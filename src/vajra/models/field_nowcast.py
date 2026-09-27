"""Continuous Probability Field Nowcasting & Lagrangian Advection Engine (Phase 7).

Replaces heuristic cell bounding-box painting with:
1. Physics-consistent, continuous 2D probability field generation without rectangular artifacts.
2. Direct deep U-Net probability field integration with spatial Gaussian contour smoothing (sigma=1.0).
3. Convective Initiation (CI) precursor plume blending at 30-60 min horizons.
4. Lagrangian advection extrapolation for outer forecast horizons (60-120 minutes)
   with exponential predictability decay exp(-dt / tau) and spatial diffusion.
5. Dual aleatoric/epistemic spatial uncertainty field generation sigma(x, y).
"""

from __future__ import annotations

import io
import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
try:
    import scipy.ndimage as ndi
except ImportError:
    from .. import ndx as ndi
from PIL import Image

from ..grid import GridSpec
from ..schemas import Cell, CICandidate, StormLifecycleState

logger = logging.getLogger(__name__)


def get_lifecycle_tau_decay(lifecycle_state: StormLifecycleState | str | None) -> float:
    """Return exponential predictability decay timescale tau in minutes.

    Research basis:
    - Initiating cells have rapid evolution and shorter predictability (tau = 45 min).
    - Intensifying / Decaying cells have intermediate predictability (tau = 60 min).
    - Mature cells and organized squall lines have longer dynamical coherence (tau = 75 min).
    """
    if lifecycle_state is None:
        return 60.0
    state_str = str(getattr(lifecycle_state, "value", lifecycle_state)).upper()
    if state_str in ("INITIATING", "SPLIT"):
        return 45.0
    elif state_str in ("MATURE", "MERGE"):
        return 75.0
    else:  # INTENSIFYING, DECAYING, etc.
        return 60.0


