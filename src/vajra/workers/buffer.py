"""In-Memory Thread-Safe Sliding Observation Buffer (Phase 11 / TASK-V2-11.1).

Stores recent multi-modal atmospheric frames in memory with bounded capacity
and time-based retention to decouple external network ingestion from the
core nowcasting inference loop, preventing network stalls.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from ..schemas import Modality, ObsFrame


class SlidingBuffer:
    """Thread-safe bounded in-memory sliding buffer for real-time observation frames."""

    def __init__(self, max_retention_minutes: int = 240, max_frames_per_modality: int = 50):
        self.max_retention_minutes = max_retention_minutes
        self.max_frames_per_modality = max_frames_per_modality
        self._lock = threading.RLock()
        self._buffers: dict[str, list[ObsFrame]] = {m.value: [] for m in Modality}
        self._last_updated: dict[str, datetime] = {}
        self._drop_count: dict[str, int] = {m.value: 0 for m in Modality}

    def put(self, modality: Modality | str, frame: ObsFrame) -> None:
        """Appends a new observation frame into the sliding buffer, maintaining time sort."""
        mod_key = modality.value if isinstance(modality, Modality) else str(modality)
        with self._lock:
            buf = self._buffers.setdefault(mod_key, [])

            # Deduplicate by timestamp and variable
            t_frame = frame.meta.time
            var_frame = frame.meta.variable
            existing_idx = next(
                (i for i, f in enumerate(buf) if f.meta.time == t_frame and f.meta.variable == var_frame),
                None,
            )
            if existing_idx is not None:
                buf[existing_idx] = frame
            else:
                buf.append(frame)
                buf.sort(key=lambda f: f.meta.time)

            self._last_updated[mod_key] = datetime.now(timezone.utc)
            self._prune_locked(mod_key)

    def put_many(self, modality: Modality | str, frames: list[ObsFrame]) -> int:
        """Appends multiple frames atomically."""
        count = 0
        with self._lock:
            for f in frames:
                self.put(modality, f)
                count += 1
        return count

    def get_history(
        self,
        modality: Modality | str,
        t_target: datetime,
        minutes: int,
    ) -> list[ObsFrame]:
        """Returns frames within [t_target - minutes, t_target] for the given modality."""
        mod_key = modality.value if isinstance(modality, Modality) else str(modality)
        t_start = t_target - timedelta(minutes=minutes)
        with self._lock:
            buf = self._buffers.get(mod_key, [])
            return [f for f in buf if t_start <= f.meta.time <= t_target]

    def get_latest(self, modality: Modality | str) -> ObsFrame | None:
        """Returns the most recent frame for the modality, or None if empty."""
        mod_key = modality.value if isinstance(modality, Modality) else str(modality)
        with self._lock:
            buf = self._buffers.get(mod_key, [])
            return buf[-1] if buf else None

    def clear(self, modality: Modality | str | None = None) -> None:
        """Clears all frames or frames for a specific modality."""
        with self._lock:
            if modality is not None:
                mod_key = modality.value if isinstance(modality, Modality) else str(modality)
                self._buffers[mod_key] = []
            else:
                for k in self._buffers:
                    self._buffers[k] = []

    def _prune_locked(self, mod_key: str) -> None:
        """Enforces time retention and max frame capacity."""
        buf = self._buffers.get(mod_key, [])
        if not buf:
            return

        # Anchor retention to the latest frame in the buffer (supports live, replay, & simulation)
        newest_time = max(f.meta.time for f in buf)
        cutoff = newest_time - timedelta(minutes=self.max_retention_minutes)

        # Time retention pruning
        initial_len = len(buf)
        buf = [f for f in buf if f.meta.time >= cutoff]

        # Capacity limit pruning
        if len(buf) > self.max_frames_per_modality:
            buf = buf[-self.max_frames_per_modality:]

        dropped = initial_len - len(buf)
        if dropped > 0:
            self._drop_count[mod_key] = self._drop_count.get(mod_key, 0) + dropped

        self._buffers[mod_key] = buf

    def summary(self) -> dict[str, Any]:
        """Provides operational diagnostics and buffer inventory."""
        with self._lock:
            stats = {}
            total_frames = 0
            for mod_key, buf in self._buffers.items():
                n = len(buf)
                total_frames += n
                earliest = buf[0].meta.time.isoformat() if buf else None
                latest = buf[-1].meta.time.isoformat() if buf else None
                stats[mod_key] = {
                    "count": n,
                    "earliest": earliest,
                    "latest": latest,
                    "dropped": self._drop_count.get(mod_key, 0),
                    "last_write": self._last_updated.get(mod_key, None),
                }
            return {
                "total_frames": total_frames,
                "retention_minutes": self.max_retention_minutes,
                "modalities": stats,
            }
