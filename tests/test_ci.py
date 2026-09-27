"""Verification suite for Phase 7: Convective Initiation (CI) Precursor Detection Engine.

Covers:
1. Physical decision tree thresholding:
   - Cloud-top cooling rate: dT_b / dt <= -4.0 K / 15 min
   - Freezing level glaciation: T_b(IR1) <= 273.15 K
   - Tri-spectral saturation: (T_IR1 - T_WV) >= -1.0 K
   - Pre-convective screening: Radar MaxZ < 35.0 dBZ
2. Rejection of mature storms (radar >= 35 dBZ) to ensure CI identifies only initiating cells.
3. Rejection of warm/stable clouds (cooling > -4.0 K or T_b > 273.15 K).
4. Spatial grouping, polygon coordinates, and centroid calculations.
5. Physics-based P(CI) scoring and estimated lead time to first lightning flash (15-45 min).
6. Cycle frame extraction helper with SEVIR and MOSDAC scaling.
"""

from __future__ import annotations

from datetime import datetime, timezone
import numpy as np
import pytest

from vajra.grid import make_india_grid
from vajra.schemas import CICandidate, Modality, ObsFrame, ObsFrameMeta, QualityInfo, QualityStatus
from vajra.models.ci import detect_convective_initiation, extract_ci_candidates_from_cycle


@pytest.fixture
def test_grid():
    return make_india_grid(step_deg=0.1)


def test_ci_detection_vigorous_updraft(test_grid):
    """Test detection of a vigorous pre-convective updraft fulfilling all 4 physical criteria."""
    h, w = test_grid.nlat, test_grid.nlon

    # Baseline ambient warm clear sky / low cloud: 290 K
    ir_prev = np.full((h, w), 290.0, dtype=np.float32)
    ir_curr = np.full((h, w), 290.0, dtype=np.float32)
    wv_curr = np.full((h, w), 245.0, dtype=np.float32)
    radar_dbz = np.zeros((h, w), dtype=np.float32)

    # Insert an initiating convective core around pixel (50, 50)
    # Cooling from 275 K down to 245 K in 15 min (-30 K / 15 min cooling)
    # Cloud top reaches 245 K (< 273.15 K)
    # Deep saturation: WV is 246 K, so (IR - WV) = -1.0 K >= -1.0 K
    # Radar is 15 dBZ (pre-radar, no mature echo yet)
    cy, cx = 50, 50
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            if dy**2 + dx**2 <= 4:
                ir_prev[cy + dy, cx + dx] = 275.0
                ir_curr[cy + dy, cx + dx] = 245.0
                wv_curr[cy + dy, cx + dx] = 245.5
                radar_dbz[cy + dy, cx + dx] = 18.0

    candidates = detect_convective_initiation(
        ir_t0=ir_curr,
        ir_t_prev=ir_prev,
        wv_t0=wv_curr,
        radar_maxz=radar_dbz,
        grid=test_grid,
        dt_minutes=15.0,
    )

    assert len(candidates) == 1
    cand = candidates[0]
    assert isinstance(cand, CICandidate)
    # Cooling rate must be severe (around -30 K / 15 min)
    assert cand.cooling_rate_k_per_15m <= -4.0
    # Minimum IR temperature must be well below freezing
    assert cand.ir_brightness_temp_k <= 273.15
    # High probability of initiation for vigorous cooling
    assert cand.p_initiation >= 0.70
    # Estimated lead time should be short for rapid cooling (15 to 30 min)
    assert 15 <= cand.estimated_lead_min <= 30
    # Centroid coordinates should be close to pixel (50, 50)
    expected_lat = test_grid.lat0 + 50 * test_grid.dlat
    expected_lon = test_grid.lon0 + 50 * test_grid.dlon
    assert abs(cand.centroid_lat - expected_lat) < 0.2
    assert abs(cand.centroid_lon - expected_lon) < 0.2
    assert len(cand.polygon) == 5  # closed GeoJSON polygon


