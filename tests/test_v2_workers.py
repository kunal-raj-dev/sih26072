"""Tests for Asynchronous Ingestion Workers and Sliding Buffer (Phase 11 / TASK-V2-11.1).

Covers:
1. Thread-safe sliding buffer insertion, temporal filtering, capacity pruning, and dedup.
2. IngestionWorker lifecycle (start, is_running, stop, loop shutdown).
3. IngestionWorker single-pass poll (MOSDAC, GFS, IMERG, LIS) into sliding buffer.
4. Fast recovery and non-blocking resilience on unconfigured / network-error feeds.
5. FastAPI endpoints: GET /api/v1/workers/status and POST /api/v1/workers/poll.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from starlette.testclient import TestClient

from vajra.api.app import create_app
from vajra.config import load_settings
from vajra.schemas import (
    DataMode,
    GridMeta,
    Modality,
    ObsFrame,
    ObsFrameMeta,
    QualityInfo,
    QualityStatus,
)
from vajra.workers.buffer import SlidingBuffer
from vajra.workers.ingestion import IngestionWorker


def _make_dummy_frame(
    modality: Modality,
    var: str,
    t: datetime,
    val: float = 1.0,
) -> ObsFrame:
    gm = GridMeta(name="test_grid", lat0=25.0, lon0=85.0, dlat=0.1, dlon=0.1, nlat=10, nlon=10)
    meta = ObsFrameMeta(
        source="test_source",
        modality=modality,
        variable=var,
        units="test_units",
        time=t,
        grid=gm,
        mode=DataMode.SIMULATION,
        quality=QualityInfo(status=QualityStatus.OK),
    )
    field = np.full((10, 10), val, dtype=np.float32)
    return ObsFrame(meta=meta, field=field)


# ---------------------------------------------------------------------------
# 1. Sliding Buffer Unit Tests
# ---------------------------------------------------------------------------
def test_sliding_buffer_insertion_and_temporal_retrieval():
    """Verify sliding buffer maintains time ordering and returns correct time windows."""
    buf = SlidingBuffer(max_retention_minutes=60, max_frames_per_modality=10)
    t0 = datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc)

    # Insert 3 frames at T-30, T-15, T-0
    f1 = _make_dummy_frame(Modality.SATELLITE, "bt_ir107", t0 - timedelta(minutes=30), 220.0)
    f2 = _make_dummy_frame(Modality.SATELLITE, "bt_ir107", t0 - timedelta(minutes=15), 215.0)
    f3 = _make_dummy_frame(Modality.SATELLITE, "bt_ir107", t0, 210.0)

    buf.put(Modality.SATELLITE, f2)  # Insert out of order
    buf.put(Modality.SATELLITE, f1)
    buf.put(Modality.SATELLITE, f3)

    # Query last 20 minutes from t0 -> should get f2 and f3
    hist_20 = buf.get_history(Modality.SATELLITE, t0, 20)
    assert len(hist_20) == 2
    assert hist_20[0].meta.time == t0 - timedelta(minutes=15)
    assert hist_20[1].meta.time == t0

    # Query last 45 minutes -> should get all 3
    hist_45 = buf.get_history(Modality.SATELLITE, t0, 45)
    assert len(hist_45) == 3

    # get_latest
    latest = buf.get_latest(Modality.SATELLITE)
    assert latest is not None
    assert latest.meta.time == t0
    assert latest.field[0, 0] == 210.0


def test_sliding_buffer_deduplication_and_capacity_limit():
    """Verify buffer deduplicates duplicate timestamps and respects max frame capacity."""
    buf = SlidingBuffer(max_retention_minutes=120, max_frames_per_modality=5)
    t0 = datetime(2026, 4, 18, 10, 0, tzinfo=timezone.utc)

    # Insert 8 frames
    for i in range(8):
        t = t0 + timedelta(minutes=i * 10)
        f = _make_dummy_frame(Modality.RADAR, "vil", t, float(i))
        buf.put(Modality.RADAR, f)

    # Capacity limit is 5 -> should only keep the latest 5 (i=3..7)
    summary = buf.summary()
    assert summary["modalities"]["radar"]["count"] == 5

    hist = buf.get_history(Modality.RADAR, t0 + timedelta(minutes=100), 120)
    assert len(hist) == 5
    assert hist[-1].field[0, 0] == 7.0

    # Updating existing timestamp should replace rather than append
    f_updated = _make_dummy_frame(Modality.RADAR, "vil", t0 + timedelta(minutes=70), 99.0)
    buf.put(Modality.RADAR, f_updated)
    assert buf.summary()["modalities"]["radar"]["count"] == 5
    latest = buf.get_latest(Modality.RADAR)
    assert latest.field[0, 0] == 99.0


# ---------------------------------------------------------------------------
# 2. IngestionWorker Single-Pass Polling Test
# ---------------------------------------------------------------------------
def test_ingestion_worker_poll_all_once():
    """Verify IngestionWorker polls all 4 sources and populates the sliding buffer."""
    settings = load_settings()
    buf = SlidingBuffer(max_retention_minutes=240)
    worker = IngestionWorker(settings, buffer=buf)

    now = datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc)
    results = worker.poll_all_once(now=now)

    assert "mosdac" in results
    assert "gfs" in results
    assert "imerg" in results
    assert "lis" in results

    # Verify no unhandled exceptions were raised
    for src, res in results.items():
        assert res["latency_ms"] >= 0.0
        assert "status" in res

    # Status summary reflects polling counts
    status = worker.status()
    assert status["worker_running"] is False
    assert status["sources"]["mosdac"]["poll_count"] == 1
    assert status["sources"]["gfs"]["poll_count"] == 1
    assert "buffer" in status


# ---------------------------------------------------------------------------
# 3. IngestionWorker Lifecycle Thread Test
# ---------------------------------------------------------------------------
def test_ingestion_worker_thread_lifecycle():
    """Verify worker thread starts, runs, and stops cleanly."""
    settings = load_settings()
    # High-frequency poll intervals for rapid testing
    test_intervals = {
        "mosdac": 0.2,
        "gfs": 0.2,
        "imerg": 0.2,
        "lis": 0.2,
    }
    worker = IngestionWorker(settings, poll_intervals_sec=test_intervals)
    assert worker.is_running() is False

    worker.start()
    assert worker.is_running() is True

    # Allow daemon to execute at least one background poll cycle
    time.sleep(0.5)

    status = worker.status()
    assert status["worker_running"] is True
    assert status["sources"]["mosdac"]["poll_count"] >= 1

    worker.stop(timeout_sec=2.0)
    assert worker.is_running() is False


# ---------------------------------------------------------------------------
# 4. API Endpoints for Workers & Buffer Diagnostics
# ---------------------------------------------------------------------------
def test_worker_api_endpoints():
    """Verify GET /api/v1/workers/status and POST /api/v1/workers/poll endpoints."""
    app = create_app()
    client = TestClient(app)

    # 1. GET worker status
    r_status = client.get("/api/v1/workers/status")
    assert r_status.status_code == 200
    data = r_status.json()
    assert "worker_running" in data
    assert "intervals_sec" in data
    assert "sources" in data
    assert "buffer" in data
    assert "mosdac" in data["sources"]

    # 2. POST worker manual poll
    r_poll = client.post("/api/v1/workers/poll")
    assert r_poll.status_code == 200
    poll_res = r_poll.json()
    assert "mosdac" in poll_res
    assert "gfs" in poll_res
    assert "imerg" in poll_res
    assert "lis" in poll_res