def generate_continuous_probability_field(
    cells: list[Cell],
    p_cell: dict[str, float],
    grid: GridSpec,
    background_p: float = 0.05,
    base_unet_field: np.ndarray | None = None,
    ci_candidates: list[CICandidate] | None = None,
    lead_minutes: int = 30,
    smooth_sigma: float = 1.0,
) -> np.ndarray:
    """Generate a smooth, continuous 2D probability field P(x, y) on the canonical grid.

    Eliminates rectangular step-function box artifacts by utilizing anisotropic
    spatial Gaussian kernels oriented along the storm motion vector (sigma_parallel = 2.5 * sigma_perp)
    to represent downwind anvil blow-off accurately, or directly consuming
    the deep U-Net continuous probability field.
    """
    h, w = grid.nlat, grid.nlon

    if base_unet_field is not None and base_unet_field.shape == (h, w):
        # Track B: Deep U-Net continuous probability field
        field = np.clip(np.nan_to_num(base_unet_field.astype(np.float32), nan=background_p), 0.0, 1.0)
    else:
        # Track A / Tabular: Anisotropic continuous Gaussian kernel blending
        field = np.full((h, w), float(np.clip(background_p, 0.0, 1.0)), dtype=np.float32)

        # Coordinate grids
        y_coords = np.arange(h, dtype=np.float32)
        x_coords = np.arange(w, dtype=np.float32)
        grid_x, grid_y = np.meshgrid(x_coords, y_coords)

        by_id = {c.id: c for c in cells}
        for cid, prob in p_cell.items():
            cell = by_id.get(cid)
            if cell is None or prob <= background_p:
                continue

            # Centroid in grid pixel coordinates
            cy_px = (cell.centroid_lat - grid.lat0) / grid.dlat
            cx_px = (cell.centroid_lon - grid.lon0) / grid.dlon

            if not (-10 <= cy_px <= h + 10 and -10 <= cx_px <= w + 10):
                continue

            # Base perpendicular spatial scale from cell area or bounding box
            lat_span = abs(cell.bbox[3] - cell.bbox[1])
            lon_span = abs(cell.bbox[2] - cell.bbox[0])
            r_from_area = math.sqrt(max(4.0, float(cell.area_px)) / math.pi)
            sigma_perp = max(1.5, min(r_from_area, float(lat_span / (2.0 * abs(grid.dlat)))))
            sigma_parallel = 2.5 * sigma_perp

            # Storm motion direction in grid pixel coordinates
            if cell.velocity_kmh > 1.0:
                head_rad = math.radians(cell.heading_deg)
                u_dir = math.sin(head_rad)
                v_dir = math.cos(head_rad)
                mx = u_dir / (abs(grid.dlon) * 111.12 * max(0.1, math.cos(math.radians(cell.centroid_lat))))
                my = v_dir / (abs(grid.dlat) * 111.12)
                if grid.dlat < 0:
                    my = -my
            elif abs(cell.motion_dlon) > 1e-4 or abs(cell.motion_dlat) > 1e-4:
                mx = cell.motion_dlon / grid.dlon
                my = cell.motion_dlat / grid.dlat
            else:
                mx = 0.0
                my = 0.0

            s_mag = math.hypot(mx, my)
            dx = grid_x - cx_px
            dy = grid_y - cy_px

            if s_mag > 1e-3:
                # Rotated coordinates: parallel along motion, perpendicular across
                ux = mx / s_mag
                uy = my / s_mag
                d_par = dx * ux + dy * uy
                d_perp = -dx * uy + dy * ux

                # Downwind anvil blow-off asymmetry (sigma_parallel = 2.5 * sigma_perp downwind)
                sig_par = np.where(d_par > 0, sigma_parallel, sigma_perp)
                dist_sq = (d_par / sig_par) ** 2 + (d_perp / sigma_perp) ** 2
            else:
                dist_sq = (dx / sigma_perp) ** 2 + (dy / sigma_perp) ** 2

            kernel = np.exp(-0.5 * dist_sq)
            kernel_prob = prob * kernel

            # Smooth probabilistic union: P_total = 1 - (1 - P_field) * (1 - P_kernel)
            field = 1.0 - (1.0 - field) * (1.0 - np.clip(kernel_prob, 0.0, 0.999))

    # Convective Initiation plume injection for pre-convective 30-60 min forecasts
    if ci_candidates and lead_minutes >= 30:
        y_coords = np.arange(h, dtype=np.float32)
        x_coords = np.arange(w, dtype=np.float32)
        grid_x, grid_y = np.meshgrid(x_coords, y_coords)

        for ci in ci_candidates:
            # Check lead time compatibility (candidate electrifies within +-15 min of lead)
            lead_diff = abs(ci.estimated_lead_min - lead_minutes)
            if lead_diff > 20:
                continue

            cy_px = (ci.centroid_lat - grid.lat0) / grid.dlat
            cx_px = (ci.centroid_lon - grid.lon0) / grid.dlon

            if not (0 <= cy_px < h and 0 <= cx_px < w):
                continue

            # Scale plume radius with candidate area (typically 1.5 - 3 grid cells)
            r_px = max(1.5, math.sqrt(max(10.0, ci.area_km2) / (math.pi * 100.0)))
            dist_sq = ((grid_y - cy_px) / r_px) ** 2 + ((grid_x - cx_px) / r_px) ** 2
            plume = ci.p_initiation * np.exp(-0.5 * dist_sq)

            # Lead-time timing attenuation
            time_factor = math.exp(-0.5 * (lead_diff / 15.0) ** 2)
            plume *= time_factor

            # Blend into field
            field = np.maximum(field, plume.astype(np.float32))

    # Apply spatial Gaussian smoothing (sigma=1.0) to eliminate any sub-grid discretization artifacts
    if smooth_sigma > 0:
        field = ndi.gaussian_filter(field, sigma=smooth_sigma, mode="nearest")

    return np.clip(field, 0.0, 1.0).astype(np.float32)


