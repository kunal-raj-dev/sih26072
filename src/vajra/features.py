"""Feature engineering for the late-fusion nowcast model.

Features are computed per detected storm cell at issue time t, from the verified
observation window only (no future information leaks into features):

- VIL cell structure: intensity, area, growth over 10 min, age, motion speed;
- lightning: flash counts within a radius of the centroid over the past 10/20/30 min
  (the 'lightning jump' signal appears here as a feature, plus as a baseline);
- satellite: minimum IR value (cold anvil proxy) within the cell footprint and its
  10-min change (cooling rate);
- environment: NWP features are pluggable; when the MODEL modality is UNAVAILABLE
  they are simply absent (NaN) — XGBoost handles missing values natively, which is
  exactly the reduced-modality behaviour required by the fallback design.

Feature names are the contract between training and inference; they live in one
list (FEATURE_NAMES) so drift is impossible to hide.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .cells import CellTracker, flashes_near
from .grid import GridSpec, KM_PER_DEG_LAT
from .schemas import Cell, ObsFrame

FEATURE_NAMES = [
    "vil_max", "vil_mean", "area_px",
    "vil_growth_10", "area_growth_10",
    "track_age", "motion_speed_km_h",
    "flash_cnt_10", "flash_cnt_20", "flash_cnt_30",
    "ir_min", "ir_cooling_10",
    "env_cape", "env_shear",  # NWP features: NaN when MODEL modality unavailable
]

FEATURE_NAMES_NO_ENV = [f for f in FEATURE_NAMES if not f.startswith("env_")]


def _flash_history(lightning_frames: list[ObsFrame]) -> tuple[np.ndarray, np.ndarray]:
    """Concatenate lightning point frames.

    Contract: points are (N,4) = lat, lon, energy, epoch_seconds.
    Returns (points (N,4), epoch seconds (N,)).
    """
    pts, ts = [], []
    for fr in lightning_frames:
        if fr.points is None or len(fr.points) == 0:
            continue
        p = fr.points
        if p.shape[1] >= 4:  # per-point absolute time (SEVIR contract)
            pts.append(p[:, :2])
            ts.append(p[:, 3])
        else:                # fallback: frame-time stamping
            pts.append(p[:, :2])
            ts.append(np.full(len(p), fr.meta.time.timestamp()))
    if not pts:
        return np.zeros((0, 2), dtype=np.float32), np.zeros((0,))
    return np.concatenate(pts), np.concatenate(ts)


def _ir_min_in_bbox(ir_frames: list[ObsFrame], bbox: list[float]) -> float | None:
    if not ir_frames:
        return None
    fr = ir_frames[-1]
    g = fr.meta.grid
    half_lon = g.dlon / 2.0
    half_lat = abs(g.dlat) / 2.0
    j0 = int(np.floor((bbox[0] + half_lon - g.lon0) / g.dlon))
    j1 = int(np.ceil((bbox[2] - half_lon - g.lon0) / g.dlon))
    i0 = int(np.floor((bbox[3] - half_lat - g.lat0) / g.dlat))
    i1 = int(np.ceil((bbox[1] + half_lat - g.lat0) / g.dlat))
    j0, i0 = max(0, j0), max(0, i0)
    j1, i1 = min(g.nlon - 1, j1), min(g.nlat - 1, i1)
    if j1 < j0 or i1 < i0:
        return None
    sub = fr.field[i0:i1 + 1, j0:j1 + 1]
    sub = sub[np.isfinite(sub)]
    return float(sub.min()) if sub.size else None


def motion_speed_km_h(cell: Cell) -> float:
    km_h_lat = cell.motion_dlat * KM_PER_DEG_LAT
    km_h_lon = cell.motion_dlon * KM_PER_DEG_LAT * np.cos(np.radians(cell.centroid_lat))
    return float(np.hypot(km_h_lat, km_h_lon))


def build_features(
    t: datetime,
    cells: list[Cell],
    tracker: CellTracker,
    radar_frames: list[ObsFrame],
    satellite_frames: list[ObsFrame],
    lightning_frames: list[ObsFrame],
    flash_radius_km: float,
    grid: GridSpec,
) -> pd.DataFrame:
    """One row per cell with FEATURE_NAMES columns (env_* = NaN)."""
    pts, pts_t = _flash_history(lightning_frames)
    rows = []
    for cell in cells:
        t10 = t - timedelta(minutes=10)
        # Growth from tracker history (exact, cheap — no re-detection):
        track = tracker.tracks.get(cell.id)
        growth = area_growth = np.nan
        if track and len(track.detections) >= 2:
            hist = track.detections
            target = t - timedelta(minutes=10)
            older = [d for d in hist if d.time <= target]
            if older:
                od = older[-1]
                growth = cell.max_intensity - od.max_intensity
                area_growth = float(cell.area_px - od.area_px)
        fc10 = flashes_near(pts, cell.centroid_lat, cell.centroid_lon, flash_radius_km,
                            t - timedelta(minutes=10), t, pts_t)
        fc20 = flashes_near(pts, cell.centroid_lat, cell.centroid_lon, flash_radius_km,
                            t - timedelta(minutes=20), t, pts_t)
        fc30 = flashes_near(pts, cell.centroid_lat, cell.centroid_lon, flash_radius_km,
                            t - timedelta(minutes=30), t, pts_t)
        ir_now = _ir_min_in_bbox(satellite_frames, cell.bbox)
        ir_prev = _ir_min_in_bbox([f for f in satellite_frames if f.meta.time <= t10], cell.bbox)
        ir_cool = (ir_prev - ir_now) if (ir_now is not None and ir_prev is not None) else np.nan
        rows.append({
            "vil_max": cell.max_intensity,
            "vil_mean": cell.mean_intensity,
            "area_px": cell.area_px,
            "vil_growth_10": growth,
            "area_growth_10": area_growth,
            "track_age": cell.track_age_steps,
            "motion_speed_km_h": motion_speed_km_h(cell),
            "flash_cnt_10": fc10,
            "flash_cnt_20": fc20,
            "flash_cnt_30": fc30,
            "ir_min": ir_now if ir_now is not None else np.nan,
            "ir_cooling_10": ir_cool,
            "env_cape": np.nan,
            "env_shear": np.nan,
            # join keys / metadata (not model features)
            "_cell_id": cell.id,
            "_centroid_lat": cell.centroid_lat,
            "_centroid_lon": cell.centroid_lon,
            "_bbox": ",".join(str(x) for x in cell.bbox),
        })
    return pd.DataFrame(rows)


def build_training_rows(
    samples: list[dict],
) -> pd.DataFrame:
    """Assemble labelled training rows collected by the pipeline's dataset recorder."""
    return pd.DataFrame(samples)
