"""Convective Initiation (CI) Precursor Detection Engine (Phase 7).

Scientific Basis (Mecikalski & Bedka 2006, Walker et al. 2012, IMD Guidelines):
Pre-convective initiation signals appear in geostationary satellite infrared imagery
15-45 minutes before the first radar echo (>= 35 dBZ) or first cloud-to-ground flash:
1. Cloud-top cooling rate: dT_b / dt <= -4.0 K / 15 min (vigorous updraft pushing cloud top upward).
2. Cloud-top glaciation: T_b(IR1, 10.8 um) <= 273.15 K (freezing level penetrated).
3. Deep tropospheric saturation: (T_b(IR1) - T_b(WV, 6.7 um)) >= -1.0 K.
4. Pre-convective screening: Radar reflectivity < 35 dBZ (distinguishes new initiating
   cells from already mature tracked thunderstorms).
"""

from __future__ import annotations

import logging
import math
import uuid
from typing import Any

import numpy as np
import scipy.ndimage as ndi

from ..grid import GridSpec
from ..schemas import CICandidate, Modality, ObsFrame

logger = logging.getLogger(__name__)


def detect_convective_initiation(
    ir_t0: np.ndarray,
    ir_t_prev: np.ndarray,
    wv_t0: np.ndarray | None,
    radar_maxz: np.ndarray | None,
    grid: GridSpec,
    dt_minutes: float = 15.0,
    min_cooling_rate: float = -4.0,  # K / 15 min
    max_ir_temp: float = 273.15,     # K
    min_ir_wv_diff: float = -1.0,    # K
    max_radar_dbz: float = 35.0,     # dBZ threshold for mature convection
    min_area_km2: float = 15.0,
) -> list[CICandidate]:
    """Detect candidate convective initiation clusters from multi-spectral satellite imagery.

    Returns:
        List of CICandidate objects with centroid, bounding box, initiation probability,
        and estimated lead time to first lightning flash (15-45 minutes).
    """
    if ir_t0.shape != (grid.nlat, grid.nlon) or ir_t_prev.shape != (grid.nlat, grid.nlon):
        logger.warning(f"IR frame dimensions {ir_t0.shape} do not match grid ({grid.nlat}, {grid.nlon})")
        return []

    # 1. Normalize dt to 15-minute standard cooling rate: K / 15 min
    dt_scale = 15.0 / max(1.0, dt_minutes)
    cooling_rate = (ir_t0 - ir_t_prev) * dt_scale

    # 2. Apply multi-spectral scientific decision criteria
    # a. Updraft cooling rate
    mask_cooling = cooling_rate <= min_cooling_rate

    # b. Freezing level glaciation
    mask_freezing = ir_t0 <= max_ir_temp

    # c. Combined base mask
    ci_mask = mask_cooling & mask_freezing

    # d. Water vapor split-window saturation criterion (if available)
    if wv_t0 is not None and wv_t0.shape == ir_t0.shape:
        diff_ir_wv = ir_t0 - wv_t0
        ci_mask = ci_mask & (diff_ir_wv >= min_ir_wv_diff)
    else:
        diff_ir_wv = np.full_like(ir_t0, np.nan)

    # e. Pre-convective screening: eliminate pixels already exhibiting mature radar reflectivity
    if radar_maxz is not None and radar_maxz.shape == ir_t0.shape:
        ci_mask = ci_mask & (radar_maxz < max_radar_dbz)

    if not np.any(ci_mask):
        return []

    # 3. Connected-component labeling for spatial candidate grouping (8-connectivity)
    structure = ndi.generate_binary_structure(2, 2)
    labeled_mask, num_features = ndi.label(ci_mask, structure=structure)

    candidates: list[CICandidate] = []
    lat_res_km = abs(grid.dlat) * 111.0
    lon_res_km = abs(grid.dlon) * 111.0 * math.cos(math.radians((grid.lat0 + (grid.nlat * grid.dlat) / 2)))
    px_area_km2 = max(1.0, lat_res_km * lon_res_km)

    for feat_id in range(1, num_features + 1):
        idx_y, idx_x = np.where(labeled_mask == feat_id)
        if len(idx_y) == 0:
            continue

        cand_area_km2 = float(len(idx_y) * px_area_km2)
        if cand_area_km2 < min_area_km2 and len(idx_y) < 2:
            continue

        # Coordinate bounds
        i_min, i_max = int(idx_y.min()), int(idx_y.max())
        j_min, j_max = int(idx_x.min()), int(idx_x.max())

        lat_min = float(grid.lat0 + i_min * grid.dlat)
        lat_max = float(grid.lat0 + i_max * grid.dlat)
        lon_min = float(grid.lon0 + j_min * grid.dlon)
        lon_max = float(grid.lon0 + j_max * grid.dlon)

        c_lat = float(grid.lat0 + float(np.mean(idx_y)) * grid.dlat)
        c_lon = float(grid.lon0 + float(np.mean(idx_x)) * grid.dlon)

        # Candidate physical statistics
        cand_cooling = float(np.mean(cooling_rate[idx_y, idx_x]))
        cand_ir = float(np.min(ir_t0[idx_y, idx_x]))
        cand_diff = float(np.nanmean(diff_ir_wv[idx_y, idx_x])) if not np.isnan(diff_ir_wv[idx_y, idx_x]).all() else 0.0

        # Physics-based initiation probability
        # Cooling rate score: -4.0 K -> 0.40, -12.0 K -> 0.95
        cooling_score = np.clip(0.40 + 0.55 * (abs(cand_cooling) - 4.0) / 8.0, 0.40, 0.95)
        # Glaciation score: 273.15 K -> 0.50, 233.15 K -> 1.00
        temp_score = np.clip(0.50 + 0.50 * (273.15 - cand_ir) / 40.0, 0.50, 1.00)
        # Tropopause proximity bonus
        wv_bonus = 0.05 if cand_diff >= 0.0 else 0.0

        p_initiation = float(np.clip(0.60 * cooling_score + 0.40 * temp_score + wv_bonus, 0.15, 0.98))

        # Estimated lead time to first flash (15 to 45 min):
        # More vigorous updrafts electrify faster (shorter lead time)
        lead_time = int(np.clip(round(45 - 30 * ((p_initiation - 0.40) / 0.55)), 15, 45))

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
            )
        )

    # Sort descending by initiation probability
    candidates.sort(key=lambda c: c.p_initiation, reverse=True)
    return candidates


def extract_ci_candidates_from_cycle(
    satellite_frames: list[ObsFrame],
    radar_frames: list[ObsFrame],
    grid: GridSpec,
) -> list[CICandidate]:
    """Helper to extract CI candidates from cycle observation frames."""
    if len(satellite_frames) < 2:
        return []

    def _get_time(f: ObsFrame) -> datetime:
        return getattr(f.meta, "time", getattr(f.meta, "valid_time", None))

    def _get_field(f: ObsFrame) -> np.ndarray:
        return f.field if getattr(f, "field", None) is not None else getattr(f, "data", None)

    # Sort satellite frames chronologically
    sorted_sat = sorted(satellite_frames, key=_get_time)
    f_curr = sorted_sat[-1]
    f_prev = sorted_sat[-2]

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
        wv_t0=None,
        radar_maxz=radar_maxz,
        grid=grid,
        dt_minutes=dt,
    )