def extrapolate_lagrangian_advection(
    p_grid_base: np.ndarray,
    u_px: float,
    v_px: float,
    lead_minutes: int,
    base_lead: int = 60,
    background_p: float = 0.05,
    tau_minutes: float = 45.0,
    lifecycle_state: StormLifecycleState | str | None = None,
) -> np.ndarray:
    """Extrapolate continuous probability field to outer horizons (up to 90-120 min).

    Applies:
    1. Lagrangian displacement along storm motion vector [u, v].
    2. Exponential predictability decay exp(-dt / tau) reflecting convective storm lifecycle
       (tau = 45 min for initiating cells, 75 min for mature squall lines).
    3. Increasing spatial diffusion modeling positional uncertainty growth with lead time.
    """
    if lead_minutes <= base_lead:
        return p_grid_base

    dt = float(lead_minutes - base_lead)
    effective_tau = get_lifecycle_tau_decay(lifecycle_state) if lifecycle_state is not None else tau_minutes

    # Pixel shift (v is y/lat direction, u is x/lon direction)
    # Scale: motion vector is given per 15-min interval
    steps = dt / 15.0
    shift_y = float(v_px * steps)
    shift_x = float(u_px * steps)

    # Lagrangian advection shift
    advected = ndi.shift(p_grid_base, shift=(shift_y, shift_x), order=1, mode="nearest", prefilter=False)

    # Exponential predictability dissipation
    decay = math.exp(-dt / max(1.0, effective_tau))
    decayed = background_p + (advected - background_p) * decay

    # Progressive spatial diffusion: uncertainty expands with sqrt(dt)
    diff_sigma = 1.0 + 0.5 * math.sqrt(dt / 15.0)
    smoothed = ndi.gaussian_filter(decayed, sigma=diff_sigma, mode="nearest")

    return np.clip(smoothed, 0.0, 1.0).astype(np.float32)


