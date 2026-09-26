from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from vajra.cells import CellTracker, detect_cells
from vajra.grid import GridSpec, india_grid
from vajra.config import CellsConfig

T0 = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)


def blob(field, lat0, lon0, dlat_deg=1.0, dlon_deg=1.0, amp=200.0):
    g = GRID
    for i, lat in enumerate(g.lats):
        for j, lon in enumerate(g.lons):
            d2 = ((lat - lat0) / dlat_deg) ** 2 + ((lon - lon0) / dlon_deg) ** 2
            field[i, j] = max(field[i, j], amp * np.exp(-d2))
    return field


GRID = india_grid(0.25)  # coarse test grid: 6-38N at 0.25 deg
CFG = CellsConfig(vil_threshold=74.0, min_area_px=4, max_track_speed_km_h=180.0)


def test_detect_two_blobs():
    field = np.zeros((GRID.nlat, GRID.nlon), dtype=np.float32)
    blob(field, 25.0, 85.0)
    blob(field, 30.0, 78.0)
    dets = detect_cells(field, 74.0, 4)
    assert len(dets) == 2
    areas = sorted(d[4] for d in dets)
    assert areas[0] >= 4


def test_no_cells_below_threshold():
    field = np.full((GRID.nlat, GRID.nlon), 50.0, dtype=np.float32)
    assert detect_cells(field, 74.0, 4) == []


def test_tracking_assigns_same_id_to_moving_blob():
    tracker = CellTracker(GRID, CFG, cycle_minutes=10)
    f1 = np.zeros((GRID.nlat, GRID.nlon), dtype=np.float32)
    blob(f1, 25.0, 85.0)
    c1 = tracker.step(T0, f1)
    assert len(c1) == 1
    f2 = np.zeros((GRID.nlat, GRID.nlon), dtype=np.float32)
    blob(f2, 25.1, 85.1)  # ~0.1 deg move in 10 min ≈ 77 km/h < gate
    c2 = tracker.step(T0 + timedelta(minutes=10), f2)
    assert len(c2) == 1
    assert c2[0].id == c1[0].id
    assert c2[0].track_age_steps == 1
    assert c2[0].motion_dlon > 0  # moving east


def test_tracking_new_id_for_far_appearances():
    tracker = CellTracker(GRID, CFG, cycle_minutes=10)
    f1 = np.zeros((GRID.nlat, GRID.nlon), dtype=np.float32)
    blob(f1, 25.0, 85.0)
    tracker.step(T0, f1)
    f2 = np.zeros((GRID.nlat, GRID.nlon), dtype=np.float32)
    blob(f2, 35.0, 95.0)  # far away: new cell
    c2 = tracker.step(T0 + timedelta(minutes=10), f2)
    assert c2[0].track_age_steps == 0


def test_predicted_path_extrapolates():
    tracker = CellTracker(GRID, CFG, cycle_minutes=10)
    f1 = np.zeros((GRID.nlat, GRID.nlon), dtype=np.float32)
    blob(f1, 25.0, 85.0)
    tracker.step(T0, f1)
    f2 = np.zeros((GRID.nlat, GRID.nlon), dtype=np.float32)
    blob(f2, 25.1, 85.1)
    tracker.step(T0 + timedelta(minutes=10), f2)
    path = tracker.predicted_path(list(tracker.tracks)[0], 60)
    assert len(path) == 2
    assert path[1][0] > path[0][0]  # continues north-east