def test_ci_rejection_mature_storm(test_grid):
    """Test that mature storms (radar >= 35 dBZ) are rejected to prevent duplicate tracking."""
    h, w = test_grid.nlat, test_grid.nlon
    ir_prev = np.full((h, w), 275.0, dtype=np.float32)
    ir_curr = np.full((h, w), 235.0, dtype=np.float32)
    radar_dbz = np.full((h, w), 52.0, dtype=np.float32)  # Severe mature storm core

    candidates = detect_convective_initiation(
        ir_t0=ir_curr,
        ir_t_prev=ir_prev,
        wv_t0=None,
        radar_maxz=radar_dbz,
        grid=test_grid,
        dt_minutes=15.0,
    )
    # Must be rejected because it is already a mature storm tracked by radar
    assert len(candidates) == 0


def test_ci_rejection_slow_cooling_or_warm_cloud(test_grid):
    """Test that warm low clouds or slowly cooling clouds are rejected."""
    h, w = test_grid.nlat, test_grid.nlon
    # Case A: Cooling rate is too weak (-2.0 K / 15 min > -4.0 K)
    ir_prev_a = np.full((h, w), 260.0, dtype=np.float32)
    ir_curr_a = np.full((h, w), 258.0, dtype=np.float32)
    cands_a = detect_convective_initiation(
        ir_t0=ir_curr_a, ir_t_prev=ir_prev_a, wv_t0=None, radar_maxz=None, grid=test_grid,
    )
    assert len(cands_a) == 0

    # Case B: Fast cooling, but cloud top is still warm (> 273.15 K)
    ir_prev_b = np.full((h, w), 305.0, dtype=np.float32)
    ir_curr_b = np.full((h, w), 285.0, dtype=np.float32)  # cooled 20 K but at 285 K
    cands_b = detect_convective_initiation(
        ir_t0=ir_curr_b, ir_t_prev=ir_prev_b, wv_t0=None, radar_maxz=None, grid=test_grid,
    )
    assert len(cands_b) == 0


def test_extract_ci_candidates_from_cycle_frames(test_grid):
    """Test extraction of CI candidates from observation frames."""
    t0 = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 6, 15, 14, 15, tzinfo=timezone.utc)
    h, w = test_grid.nlat, test_grid.nlon

    # Satellite frames in Kelvin
    sat_data0 = np.full((h, w), 280.0, dtype=np.float32)
    sat_data1 = np.full((h, w), 280.0, dtype=np.float32)

    # Convective initiation anomaly
    sat_data0[30:35, 30:35] = 275.0
    sat_data1[30:35, 30:35] = 240.0  # -35 K cooling
    from vajra.schemas import DataMode, GridMeta

    grid_meta = GridMeta(
        name=test_grid.name,
        lat0=test_grid.lat0,
        lon0=test_grid.lon0,
        dlat=test_grid.dlat,
        dlon=test_grid.dlon,
        nlat=test_grid.nlat,
        nlon=test_grid.nlon,
    )
    meta0 = ObsFrameMeta(
        source="test",
        modality=Modality.SATELLITE,
        variable="ir_108",
        units="K",
        time=t0,
        grid=grid_meta,
        mode=DataMode.REPLAY,
        quality=QualityInfo(status=QualityStatus.OK),
    )
    meta1 = ObsFrameMeta(
        source="test",
        modality=Modality.SATELLITE,
        variable="ir_108",
        units="K",
        time=t1,
        grid=grid_meta,
        mode=DataMode.REPLAY,
        quality=QualityInfo(status=QualityStatus.OK),
    )
    f0 = ObsFrame(meta=meta0, field=sat_data0)
    f1 = ObsFrame(meta=meta1, field=sat_data1)

    cands = extract_ci_candidates_from_cycle(
        satellite_frames=[f0, f1],
        radar_frames=[],
        grid=test_grid,
    )

    assert len(cands) == 1
    assert cands[0].p_initiation > 0.5
    assert cands[0].cooling_rate_k_per_15m < -4.0
