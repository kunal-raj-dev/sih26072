"""Asynchronous Ingestion Worker Engine (Phase 11 / TASK-V2-11.1).

Periodically polls MOSDAC (15 min), NOAA GFS (6 hr), and NASA IMERG (30 min)
asynchronously in the background, populating an in-memory sliding buffer so
the core FastAPI nowcasting engine never blocks on external network calls.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from ..config import Settings
from ..logsetup import get_logger, log_event
from ..providers import (
    GfsNcepProvider,
    ImergProvider,
    LisProvider,
    MosdacProvider,
)
from ..schemas import Modality
from .buffer import SlidingBuffer

logger = get_logger("vajra.workers.ingestion")


class IngestionWorker:
    """Manages asynchronous background polling across remote atmospheric data feeds."""

    def __init__(
        self,
        settings: Settings,
        buffer: SlidingBuffer | None = None,
        poll_intervals_sec: dict[str, float] | None = None,
    ):
        self.settings = settings
        self.buffer = buffer or SlidingBuffer(max_retention_minutes=240)

        # Polling intervals (can be tuned down for tests or high-frequency mode)
        # Default operational cadence: MOSDAC 15m, GFS 6h, IMERG 30m, LIS 10m
        default_intervals = {
            "mosdac": 15.0 * 60.0,
            "gfs": 360.0 * 60.0,
            "imerg": 30.0 * 60.0,
            "lis": 10.0 * 60.0,
        }
        self.intervals = {**default_intervals, **(poll_intervals_sec or {})}

        # Providers
        self.mosdac = MosdacProvider(settings)
        self.gfs = GfsNcepProvider(settings)
        self.imerg = ImergProvider(settings)
        self.lis = LisProvider(settings)

        # Threading state
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Telemetry & Status
        self._last_polled: dict[str, datetime | None] = {k: None for k in self.intervals}
        self._poll_counts: dict[str, int] = {k: 0 for k in self.intervals}
        self._error_counts: dict[str, int] = {k: 0 for k in self.intervals}
        self._last_latencies_ms: dict[str, float] = {k: 0.0 for k in self.intervals}
        self._status_messages: dict[str, str] = {k: "Initialized" for k in self.intervals}

    # ---------------------------------------------------------------------------
    # Lifecycle Controls
    # ---------------------------------------------------------------------------
    def start(self) -> None:
        """Starts the background worker thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="vajra-ingestion-worker",
                daemon=True,
            )
            self._thread.start()
            log_event(logger, 20, "asynchronous ingestion worker started", intervals=self.intervals)

    def stop(self, timeout_sec: float = 5.0) -> None:
        """Signals the worker thread to stop and waits for exit."""
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                return
            self._stop_event.set()
            self._thread.join(timeout=timeout_sec)
            self._thread = None
            log_event(logger, 20, "asynchronous ingestion worker stopped")

    def is_running(self) -> bool:
        """Returns True if the background worker thread is currently running."""
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    # ---------------------------------------------------------------------------
    # Polling Execution
    # ---------------------------------------------------------------------------
    def poll_all_once(self, now: datetime | None = None) -> dict[str, Any]:
        """Synchronously executes a single poll pass across all 4 providers.

        Useful for test fixtures, warmup passes, or forced manual refresh.
        """
        t = now or datetime.now(timezone.utc)
        results = {}
        for source in ["mosdac", "gfs", "imerg", "lis"]:
            results[source] = self._poll_source(source, t)
        return results

    def _poll_source(self, source: str, now: datetime) -> dict[str, Any]:
        """Polls an individual data source and commits frames to the sliding buffer."""
        t0 = time.perf_counter()
        frames_added = 0
        error = None

        try:
            if source == "mosdac":
                # Ingest recent INSAT-3D/3DR satellite frames (last 60 min)
                frames = self.mosdac.get_history(now, 60)
                if frames:
                    frames_added = self.buffer.put_many(Modality.SATELLITE, frames)
                    self._status_messages[source] = f"Ingested {len(frames)} satellite frame(s)"
                else:
                    self._status_messages[source] = "Idle: no new satellite frames available"

            elif source == "gfs":
                # Ingest NOAA GFS NWP model frames
                frames = self.gfs.get_history(now, 720)
                if frames:
                    frames_added = self.buffer.put_many(Modality.MODEL, frames)
                    self._status_messages[source] = f"Ingested {len(frames)} NWP frame(s)"
                else:
                    self._status_messages[source] = "Idle: no new NWP cycles"

            elif source == "imerg":
                # Ingest NASA IMERG precipitation frames
                frames = self.imerg.get_history(now, 120)
                if frames:
                    frames_added = self.buffer.put_many(Modality.SURFACE, frames)
                    self._status_messages[source] = f"Ingested {len(frames)} IMERG precipitation frame(s)"
                else:
                    self._status_messages[source] = "Idle: no new precipitation frames"

            elif source == "lis":
                # Ingest NASA ISS-LIS lightning frames
                frames = self.lis.get_history(now, 120)
                if frames:
                    frames_added = self.buffer.put_many(Modality.LIGHTNING, frames)
                    self._status_messages[source] = f"Ingested {len(frames)} lightning frame(s)"
                else:
                    self._status_messages[source] = "Idle: no new lightning frames"

            self._poll_counts[source] += 1
            self._last_polled[source] = now

        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            self._error_counts[source] += 1
            self._status_messages[source] = f"Ingestion error: {exc}"
            log_event(logger, 30, f"error polling {source}", error=error)

        finally:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            self._last_latencies_ms[source] = round(dt_ms, 2)

        return {
            "source": source,
            "frames_added": frames_added,
            "latency_ms": self._last_latencies_ms[source],
            "status": self._status_messages[source],
            "error": error,
        }

    def _run_loop(self) -> None:
        """Internal daemon loop checking timer expirations."""
        last_run = {k: 0.0 for k in self.intervals}

        while not self._stop_event.is_set():
            t_now_sec = time.time()
            now_dt = datetime.now(timezone.utc)

            for source, interval_sec in self.intervals.items():
                if self._stop_event.is_set():
                    break
                if t_now_sec - last_run[source] >= interval_sec:
                    self._poll_source(source, now_dt)
                    last_run[source] = t_now_sec

            # Sleep in short increments to allow rapid shutdown response
            self._stop_event.wait(timeout=1.0)

    # ---------------------------------------------------------------------------
    # Diagnostics & Telemetry
    # ---------------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        """Provides full operational health and ingestion metrics."""
        return {
            "worker_running": self.is_running(),
            "intervals_sec": dict(self.intervals),
            "sources": {
                s: {
                    "last_polled": self._last_polled[s].isoformat() if self._last_polled[s] else None,
                    "poll_count": self._poll_counts[s],
                    "error_count": self._error_counts[s],
                    "last_latency_ms": self._last_latencies_ms[s],
                    "status_message": self._status_messages[s],
                }
                for s in self.intervals
            },
            "buffer": self.buffer.summary(),
        }
