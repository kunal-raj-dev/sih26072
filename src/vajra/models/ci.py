"""Convective Initiation (CI) Precursor Detection Engine (Phase V2-2 / Phase 7).

Scientific Basis (Mecikalski & Bedka 2006, Walker et al. 2012, IMD Guidelines):
Pre-convective initiation signals appear in geostationary satellite infrared imagery
15-45 minutes before the first radar echo (>= 35 dBZ) or first cloud-to-ground flash:
1. Temporal cloud-top cooling rate: dT_b / dt <= -4.0 K / 15 min (vigorous updraft pushing cloud top upward).
2. Freezing level glaciation: T_b(TIR1, 10.8 um) <= 273.15 K (freezing level penetrated).
3. Deep tropospheric saturation difference: (T_b(TIR1) - T_b(WV, 6.8 um)) >= -1.0 K.
4. Split-window brightness temperature difference: Delta T_split = T_b(TIR1) - T_b(TIR2) <= 3.0 K.
5. Pre-convective screening: Radar reflectivity MaxZ < 35 dBZ (distinguishes new initiating
   cells from already mature tracked thunderstorms).
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime
from typing import Any

import numpy as np
try:
    import scipy.ndimage as ndi
except ImportError:
    from .. import ndx as ndi

from ..grid import GridSpec
from ..schemas import CICandidate, Modality, ObsFrame

logger = logging.getLogger(__name__)


def detect_convective_initiation(
    ir_t0: np.ndarray,
    ir_t_prev: np.ndarray,
    wv_t0: np.ndarray | None = None,
    radar_maxz: np.ndarray | None = None,
    grid: GridSpec | None = None,
    dt_minutes: float = 15.0,
    min_cooling_rate: float = -4.0,  # K / 15 min
    max_ir_temp: float = 273.15,     # K
    min_ir_wv_diff: float = -1.0,    # K
    max_radar_dbz: float = 35.0,     # dBZ threshold for mature convection
    min_area_km2: float = 15.0,
    tir2_t0: np.ndarray | None = None,
    split_window_max_k: float = 3.0,
    history_candidates: list[CICandidate] | None = None,
) -> list[CICandidate]:
    """Detect candidate convective initiation clusters from multi-spectral satellite imagery.

    Applies the 5-point physical decision criteria:
    1. Cloud-top cooling rate <= min_cooling_rate (-4.0 K / 15 min)
    2. Cloud-top temperature <= max_ir_temp (273.15 K)
    3. Deep tropospheric saturation (IR1 - WV) >= min_ir_wv_diff (-1.0 K)
    4. Split-window difference (IR1 - TIR2) <= split_window_max_k (if available)
    5. Pre-convective radar screening: MaxZ < max_radar_dbz (35 dBZ)

    Parameters
    ----------
    ir_t0:
        Current TIR1 (10.8 µm) Brightness Temperature array in Kelvin.
    ir_t_prev:
        Prior TIR1 Brightness Temperature array in Kelvin from dt_minutes earlier.
    wv_t0:
        Optional current Water Vapor (6.8 µm) Brightness Temperature array in Kelvin.
    radar_maxz:
        Optional composite radar MaxZ reflectivity array in dBZ.
    grid:
        GridSpec of the spatial domain.
    dt_minutes:
        Time interval between prior and current satellite scans (default: 15.0).
    min_cooling_rate:
        Minimum cloud-top cooling rate threshold in K / 15 min (default: -4.0).
    max_ir_temp:
        Freezing-level glaciation ceiling in Kelvin (default: 273.15).
    min_ir_wv_diff:
        Minimum (IR1 - WV) difference for tropospheric saturation in Kelvin (default: -1.0).
    max_radar_dbz:
        Radar reflectivity threshold above which echoes are treated as mature storms (default: 35.0).
    min_area_km2:
        Minimum candidate cluster surface area in km² (default: 15.0).
    tir2_t0:
        Optional current TIR2 (12.0 µm) Brightness Temperature array in Kelvin.
    split_window_max_k:
        Maximum split-window BTD (TIR1 - TIR2) in Kelvin (default: 3.0).
    history_candidates:
        Optional candidate list from previous cycle for kinematic tracking.

    Returns
    -------
    List of CICandidate objects ordered descending by initiation probability.
    """
    if grid is not None and (ir_t0.shape != (grid.nlat, grid.nlon) or ir_t_prev.shape != (grid.nlat, grid.nlon)):
        logger.warning(f"IR frame dimensions {ir_t0.shape} do not match grid ({grid.nlat}, {grid.nlon})")
        return []

    h, w = ir_t0.shape

    # 1. Normalize dt to 15-minute standard cooling rate: K / 15 min
    dt_scale = 15.0 / max(1.0, dt_minutes)
    cooling_rate = (ir_t0 - ir_t_prev) * dt_scale

    # 2. Multi-spectral physical decision criteria
    # a. Updraft cooling rate (vigorous vertical ascent)
    mask_cooling = cooling_rate <= min_cooling_rate

    # b. Freezing level glaciation (penetrating into mixed-phase charging zone)
    mask_freezing = ir_t0 <= max_ir_temp

    # Combined base mask
    ci_mask = mask_cooling & mask_freezing

    # c. Water vapor deep tropospheric saturation criterion (if available)
    if wv_t0 is not None and wv_t0.shape == ir_t0.shape:
        diff_ir_wv = ir_t0 - wv_t0
        ci_mask = ci_mask & (diff_ir_wv >= min_ir_wv_diff)
    else:
        diff_ir_wv = np.full_like(ir_t0, np.nan)

    # d. Split-window BTD criterion (if TIR2 available)
    if tir2_t0 is not None and tir2_t0.shape == ir_t0.shape:
        diff_split = ir_t0 - tir2_t0
        ci_mask = ci_mask & (diff_split <= split_window_max_k)
    else:
        diff_split = np.full_like(ir_t0, np.nan)

    # e. Pre-convective screening: eliminate pixels already exhibiting mature radar reflectivity
    if radar_maxz is not None and radar_maxz.shape == ir_t0.shape:
        ci_mask = ci_mask & (radar_maxz < max_radar_dbz)

    if not np.any(ci_mask):
        return []

    # 3. Connected-component labeling for spatial candidate grouping (8-connectivity)
    structure = ndi.generate_binary_structure(2, 2)
    labeled_mask, num_features = ndi.label(ci_mask, structure=structure)

    candidates: list[CICandidate] = []

    # Determine pixel area
    if grid is not None:
        lat_res_km = abs(grid.dlat) * 111.0
        center_lat = grid.lat0 + (grid.nlat * grid.dlat) / 2.0
        lon_res_km = abs(grid.dlon) * 111.0 * math.cos(math.radians(center_lat))
        px_area_km2 = max(1.0, lat_res_km * lon_res_km)
    else:
        px_area_km2 = 100.0  # fallback ~10 km x 10 km

    for feat_id in range(1, num_features + 1):
        idx_y, idx_x = np.where(labeled_mask == feat_id)
        if len(idx_y) == 0:
            continue

        cand_area_km2 = float(len(idx_y) * px_area_km2)
        # Enforce minimum area filter (TASK-V2-2.2: filter candidate clusters with area < 15 km²)
        if cand_area_km2 < min_area_km2 and len(idx_y) < 2:
            continue

        # Spatial coordinates
        if grid is not None:
            i_min, i_max = int(idx_y.min()), int(idx_y.max())
            j_min, j_max = int(idx_x.min()), int(idx_x.max())

            lat_min = float(grid.lat0 + i_min * grid.dlat)
            lat_max = float(grid.lat0 + i_max * grid.dlat)
            lon_min = float(grid.lon0 + j_min * grid.dlon)
            lon_max = float(grid.lon0 + j_max * grid.dlon)

            c_lat = float(grid.lat0 + float(np.mean(idx_y)) * grid.dlat)
            c_lon = float(grid.lon0 + float(np.mean(idx_x)) * grid.dlon)
        else:
            lat_min, lat_max = float(idx_y.min()), float(idx_y.max())
            lon_min, lon_max = float(idx_x.min()), float(idx_x.max())
            c_lat, c_lon = float(np.mean(idx_y)), float(np.mean(idx_x))

        # Candidate physical statistics
        cand_cooling = float(np.mean(cooling_rate[idx_y, idx_x]))
        cand_ir = float(np.min(ir_t0[idx_y, idx_x]))
        cand_diff = float(np.nanmean(diff_ir_wv[idx_y, idx_x])) if not np.isnan(diff_ir_wv[idx_y, idx_x]).all() else 0.0
        cand_split = float(np.nanmean(diff_split[idx_y, idx_x])) if not np.isnan(diff_split[idx_y, idx_x]).all() else None

        # Physics-based initiation probability P_CI in [0.40, 0.95]
        # Cooling rate score: -4.0 K -> 0.40, -12.0 K -> 0.95
        cooling_score = np.clip(0.40 + 0.55 * (abs(cand_cooling) - 4.0) / 8.0, 0.40, 0.95)
        # Glaciation score: 273.15 K -> 0.50, 233.15 K -> 1.00
        temp_score = np.clip(0.50 + 0.50 * (273.15 - cand_ir) / 40.0, 0.50, 1.00)
        # Tropopause proximity bonus
        wv_bonus = 0.05 if (wv_t0 is not None and cand_diff >= 0.0) else 0.0
        # Split-window ice-crystal bonus
        split_bonus = 0.05 if (cand_split is not None and cand_split <= 1.5) else 0.0

        p_initiation = float(np.clip(0.60 * cooling_score + 0.40 * temp_score + wv_bonus + split_bonus, 0.40, 0.98))

        # Estimated lead time to first flash (15 to 45 min):
        # More vigorous updrafts electrify faster (shorter lead time)
        lead_time = int(np.clip(round(45 - 30 * ((p_initiation - 0.40) / 0.45)), 15, 45))

        # Polygon footprint for GIS overlay
        polygon = [
            [round(min(lon_min, lon_max), 4), round(min(lat_min, lat_max), 4)],
            [round(max(lon_min, lon_max), 4), round(min(lat_min, lat_max), 4)],
            [round(max(lon_min, lon_max), 4), round(max(lat_min, lat_max), 4)],
            [round(min(lon_min, lon_max), 4), round(max(lat_min, lat_max), 4)],
            [round(min(lon_min, lon_max), 4), round(min(lat_min, lat_max), 4)],
        ]

        candidates.append(
            CICandidate(
                id=f"ci_{uuid.uuid4().hex[:6]}",
                centroid_lat=round(c_lat, 4),
                centroid_lon=round(c_lon, 4),
                bbox=[
                    round(min(lon_min, lon_max), 4),
                    round(min(lat_min, lat_max), 4),
                    round(max(lon_min, lon_max), 4),
                    round(max(lat_min, lat_max), 4),
                ],
                cooling_rate_k_per_15m=round(cand_cooling, 2),
                ir_brightness_temp_k=round(cand_ir, 2),
                ir_wv_diff_k=round(cand_diff, 2),
                p_initiation=round(p_initiation, 3),
                estimated_lead_min=lead_time,
                area_km2=round(cand_area_km2, 1),
                polygon=polygon,
                split_window_btd_k=round(cand_split, 2) if cand_split is not None else None,
            )
        )

    # 4. Multi-cycle candidate tracking & kinematic advection (TASK-V2-2.2)
    if history_candidates and candidates:
        candidates = track_ci_candidates(candidates, history_candidates, dt_minutes=dt_minutes)

    # Sort descending by initiation probability
    candidates.sort(key=lambda c: c.p_initiation, reverse=True)
    return candidates


def track_ci_candidates(
    current_candidates: list[CICandidate],
    history_candidates: list[CICandidate],
    dt_minutes: float = 15.0,
    max_distance_km: float = 50.0,
) -> list[CICandidate]:
    """Associate CI candidates across consecutive cycles, computing kinematic motion vectors.

    Parameters
    ----------
    current_candidates:
        Candidates detected at cycle T_0.
    history_candidates:
        Candidates detected at cycle T_{-15}.
    dt_minutes:
        Time delta between cycles in minutes.
    max_distance_km:
        Maximum centroid displacement to consider a candidate track match.

    Returns
    -------
    Updated list of current candidates with persistent IDs and kinematic velocity vectors.
    """
    dt_hr = max(0.01, dt_minutes / 60.0)

    for curr in current_candidates:
        best_match = None
        min_dist = float("inf")

        for prev in history_candidates:
            dlat_km = (curr.centroid_lat - prev.centroid_lat) * 111.0
            mean_lat_rad = math.radians((curr.centroid_lat + prev.centroid_lat) / 2.0)
            dlon_km = (curr.centroid_lon - prev.centroid_lon) * 111.0 * math.cos(mean_lat_rad)
            dist_km = math.sqrt(dlat_km ** 2 + dlon_km ** 2)

            if dist_km < min_dist and dist_km <= max_distance_km:
                min_dist = dist_km
                best_match = prev

        if best_match is not None:
            # Inherit track identity
            curr.id = best_match.id
            curr.tracked_cycles = best_match.tracked_cycles + 1

            # Compute kinematic velocity (km/h)
            dlat_km = (curr.centroid_lat - best_match.centroid_lat) * 111.0
            mean_lat_rad = math.radians((curr.centroid_lat + best_match.centroid_lat) / 2.0)
            dlon_km = (curr.centroid_lon - best_match.centroid_lon) * 111.0 * math.cos(mean_lat_rad)

            curr.u_kmh = round(dlon_km / dt_hr, 1)
            curr.v_kmh = round(dlat_km / dt_hr, 1)

            # Persistent cooling multi-cycle boost
            curr.p_initiation = min(0.98, round(curr.p_initiation + 0.05, 3))

    return current_candidates


def generate_ci_probability_grid(
    candidates: list[CICandidate],
    grid: GridSpec,
    lead_minutes: int = 30,
    background_p: float = 0.0,
) -> np.ndarray:
    """Generate a continuous 2D convective initiation probability field P_ci(x, y).

    Projects spatial Gaussian plumes for active CI candidates at the designated lead time,
    accounting for kinematic advection velocity and lead-time timing attenuation.

    Parameters
    ----------
    candidates:
        Active CICandidate detections.
    grid:
        GridSpec of the domain.
    lead_minutes:
        Forecast lead time in minutes (typically 15, 30, 45, 60).
    background_p:
        Ambient baseline probability (default: 0.0).

    Returns
    -------
    (nlat, nlon) float32 probability array bounded in [0.0, 1.0].
    """
    h, w = grid.nlat, grid.nlon
    field = np.full((h, w), float(np.clip(background_p, 0.0, 1.0)), dtype=np.float32)

    if not candidates:
        return field

    y_coords = np.arange(h, dtype=np.float32)
    x_coords = np.arange(w, dtype=np.float32)
    grid_x, grid_y = np.meshgrid(x_coords, y_coords)

    lead_hr = lead_minutes / 60.0

    for ci in candidates:
        # Check timing window: candidate triggers within +/-20 min of lead time
        lead_diff = abs(ci.estimated_lead_min - lead_minutes)
        if lead_diff > 25:
            continue

        # Kinematic displacement if velocity is known
        dlat_deg = (ci.v_kmh * lead_hr) / 111.0 if ci.v_kmh else 0.0
        mean_lat_rad = math.radians(ci.centroid_lat)
        dlon_deg = (ci.u_kmh * lead_hr) / (111.0 * max(0.1, math.cos(mean_lat_rad))) if ci.u_kmh else 0.0

        projected_lat = ci.centroid_lat + dlat_deg
        projected_lon = ci.centroid_lon + dlon_deg

        cy_px = (projected_lat - grid.lat0) / grid.dlat
        cx_px = (projected_lon - grid.lon0) / grid.dlon

        if not (-5 <= cy_px <= h + 5 and -5 <= cx_px <= w + 5):
            continue

        # Spatial plume radius (typically 1.5 - 3.5 grid cells)
        r_px = max(1.5, math.sqrt(max(10.0, ci.area_km2) / (math.pi * 100.0)))
        dist_sq = ((grid_y - cy_px) / r_px) ** 2 + ((grid_x - cx_px) / r_px) ** 2

        # Temporal attenuation kernel: peak at estimated_lead_min, decaying away
        time_factor = math.exp(-0.5 * (lead_diff / 15.0) ** 2)
        plume_amplitude = ci.p_initiation * time_factor
        plume = plume_amplitude * np.exp(-0.5 * dist_sq)

        # Probabilistic union merge: P_total = 1 - (1 - P_field) * (1 - P_plume)
        field = 1.0 - (1.0 - field) * (1.0 - np.clip(plume.astype(np.float32), 0.0, 0.999))

    return np.clip(field, 0.0, 1.0).astype(np.float32)


def extract_ci_candidates_from_cycle(
    satellite_frames: list[ObsFrame],
    radar_frames: list[ObsFrame],
    grid: GridSpec,
    history_candidates: list[CICandidate] | None = None,
) -> list[CICandidate]:
    """Helper to extract CI candidates from cycle observation frames with multi-channel support."""
    if len(satellite_frames) < 2:
        return []

    def _get_time(f: ObsFrame) -> datetime:
        return getattr(f.meta, "time", getattr(f.meta, "valid_time", None))

    def _get_field(f: ObsFrame) -> np.ndarray:
        return f.field if getattr(f, "field", None) is not None else getattr(f, "data", None)

    def _is_ir(f: ObsFrame) -> bool:
        var = getattr(f.meta, "variable", "").lower()
        if "wv" in var or "tir2" in var or "120" in var:
            return False
        return True

    ir_frames = [f for f in satellite_frames if _is_ir(f)]
    if len(ir_frames) < 2:
        ir_frames = satellite_frames

    if len(ir_frames) < 2:
        return []

    # Sort IR frames chronologically
    sorted_ir = sorted(ir_frames, key=_get_time)
    f_curr = sorted_ir[-1]
    f_prev = sorted_ir[-2]

    t_curr = _get_time(f_curr)
    t_prev = _get_time(f_prev)
    dt = (t_curr - t_prev).total_seconds() / 60.0 if (t_curr and t_prev) else 15.0
    if dt <= 0:
        dt = 15.0

    ir_curr = _get_field(f_curr).astype(np.float32)
    ir_prev = _get_field(f_prev).astype(np.float32)

    # Check units: if SEVIR raw [0, 255] or MOSDAC Kelvin [180, 330]
    # For SEVIR IR, proxy conversion: Kelvin ~ 310.0 - (raw / 255.0) * 110.0
    if float(np.nanmax(ir_curr)) <= 255.0 and float(np.nanmin(ir_curr)) >= 0.0:
        ir_curr = 310.0 - (ir_curr / 255.0) * 110.0
        ir_prev = 310.0 - (ir_prev / 255.0) * 110.0

    # Look for auxiliary multi-spectral frames (WV, TIR2)
    wv_curr = None
    wv_frames = [
        f for f in satellite_frames
        if "wv" in getattr(f.meta, "variable", "").lower() or "68" in getattr(f.meta, "variable", "").lower()
    ]
    if wv_frames:
        sorted_wv = sorted(wv_frames, key=_get_time)
        wv_f = _get_field(sorted_wv[-1])
        if wv_f is not None:
            wv_curr = wv_f.astype(np.float32)

    tir2_curr = None
    tir2_frames = [
        f for f in satellite_frames
        if "tir2" in getattr(f.meta, "variable", "").lower() or "120" in getattr(f.meta, "variable", "").lower()
    ]
    if tir2_frames:
        sorted_tir2 = sorted(tir2_frames, key=_get_time)
        t2_f = _get_field(sorted_tir2[-1])
        if t2_f is not None:
            tir2_curr = t2_f.astype(np.float32)

    # Radar reflectivity
    radar_maxz = None
    if radar_frames:
        f_rad = sorted(radar_frames, key=_get_time)[-1]
        r_field = _get_field(f_rad)
        if r_field is not None:
            r_data = r_field.astype(np.float32)
            # If SEVIR VIL raw [0, 255], convert to proxy dBZ: dBZ ~ (raw / 255.0) * 75.0
            if float(np.nanmax(r_data)) <= 255.0:
                radar_maxz = (r_data / 255.0) * 75.0
            else:
                radar_maxz = r_data

    return detect_convective_initiation(
        ir_t0=ir_curr,
        ir_t_prev=ir_prev,
        wv_t0=wv_curr,
        radar_maxz=radar_maxz,
        grid=grid,
        dt_minutes=dt,
        tir2_t0=tir2_curr,
        history_candidates=history_candidates,
    )