def compute_spatial_uncertainty_field(
    p_grid: np.ndarray,
    lead_minutes: int,
    grid: GridSpec,
    missing_modalities: list[str] | None = None,
    radar_available: bool = True,
) -> np.ndarray:
    """Compute spatial uncertainty field Sigma(x, y) in [0.0, 1.0].

    Components:
    1. Aleatoric uncertainty: 4 * P * (1 - P), highest at decision boundary P=0.5.
    2. Epistemic lead-time uncertainty: grows with forecast horizon.
    3. Sensor coverage uncertainty: radar beam horizon distance decay and missing sensors.
    """
    h, w = p_grid.shape
    p = np.clip(p_grid, 0.0, 1.0)

    # 1. Aleatoric uncertainty: binary entropy / decision ambiguity
    u_aleatoric = 4.0 * p * (1.0 - p)

    # 2. Epistemic lead-time uncertainty (0.0 at 0 min, 0.4 at 120 min)
    u_lead = float(min(0.40, 0.05 * (lead_minutes / 15.0)))

    # 3. Sensor coverage & edge uncertainty
    y_coords = np.arange(h)
    x_coords = np.arange(w)
    grid_x, grid_y = np.meshgrid(x_coords, y_coords)

    # Distance from grid border (normalized to [0, 1])
    dist_border_y = np.minimum(grid_y, h - 1 - grid_y) / max(1, h // 10)
    dist_border_x = np.minimum(grid_x, w - 1 - grid_x) / max(1, w // 10)
    border_factor = np.clip(np.minimum(dist_border_y, dist_border_x), 0.0, 1.0)
    edge_penalty = 0.20 * (1.0 - border_factor)

    # Missing modality penalties
    sensor_penalty = 0.0
    if not radar_available:
        sensor_penalty += 0.20
    if missing_modalities:
        if "satellite" in missing_modalities:
            sensor_penalty += 0.25
        if "model" in missing_modalities:
            sensor_penalty += 0.15

    # Combined uncertainty field
    sigma = (
        0.45 * u_aleatoric
        + 0.30 * u_lead
        + 0.15 * edge_penalty
        + 0.10 * min(1.0, sensor_penalty)
    )

    # Gaussian smoothing to create seamless uncertainty field
    sigma = ndi.gaussian_filter(sigma, sigma=1.5, mode="nearest")
    return np.clip(sigma, 0.05, 1.0).astype(np.float32)


@dataclass
class ThreeTierUncertainty:
    """Container for three-tier uncertainty decomposition (TASK-V2-6.1)."""
    p_hazard: np.ndarray             # Tier 1: Calibrated hazard probability P in [0.0, 1.0]
    sigma_aleatoric: np.ndarray      # Tier 2: Aleatoric spread sqrt(P*(1-P)*(1 + dt/60))
    sensor_confidence: float         # Tier 3: Epistemic sensor health index [0.05, 0.90]
    composite_sigma: np.ndarray      # Smoothed composite uncertainty field [0.05, 1.0]


def compute_three_tier_uncertainty(
    p_grid: np.ndarray,
    lead_minutes: int,
    grid: GridSpec,
    missing_modalities: list[str] | None = None,
    radar_available: bool = True,
    qc_suspect_count: int = 0,
) -> ThreeTierUncertainty:
    """Three-Tier Uncertainty Quantification (TASK-V2-6.1).

    Explicitly decomposes total forecast uncertainty into:
    1. Hazard Probability P in [0.0, 1.0]: Physical likelihood of convection/lightning.
    2. Aleatoric Spatial Spread: Predictive variance sigma^2_aleatoric = P*(1 - P)*(1 + dt / 60)
       capturing intrinsic chaotic atmospheric unpredictability, maximized at decision boundary P=0.5.
    3. Epistemic Sensor Confidence: Bounded [0.05, 0.90] reflecting sensor degradation,
       missing feeds, and QC status.
    """
    p = np.clip(np.nan_to_num(p_grid.astype(np.float32), nan=0.05), 0.0, 1.0)

    # Tier 2: Aleatoric spatial spread
    dt = float(lead_minutes)
    aleatoric_var = p * (1.0 - p) * (1.0 + dt / 60.0)
    sigma_aleatoric = np.sqrt(aleatoric_var).astype(np.float32)

    # Tier 3: Epistemic sensor confidence
    missing = set(m.lower() for m in (missing_modalities or []))
    n_total = 5
    n_missing = len(missing)
    if not radar_available and "radar" not in missing:
        n_missing += 1
    n_healthy = max(0, n_total - n_missing)
    base_conf = 0.35 + 0.12 * max(0, n_healthy - 1)
    sensor_conf = float(np.clip(base_conf - 0.05 * qc_suspect_count, 0.05, 0.90))

    # Composite spatial uncertainty field for visualization & downstream consumers
    composite = compute_spatial_uncertainty_field(
        p_grid=p,
        lead_minutes=lead_minutes,
        grid=grid,
        missing_modalities=missing_modalities,
        radar_available=radar_available,
    )

    return ThreeTierUncertainty(
        p_hazard=p,
        sigma_aleatoric=sigma_aleatoric,
        sensor_confidence=sensor_conf,
        composite_sigma=composite,
    )


def render_uncertainty_png(sigma_grid: np.ndarray) -> bytes:
    """Render spatial uncertainty field as an amber/cyan semi-transparent overlay."""
    sig = np.clip(np.nan_to_num(sigma_grid.astype(float), nan=0.0), 0.0, 1.0)
    h, w = sig.shape
    img = np.zeros((h, w, 4), dtype=np.uint8)

    # Low uncertainty (< 0.25): transparent to subtle teal
    # Medium uncertainty (0.25 - 0.60): cyan / blue
    # High uncertainty (> 0.60): warm amber / magenta
    r = (np.clip((sig - 0.2) / 0.8, 0, 1) * 220).astype(np.uint8)
    g = (np.clip((1.0 - np.abs(sig - 0.5) * 2), 0, 1) * 180).astype(np.uint8)
    b = (np.clip((0.8 - sig) / 0.8, 0, 1) * 240).astype(np.uint8)
    a = (np.clip((sig - 0.1) / 0.9, 0, 1) * 160).astype(np.uint8)

    img[:, :, 0] = r
    img[:, :, 1] = g
    img[:, :, 2] = b
    img[:, :, 3] = a

    buf = io.BytesIO()
    Image.fromarray(img, "RGBA").save(buf, format="PNG")
    return buf.getvalue()
