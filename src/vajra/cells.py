"""Storm-cell detection and tracking on gridded intensity fields.

Detection: threshold + connected components (4-connectivity) — the TITAN-lineage
object approach identified by the research (MASTER.md §7) as the operational
backbone. Tracking: greedy nearest-centroid matching with a physically motivated
speed gate (config cells.max_track_speed_km_h). Motion vectors are per-step
displacements divided by the step interval; this is computed, not animated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from .config import CellsConfig
from .grid import GridSpec, KM_PER_DEG_LAT, haversine_km
from .ndx import label as cc_label
from .ndx import dilate
from .schemas import Cell


@dataclass
class Detection:
    time: datetime
    centroid_i: float
    centroid_j: float
    centroid_lat: float
    centroid_lon: float
    bbox: tuple[int, int, int, int]      # i0, j0, i1, j1 (inclusive)
    area_px: int
    max_intensity: float
    mean_intensity: float
    cell_id: str = ""
    track_age: int = 0


@dataclass
class Track:
    cell_id: str
    detections: list[Detection] = field(default_factory=list)

    @property
    def latest(self) -> Detection | None:
        return self.detections[-1] if self.detections else None


def detect_cells(field: np.ndarray, threshold: float, min_area_px: int) -> list[tuple[int, int, int, int, int, float, float]]:
    """Returns detections as (i0, j0, i1, j1, area_px, max_int, mean_int)."""
    mask = np.isfinite(field) & (field >= threshold)
    if not mask.any():
        return []
    lab, n = cc_label(mask)
    out = []
    for k in range(1, n + 1):
        ys, xs = np.nonzero(lab == k)
        if ys.size < min_area_px:
            continue
        vals = field[ys, xs]
        out.append((int(ys.min()), int(xs.min()), int(ys.max()), int(xs.max()),
                    int(ys.size), float(vals.max()), float(vals.mean())))
    return out


class CellTracker:
    """Greedy nearest-centroid tracker across consecutive frames."""

    def __init__(self, grid: GridSpec, cfg: CellsConfig, cycle_minutes: int):
        self.grid = grid
        self.cfg = cfg
        self.cycle_minutes = cycle_minutes
        self.tracks: dict[str, Track] = {}
        self._prev: list[Detection] = []
        self._counter = 0

    def _max_step_deg(self) -> float:
        km = self.cfg.max_track_speed_km_h * (self.cycle_minutes / 60.0)
        return km / KM_PER_DEG_LAT

    def step(self, t: datetime, field: np.ndarray) -> list[Cell]:
        """Consume one frame; returns Cell objects for this frame (tracked)."""
        detections: list[Detection] = []
        for (i0, j0, i1, j1, area, vmax, vmean) in detect_cells(field, self.cfg.vil_threshold, self.cfg.min_area_px):
            ci, cj = (i0 + i1) / 2.0, (j0 + j1) / 2.0
            lat = self.grid.lat0 + self.grid.dlat * ci
            lon = self.grid.lon0 + self.grid.dlon * cj
            detections.append(Detection(t, ci, cj, float(lat), float(lon),
                                        (i0, j0, i1, j1), area, vmax, vmean))
        max_step = self._max_step_deg()
        dlat = abs(self.grid.dlat)
        dlon = self.grid.dlon
        unmatched_prev = list(self._prev)
        for det in detections:
            best, best_d = None, 1e9
            for p in unmatched_prev:
                d = float(np.hypot(det.centroid_lat - p.centroid_lat,
                                   det.centroid_lon - p.centroid_lon))
                if d < best_d:
                    best, best_d = p, d
            if best is not None and best_d <= max_step:
                # inherit id
                det.cell_id = best.cell_id
                track = self.tracks[det.cell_id]
                n_prev = max(1, len(track.detections) - 1)
                last = track.detections[-1]
                dt_hours = max(1e-6, (det.time - last.time).total_seconds() / 3600.0)
                det_motion = ((det.centroid_lat - last.centroid_lat) / dt_hours,
                              (det.centroid_lon - last.centroid_lon) / dt_hours)
                _ = n_prev
                track.detections.append(det)
                det.track_age = len(track.detections) - 1
                unmatched_prev.remove(best)
            else:
                self._counter += 1
                det.cell_id = f"C{self._counter:04d}"
                self.tracks[det.cell_id] = Track(det.cell_id, [det])
                det.track_age = 0
        self._prev = detections
        # Convert detections -> schema Cells with per-step motion (deg per cycle).
        cells: list[Cell] = []
        cycle_h = self.cycle_minutes / 60.0
        for det in detections:
            track = self.tracks[det.cell_id]
            idx = track.detections.index(det)
            if idx >= 1:
                prev_det = track.detections[idx - 1]
                mlat = (det.centroid_lat - prev_det.centroid_lat) / cycle_h * cycle_h
                mlon = (det.centroid_lon - prev_det.centroid_lon) / cycle_h * cycle_h
            else:
                mlat = mlon = 0.0
            i0, j0, i1, j1 = det.bbox
            bbox_ll = [
                self.grid.lon0 + self.grid.dlon * j0 - self.grid.dlon / 2,
                self.grid.lat0 + self.grid.dlat * i1 - abs(self.grid.dlat) / 2,
                self.grid.lon0 + self.grid.dlon * j1 + self.grid.dlon / 2,
                self.grid.lat0 + self.grid.dlat * i0 + abs(self.grid.dlat) / 2,
            ]
            cells.append(Cell(
                id=det.cell_id, time=t,
                centroid_lat=det.centroid_lat, centroid_lon=det.centroid_lon,
                bbox=[round(bbox_ll[0], 4), round(bbox_ll[1], 4), round(bbox_ll[2], 4), round(bbox_ll[3], 4)],
                area_px=det.area_px,
                max_intensity=round(det.max_intensity, 2),
                mean_intensity=round(det.mean_intensity, 2),
                track_age_steps=det.track_age,
                motion_dlat=round(mlat, 5), motion_dlon=round(mlon, 5),
                intensity_units="raw",
            ))
        return cells

    def predicted_path(self, cell_id: str, lead_minutes: int) -> list[tuple[float, float]]:
        """Extrapolated centroid positions at +lead/2 and +lead (computed extrapolation)."""
        track = self.tracks.get(cell_id)
        if not track or not track.detections:
            return []
        last = track.detections[-1]
        idx = len(track.detections) - 1
        if idx >= 1:
            prev = track.detections[idx - 1]
            dt_h = max(1e-6, (last.time - prev.time).total_seconds() / 3600.0)
            vlat = (last.centroid_lat - prev.centroid_lat) / dt_h
            vlon = (last.centroid_lon - prev.centroid_lon) / dt_h
        else:
            vlat = vlon = 0.0
        out = []
        for frac in (0.5, 1.0):
            h = lead_minutes * frac / 60.0
            out.append((last.centroid_lat + vlat * h, last.centroid_lon + vlon * h))
        return out


def flashes_near(points: np.ndarray | None, lat: float, lon: float, radius_km: float,
                 t_from: datetime, t_to: datetime, point_times: np.ndarray | None = None) -> int:
    """Count flashes within radius_km of (lat, lon) between t_from and t_to.

    points: (N, >=2) lat, lon, ... ; point_times: (N,) datetimes as epoch seconds
    or None when points already cover the window.
    """
    if points is None or len(points) == 0:
        return 0
    lat_r = radius_km / KM_PER_DEG_LAT
    lon_r = radius_km / max(1e-6, KM_PER_DEG_LAT * np.cos(np.radians(lat)))
    box = (np.abs(points[:, 0] - lat) <= lat_r) & (np.abs(points[:, 1] - lon) <= lon_r)
    sel = box
    if point_times is not None and len(point_times) == len(points):
        t0 = t_from.timestamp()
        t1 = t_to.timestamp()
        sel &= (point_times >= t0) & (point_times <= t1)
    return int(sel.sum())
