"""Verification suite for Phase V2-5:
Dynamic Kinematics & Hybrid Semi-Lagrangian Advection.

Covers:
- TASK-V2-5.1:
  - Convective Cell Lifecycle Classification (INITIATING, INTENSIFYING, MATURE, DECAYING, SPLIT, MERGE).
  - Volumetric growth rate tracking (dArea/dt in km^2/h, dVIL/dt in dBZ/h).
  - CellTracker multi-cycle lifecycle transitions.

- TASK-V2-5.2:
  - Semi-Lagrangian advection with exponential predictability decay:
    P_advected(x, y, t + dt) = P(x - u*dt, y - v*dt, t) * exp(-dt / tau_decay)
  - Dynamic decay timescales tau: 45 min (initiating) vs 75 min (mature squall lines).
  - Multi-horizon advection up to 90 minutes with progressive spatial diffusion.

- TASK-V2-5.3:
  - Elimination of rectangular bounding-box dilation.
  - Anisotropic continuous Gaussian kernel oriented along the storm motion vector (sigma_parallel = 2.5 * sigma_perp)
    modeling downwind anvil blow-off.
  - Spatial gradient smoothness verification (zero step-function discontinuities).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
import scipy.ndimage as ndi

from vajra.cells import (
    CellTracker,
    Detection,
    classify_cell_lifecycle,
    compute_kinematic_acceleration,
)
from vajra.config import CellsConfig
from vajra.grid import india_grid
from vajra.models.field_nowcast import (
    extrapolate_lagrangian_advection,
    generate_continuous_probability_field,
    get_lifecycle_tau_decay,
)
from vajra.models.painting import paint_probability
from vajra.schemas import Cell, StormLifecycleState


# =============================================================================
# 1. TASK-V2-5.1: Convective Cell Lifecycle Classification
# =============================================================================

def test_classify_cell_lifecycle_initiating():
    """Verify single or first-detection cells are classified as INITIATING."""
    t0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    det0 = Detection(
        time=t0, centroid_i=10.0, centroid_j=10.0, centroid_lat=20.0, centroid_lon=80.0,
        bbox=(8, 8, 12, 12), area_px=16, max_intensity=35.0, mean_intensity=30.0,
    )
    px_area_km2 = 25.0  # 5km x 5km

    state, d_area, d_vil = classify_cell_lifecycle([det0], px_area_km2)
    assert state == StormLifecycleState.INITIATING
    assert d_area == 0.0
    assert d_vil == 0.0


def test_classify_cell_lifecycle_intensifying():
    """Verify cells with expanding area or increasing reflectivity are INTENSIFYING."""
    t0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=15)  # 0.25 h
    px_area_km2 = 25.0

    det0 = Detection(
        time=t0, centroid_i=10.0, centroid_j=10.0, centroid_lat=20.0, centroid_lon=80.0,
        bbox=(8, 8, 12, 12), area_px=10, max_intensity=35.0, mean_intensity=30.0,
    )
    # Area grows from 10 -> 20 px (+250 km^2 in 0.25h = +1000 km^2/h); max dBZ grows 35 -> 48 dBZ
    det1 = Detection(
        time=t1, centroid_i=10.0, centroid_j=10.0, centroid_lat=20.0, centroid_lon=80.0,
        bbox=(7, 7, 13, 13), area_px=20, max_intensity=48.0, mean_intensity=40.0,
    )

    state, d_area, d_vil = classify_cell_lifecycle([det0, det1], px_area_km2)
    assert state == StormLifecycleState.INTENSIFYING
    assert d_area > 15.0
    assert d_vil > 5.0


def test_classify_cell_lifecycle_decaying():
    """Verify cells with collapsing area and diminishing core reflectivity are DECAYING."""
    t0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=15)
    px_area_km2 = 25.0

    det0 = Detection(
        time=t0, centroid_i=10.0, centroid_j=10.0, centroid_lat=20.0, centroid_lon=80.0,
        bbox=(5, 5, 15, 15), area_px=50, max_intensity=52.0, mean_intensity=42.0,
    )
    # Area collapses 50 -> 25 px; max dBZ collapses 52 -> 36 dBZ
    det1 = Detection(
        time=t1, centroid_i=10.0, centroid_j=10.0, centroid_lat=20.0, centroid_lon=80.0,
        bbox=(7, 7, 13, 13), area_px=25, max_intensity=36.0, mean_intensity=30.0,
    )

    state, d_area, d_vil = classify_cell_lifecycle([det0, det1], px_area_km2)
    assert state == StormLifecycleState.DECAYING
    assert d_area < -15.0
    assert d_vil < -5.0


def test_classify_cell_lifecycle_mature():
    """Verify mature cores with steady area and severe reflectivity are MATURE."""
    t0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=10)
    t2 = t1 + timedelta(minutes=10)
    px_area_km2 = 25.0

    dets = [
        Detection(time=t0, centroid_i=10.0, centroid_j=10.0, centroid_lat=20.0, centroid_lon=80.0,
                  bbox=(6, 6, 14, 14), area_px=40, max_intensity=50.0, mean_intensity=44.0),
        Detection(time=t1, centroid_i=10.1, centroid_j=10.1, centroid_lat=20.02, centroid_lon=80.02,
                  bbox=(6, 6, 14, 14), area_px=41, max_intensity=51.0, mean_intensity=45.0),
        Detection(time=t2, centroid_i=10.2, centroid_j=10.2, centroid_lat=20.04, centroid_lon=80.04,
                  bbox=(6, 6, 14, 14), area_px=41, max_intensity=50.5, mean_intensity=44.5),
    ]

    state, d_area, d_vil = classify_cell_lifecycle(dets, px_area_km2)
    assert state == StormLifecycleState.MATURE
    assert abs(d_area) <= 15.0
    assert abs(d_vil) <= 5.0


def test_classify_cell_lifecycle_split_and_merge():
    """Verify explicit split and merge lifecycle flags."""
    px_area_km2 = 25.0
    state_s, _, _ = classify_cell_lifecycle([], px_area_km2, is_split=True)
    assert state_s == StormLifecycleState.SPLIT

    state_m, _, _ = classify_cell_lifecycle([], px_area_km2, is_merge=True)
    assert state_m == StormLifecycleState.MERGE


def test_cell_tracker_lifecycle_evolution():
    """Verify CellTracker steps through lifecycle states: INITIATING -> INTENSIFYING -> DECAYING."""
    grid = india_grid(0.25)
    cfg = CellsConfig(vil_threshold=40.0, min_area_px=2, max_track_speed_km_h=200.0)
    tracker = CellTracker(grid, cfg, cycle_minutes=10)

    t0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=10)
    t2 = t1 + timedelta(minutes=10)

    def make_field(c_lat: float, c_lon: float, size: int, peak_val: float) -> np.ndarray:
        f = np.zeros((grid.nlat, grid.nlon), dtype=np.float32)
        idx = grid.index_of(c_lat, c_lon)
        assert idx is not None
        ci, cj = idx
        f[max(0, ci - size):min(grid.nlat, ci + size + 1),
          max(0, cj - size):min(grid.nlon, cj + size + 1)] = peak_val
        return f

    # Step 1: Small emerging cell (size=1 -> 9 pixels, peak=45)
    f0 = make_field(20.0, 80.0, size=1, peak_val=45.0)
    c0 = tracker.step(t0, f0)
    assert len(c0) == 1
    assert c0[0].lifecycle_state == StormLifecycleState.INITIATING
    assert c0[0].d_area_dt == 0.0

    # Step 2: Explosive intensification (size=3 -> 49 pixels, peak=65)
    f1 = make_field(20.02, 80.02, size=3, peak_val=65.0)
    c1 = tracker.step(t1, f1)
    assert len(c1) == 1
    assert c1[0].id == c0[0].id
    assert c1[0].lifecycle_state == StormLifecycleState.INTENSIFYING
    assert c1[0].d_area_dt > 0.0
    assert c1[0].d_vil_dt > 0.0

    # Step 3: Rapid collapse (size=1 -> 9 pixels, peak=42)
    f2 = make_field(20.04, 80.04, size=1, peak_val=42.0)
    c2 = tracker.step(t2, f2)
    assert len(c2) == 1
    assert c2[0].id == c0[0].id
    assert c2[0].lifecycle_state == StormLifecycleState.DECAYING
    assert c2[0].d_area_dt < 0.0
    assert c2[0].d_vil_dt < 0.0


# =============================================================================
# 2. TASK-V2-5.2: Semi-Lagrangian Advection with Predictability Decay
# =============================================================================

def test_lifecycle_tau_decay_timescales():
    """Verify predictability decay timescale tau varies dynamically with lifecycle state."""
    assert get_lifecycle_tau_decay(StormLifecycleState.INITIATING) == 45.0
    assert get_lifecycle_tau_decay(StormLifecycleState.SPLIT) == 45.0
    assert get_lifecycle_tau_decay(StormLifecycleState.INTENSIFYING) == 60.0
    assert get_lifecycle_tau_decay(StormLifecycleState.DECAYING) == 60.0
    assert get_lifecycle_tau_decay(StormLifecycleState.MATURE) == 75.0
    assert get_lifecycle_tau_decay(StormLifecycleState.MERGE) == 75.0
    assert get_lifecycle_tau_decay(None) == 60.0


def test_extrapolate_lagrangian_advection_decay_comparison():
    """Verify that initiating cells decay faster than mature squall lines under advection."""
    h, w = 60, 60
    base_field = np.full((h, w), 0.05, dtype=np.float32)
    base_field[25:35, 25:35] = 0.85

    # Advect for dt = 60 min (lead=60, base_lead=0)
    advected_init = extrapolate_lagrangian_advection(
        p_grid_base=base_field,
        u_px=1.0,
        v_px=1.0,
        lead_minutes=60,
        base_lead=0,
        background_p=0.05,
        lifecycle_state=StormLifecycleState.INITIATING,  # tau = 45m
    )

    advected_mature = extrapolate_lagrangian_advection(
        p_grid_base=base_field,
        u_px=1.0,
        v_px=1.0,
        lead_minutes=60,
        base_lead=0,
        background_p=0.05,
        lifecycle_state=StormLifecycleState.MATURE,  # tau = 75m
    )

    # Mature storm retains higher peak probability than rapidly dissipating initiating cell
    assert float(np.max(advected_mature)) > float(np.max(advected_init))
    assert float(np.min(advected_mature)) >= 0.04
    assert float(np.min(advected_init)) >= 0.04


def test_extrapolate_lagrangian_advection_90_minutes():
    """Verify advection extrapolation for horizons up to 90 minutes."""
    h, w = 60, 60
    base_field = np.full((h, w), 0.05, dtype=np.float32)
    base_field[20:25, 20:25] = 0.90

    # Advect with u=+1.0 px/15m, v=+1.0 px/15m for 90 minutes (6 time steps)
    advected_90 = extrapolate_lagrangian_advection(
        p_grid_base=base_field,
        u_px=1.0,
        v_px=1.0,
        lead_minutes=90,
        base_lead=0,
        background_p=0.05,
        lifecycle_state=StormLifecycleState.MATURE,
    )

    assert advected_90.shape == (h, w)
    peak_y, peak_x = np.unravel_index(np.argmax(advected_90), advected_90.shape)
    # Peak must have moved northeast from ~22 to ~28
    assert peak_y > 22
    assert peak_x > 22
    assert float(np.max(advected_90)) < float(np.max(base_field))
    assert float(np.max(advected_90)) > 0.15


# =============================================================================
# 3. TASK-V2-5.3: Elimination of Rectangular Box Painting
# =============================================================================

def test_anisotropic_motion_oriented_gaussian_plume():
    """Verify anisotropic Gaussian kernel oriented along storm motion (sigma_parallel = 2.5 * sigma_perp)."""
    grid = india_grid(0.25)
    c_lat, c_lon = 20.0, 80.0
    cy_px, cx_px = grid.index_of(c_lat, c_lon)

    # Cell moving due East (heading = 90 deg, speed = 60 km/h)
    cell = Cell(
        id="C0001",
        time=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        centroid_lat=c_lat,
        centroid_lon=c_lon,
        bbox=[c_lon - 0.25, c_lat - 0.25, c_lon + 0.25, c_lat + 0.25],
        area_px=16,
        max_intensity=50.0,
        mean_intensity=40.0,
        velocity_kmh=60.0,
        heading_deg=90.0,  # Eastward
        motion_dlat=0.0,
        motion_dlon=0.1,
    )

    field = generate_continuous_probability_field(
        cells=[cell],
        p_cell={"C0001": 0.85},
        grid=grid,
        background_p=0.05,
        lead_minutes=30,
        smooth_sigma=1.0,
    )

    # Inspect plume profile along parallel axis (East, x > cx_px) vs perpendicular axis (North, y > cy_px)
    # Probability should extend further downwind (East) than across-flank (North) due to sigma_parallel = 2.5 * sigma_perp
    p_center = field[cy_px, cx_px]
    p_east_4px = field[cy_px, cx_px + 4]   # Downwind parallel
    p_north_4px = field[cy_px + 4, cx_px]  # Across perpendicular

    assert p_center > 0.50
    assert p_east_4px > p_north_4px, (
        f"Downwind parallel probability ({p_east_4px:.3f}) should exceed perpendicular ({p_north_4px:.3f})"
    )

    # Verify spatial smoothness: no rectangular step jumps
    grad_y, grad_x = np.gradient(field)
    max_grad = max(float(np.max(np.abs(grad_y))), float(np.max(np.abs(grad_x))))
    assert max_grad < 0.25, f"Maximum spatial gradient {max_grad:.3f} must be < 0.25 (no step jumps)"


def test_paint_probability_smoothness_and_interface_compatibility():
    """Verify paint_probability generates smooth continuous fields without rectangular artifacts."""
    grid = india_grid(0.25)
    c_lat, c_lon = 22.0, 82.0

    cell = Cell(
        id="C0002",
        time=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        centroid_lat=c_lat,
        centroid_lon=c_lon,
        bbox=[c_lon - 0.3, c_lat - 0.3, c_lon + 0.3, c_lat + 0.3],
        area_px=20,
        max_intensity=55.0,
        mean_intensity=45.0,
        velocity_kmh=40.0,
        heading_deg=45.0,
    )

    p_field = paint_probability(
        p_cell={"C0002": 0.90},
        cells=[cell],
        grid=grid,
        background_p=0.05,
    )

    assert p_field.shape == (grid.nlat, grid.nlon)
    assert float(np.max(p_field)) > 0.50
    assert float(np.min(p_field)) >= 0.04

    # Spatial continuity: verify no rectangular boundaries
    grad_y, grad_x = np.gradient(p_field)
    max_grad = max(float(np.max(np.abs(grad_y))), float(np.max(np.abs(grad_x))))
    assert max_grad < 0.25
