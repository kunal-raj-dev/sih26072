"""Verification test suite for Phase V2-2:
Convective Initiation (CI) & Pre-Radar Precursor Engine.

Covers:
- TASK-V2-2.1: Multi-spectral decision logic (cooling rate, glaciation, deep saturation, split-window BTD, radar MaxZ screen).
- TASK-V2-2.2: Spatial morphological clustering (8-connectivity, >= 15 km² area filter, P(CI) scoring, 15-45m lead time, tracking).
- TASK-V2-2.3: CI candidate schema & pipeline integration (2D CI plume grid, ForecastStep p_ci_grid).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from vajra.grid import GridSpec, make_india_grid
from vajra.models.ci import (
    detect_convective_initiation,
    extract_ci_candidates_from_cycle,
    generate_ci_probability_grid,
    track_ci_candidates,
)
from vajra.schemas import (
    CICandidate,
    DataMode,
    GridMeta,
    Modality,
    ObsFrame,
    ObsFrameMeta,
    QualityInfo,
    QualityStatus,
)


@pytest.fixture
def pilot_grid():
    """High-resolution pilot grid for Eastern India convective corridor."""
    return GridSpec(
        name="pilot_ci_domain",
        lat0=22.0,
        lon0=83.0,
        dlat=0.1,
        dlon=0.1,
        nlat=50,
        nlon=50,
        geolocation="exact",
    )


# =============================================================================
# 1. TASK-V2-2.1: Multi-Spectral Scientific Decision Logic
# =============================================================================

def test_ci_detection_synthetic_cooling_cloud_top(pilot_grid):
    """Verify that a synthetic cooling cloud top (-6 K / 15 min) with Tb=260 K
    and Reflectivity=15 dBZ triggers a valid CICandidate."""
    h, w = pilot_grid.nlat, pilot_grid.nlon

    # Ambient warm clear-sky/low-cloud baseline (290 K)
    ir_prev = np.full((h, w), 290.0, dtype=np.float32)
    ir_curr = np.full((h, w), 290.0, dtype=np.float32)
    wv_curr = np.full((h, w), 245.0, dtype=np.float32)
    radar_dbz = np.zeros((h, w), dtype=np.float32)

    # Insert an initiating convective core at (25, 25):
    # Cooled from 266 K down to 260 K (-6 K / 15 min cooling)
    # Reached 260 K (<= 273.15 K freezing level)
    # WV is 260.5 K (IR - WV = -0.5 K >= -1.0 K deep saturation)
    # Radar is 15 dBZ (< 35 dBZ pre-radar echo)
    cy, cx = 25, 25
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            if dy ** 2 + dx ** 2 <= 4:
                ir_prev[cy + dy, cx + dx] = 266.0
                ir_curr[cy + dy, cx + dx] = 260.0
                wv_curr[cy + dy, cx + dx] = 260.5
                radar_dbz[cy + dy, cx + dx] = 15.0

    candidates = detect_convective_initiation(
        ir_t0=ir_curr,
        ir_t_prev=ir_prev,
        wv_t0=wv_curr,
        radar_maxz=radar_dbz,
        grid=pilot_grid,
        dt_minutes=15.0,
    )

    assert len(candidates) == 1, "Expected exactly 1 CICandidate to be detected"
    cand = candidates[0]
    assert isinstance(cand, CICandidate)
    assert cand.cooling_rate_k_per_15m <= -4.0
    assert cand.ir_brightness_temp_k <= 273.15
    assert cand.area_km2 >= 15.0
    assert 0.40 <= cand.p_initiation <= 0.95
    assert 15 <= cand.estimated_lead_min <= 45
    assert len(cand.polygon) == 5
    assert len(cand.bbox) == 4


def test_ci_mature_storm_radar_suppression(pilot_grid):
    """Verify that an already mature thunderstorm (Reflectivity=45 dBZ)
    is correctly suppressed by the pre-convective radar screen."""
    h, w = pilot_grid.nlat, pilot_grid.nlon

    ir_prev = np.full((h, w), 270.0, dtype=np.float32)
    ir_curr = np.full((h, w), 235.0, dtype=np.float32)  # -35 K intense cooling
    radar_dbz = np.full((h, w), 45.0, dtype=np.float32)  # Mature storm core >= 35 dBZ

    candidates = detect_convective_initiation(
        ir_t0=ir_curr,
        ir_t_prev=ir_prev,
        wv_t0=None,
        radar_maxz=radar_dbz,
        grid=pilot_grid,
        dt_minutes=15.0,
    )

    assert len(candidates) == 0, "Mature storm (45 dBZ) must be suppressed by radar mask"


def test_ci_split_window_btd_criterion(pilot_grid):
    """Verify split-window brightness temperature difference (TIR1 - TIR2) integration."""
    h, w = pilot_grid.nlat, pilot_grid.nlon

    ir_prev = np.full((h, w), 290.0, dtype=np.float32)
    ir_curr = np.full((h, w), 290.0, dtype=np.float32)
    tir2_curr = np.full((h, w), 290.0, dtype=np.float32)
    radar_dbz = np.zeros((h, w), dtype=np.float32)

    cy, cx = 20, 20
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            if dy ** 2 + dx ** 2 <= 4:
                ir_prev[cy + dy, cx + dx] = 275.0
                ir_curr[cy + dy, cx + dx] = 250.0  # -25 K cooling
                tir2_curr[cy + dy, cx + dx] = 249.0  # Split difference = +1.0 K (<= 3.0 K)
                radar_dbz[cy + dy, cx + dx] = 12.0

    candidates = detect_convective_initiation(
        ir_t0=ir_curr,
        ir_t_prev=ir_prev,
        wv_t0=None,
        radar_maxz=radar_dbz,
        grid=pilot_grid,
        tir2_t0=tir2_curr,
        split_window_max_k=3.0,
    )

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.split_window_btd_k is not None
    assert abs(cand.split_window_btd_k - 1.0) < 0.2


# =============================================================================
# 2. TASK-V2-2.2: Spatial Morphological Clustering & Tracking
# =============================================================================

def test_ci_area_filtering_suppresses_sub_15km2_noise(pilot_grid):
    """Verify that candidate clusters with surface area < 15 km² are filtered out."""
    h, w = pilot_grid.nlat, pilot_grid.nlon

    ir_prev = np.full((h, w), 280.0, dtype=np.float32)
    ir_curr = np.full((h, w), 280.0, dtype=np.float32)

    # Isolated 1-pixel anomaly on 0.1 deg grid (~110 km² on 0.1 deg, so use high-threshold filter)
    # We explicitly test min_area_km2 thresholding:
    ir_prev[10, 10] = 270.0
    ir_curr[10, 10] = 255.0  # -15 K cooling on single pixel

    # With min_area_km2 set higher than a single pixel, it must be filtered
    candidates_filtered = detect_convective_initiation(
        ir_t0=ir_curr,
        ir_t_prev=ir_prev,
        radar_maxz=None,
        grid=pilot_grid,
        min_area_km2=500.0,  # Single pixel area (~110 km²) < 500 km²
    )
    assert len(candidates_filtered) == 0


def test_ci_candidate_tracking_and_kinematics():
    """Verify multi-cycle candidate association, velocity estimation, and track ID preservation."""
    # Previous cycle T_{-15} candidate
    prev_cand = CICandidate(
        id="ci_track_101",
        centroid_lat=24.0,
        centroid_lon=85.0,
        bbox=[84.9, 23.9, 85.1, 24.1],
        cooling_rate_k_per_15m=-6.0,
        ir_brightness_temp_k=255.0,
        ir_wv_diff_k=-0.2,
        p_initiation=0.72,
        estimated_lead_min=25,
        area_km2=60.0,
        tracked_cycles=1,
    )

    # Current cycle T_0 candidate displaced eastward by ~0.15 deg (approx 16 km over 15 min -> ~64 km/h)
    curr_cand = CICandidate(
        id="ci_temp_new",
        centroid_lat=24.05,
        centroid_lon=85.15,
        bbox=[85.05, 23.95, 85.25, 24.15],
        cooling_rate_k_per_15m=-8.0,
        ir_brightness_temp_k=248.0,
        ir_wv_diff_k=0.1,
        p_initiation=0.80,
        estimated_lead_min=20,
        area_km2=75.0,
        tracked_cycles=1,
    )

    tracked = track_ci_candidates([curr_cand], [prev_cand], dt_minutes=15.0, max_distance_km=50.0)

    assert len(tracked) == 1
    t_cand = tracked[0]
    # Inherits previous track ID
    assert t_cand.id == "ci_track_101"
    # Increments tracked cycles
    assert t_cand.tracked_cycles == 2
    # Eastward velocity u > 0, slight northward velocity v > 0
    assert t_cand.u_kmh > 40.0
    assert t_cand.v_kmh > 0.0
    # Multi-cycle persistent cooling confidence boost
    assert t_cand.p_initiation > 0.80


# =============================================================================
# 3. TASK-V2-2.3: CI Probability Plume Grid Generation & Pipeline Integration
# =============================================================================

def test_generate_ci_probability_grid(pilot_grid):
    """Verify continuous 2D CI probability field generation with spatial Gaussian plumes."""
    cand = CICandidate(
        id="ci_test_grid",
        centroid_lat=24.5,
        centroid_lon=85.5,
        bbox=[85.4, 24.4, 85.6, 24.6],
        cooling_rate_k_per_15m=-9.0,
        ir_brightness_temp_k=242.0,
        ir_wv_diff_k=0.2,
        p_initiation=0.85,
        estimated_lead_min=30,
        area_km2=80.0,
        u_kmh=30.0,  # Eastward advection
        v_kmh=0.0,
    )

    # 1. At 30-min lead (matches estimated lead time exactly)
    grid_30 = generate_ci_probability_grid([cand], pilot_grid, lead_minutes=30)
    assert grid_30.shape == (pilot_grid.nlat, pilot_grid.nlon)
    assert not np.isnan(grid_30).any()
    assert 0.0 <= np.max(grid_30) <= 1.0
    assert np.max(grid_30) >= 0.70, "Peak probability should be near candidate P(CI)"

    # Peak location should be displaced eastward due to u_kmh = 30 km/h (15 km east in 30 min)
    peak_y, peak_x = np.unravel_index(np.argmax(grid_30), grid_30.shape)
    peak_lat = pilot_grid.lat0 + peak_y * pilot_grid.dlat
    peak_lon = pilot_grid.lon0 + peak_x * pilot_grid.dlon
    assert peak_lon > 85.5, f"Expected advection eastward: peak at lon {peak_lon}"

    # 2. At 60-min lead (30 min past candidate lead time -> timing attenuation)
    grid_60 = generate_ci_probability_grid([cand], pilot_grid, lead_minutes=60)
    assert np.max(grid_60) < np.max(grid_30), "Probability should attenuate away from candidate lead time"


def test_extract_ci_candidates_from_multi_spectral_cycle(pilot_grid):
    """Verify multi-spectral frame extraction (TIR1, WV, TIR2) in observation cycle."""
    t0 = datetime(2026, 5, 12, 14, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 5, 12, 14, 15, tzinfo=timezone.utc)
    h, w = pilot_grid.nlat, pilot_grid.nlon

    ir_data0 = np.full((h, w), 285.0, dtype=np.float32)
    ir_data1 = np.full((h, w), 285.0, dtype=np.float32)
    wv_data = np.full((h, w), 250.0, dtype=np.float32)
    tir2_data = np.full((h, w), 284.0, dtype=np.float32)

    # Core at (30, 30)
    ir_data0[28:33, 28:33] = 270.0
    ir_data1[28:33, 28:33] = 245.0  # -25 K cooling
    wv_data[28:33, 28:33] = 246.0   # IR - WV = -1.0 K
    tir2_data[28:33, 28:33] = 244.0 # IR - TIR2 = 1.0 K

    gmeta = GridMeta(
        name=pilot_grid.name,
        lat0=pilot_grid.lat0,
        lon0=pilot_grid.lon0,
        dlat=pilot_grid.dlat,
        dlon=pilot_grid.dlon,
        nlat=pilot_grid.nlat,
        nlon=pilot_grid.nlon,
    )
    f_ir0 = ObsFrame(
        meta=ObsFrameMeta(
            source="test", modality=Modality.SATELLITE, variable="ir_108",
            units="K", time=t0, grid=gmeta, mode=DataMode.REPLAY,
            quality=QualityInfo(status=QualityStatus.OK),
        ),
        field=ir_data0,
    )
    f_ir1 = ObsFrame(
        meta=ObsFrameMeta(
            source="test", modality=Modality.SATELLITE, variable="ir_108",
            units="K", time=t1, grid=gmeta, mode=DataMode.REPLAY,
            quality=QualityInfo(status=QualityStatus.OK),
        ),
        field=ir_data1,
    )
    f_wv = ObsFrame(
        meta=ObsFrameMeta(
            source="test", modality=Modality.SATELLITE, variable="wv_68",
            units="K", time=t1, grid=gmeta, mode=DataMode.REPLAY,
            quality=QualityInfo(status=QualityStatus.OK),
        ),
        field=wv_data,
    )
    f_tir2 = ObsFrame(
        meta=ObsFrameMeta(
            source="test", modality=Modality.SATELLITE, variable="tir2_120",
            units="K", time=t1, grid=gmeta, mode=DataMode.REPLAY,
            quality=QualityInfo(status=QualityStatus.OK),
        ),
        field=tir2_data,
    )

    cands = extract_ci_candidates_from_cycle(
        satellite_frames=[f_ir0, f_ir1, f_wv, f_tir2],
        radar_frames=[],
        grid=pilot_grid,
    )

    assert len(cands) == 1
    cand = cands[0]
    assert cand.cooling_rate_k_per_15m <= -4.0
    assert cand.p_initiation >= 0.70
    assert cand.split_window_btd_k is not None
