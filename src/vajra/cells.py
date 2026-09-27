"""Storm-cell detection and tracking on gridded intensity fields.

Detection:
1. Standard connected components (TITAN-lineage object approach).
2. Multi-threshold watershed segmentation (tobac-like): detects 35, 45, and 55 dBZ
   convective cores and segments embedded cells within large cloud shields.

Tracking:
1. Greedy nearest-centroid matching with physically motivated speed gate.
2. 2D Linear Kalman Filter: estimates smoothed storm velocity [u, v] in km/h,
   meteorological heading in degrees (0-360), and calculates the projected
   60-minute cone of uncertainty.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from .config import CellsConfig
from .grid import GridSpec, KM_PER_DEG_LAT, haversine_km
from .ndx import label as cc_label
from .ndx import dilate
from .schemas import Cell, StormLifecycleState


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
    core_area_px: int = 0


class KalmanFilter2D:
    """Constant-velocity 2D linear Kalman filter for storm cell tracking.

    State vector: x = [lat, lon, v_lat, v_lon]^T (velocities in deg/hour).
    """

    def __init__(self, lat: float, lon: float, v_lat: float = 0.0, v_lon: float = 0.0) -> None:
        self.x = np.array([lat, lon, v_lat, v_lon], dtype=np.float64)
        # Position variance: ~0.01 deg (~1.1 km), velocity variance: 1.0 (deg/h)^2 (~111 km/h)
        self.P = np.diag([0.01**2, 0.01**2, 1.0**2, 1.0**2])
        # Centroid measurement precision: ~0.005 deg (~550 m)
        self.R = np.diag([0.005**2, 0.005**2])
        # Velocity drift rate (deg/h)^2 / h
        self.q = 0.8

    def predict(self, dt_h: float) -> np.ndarray:
        """Propagate state and covariance forward by dt_h hours."""
        if dt_h <= 0:
            return self.x.copy()
        dt = max(1e-4, dt_h)
        F = np.array([
            [1.0, 0.0, dt,  0.0],
            [0.0, 1.0, 0.0, dt],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ], dtype=np.float64)

        dt2 = 0.5 * (dt**2)
        dt3 = (dt**3) / 3.0
        Q = np.array([
            [dt3 * self.q, 0.0,          dt2 * self.q, 0.0],
            [0.0,          dt3 * self.q, 0.0,          dt2 * self.q],
            [dt2 * self.q, 0.0,          dt * self.q,  0.0],
            [0.0,          dt2 * self.q, 0.0,          dt * self.q],
        ], dtype=np.float64)

        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q
        return self.x.copy()

    def update(self, z_lat: float, z_lon: float, dt_h: float) -> None:
        """Incorporate new centroid measurement at dt_h hours since last update."""
        self.predict(dt_h)
        H = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ], dtype=np.float64)
        z = np.array([z_lat, z_lon], dtype=np.float64)
        y = z - (H @ self.x)
        S = H @ self.P @ H.T + self.R
        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        I = np.eye(4, dtype=np.float64)
        self.P = (I - K @ H) @ self.P

    @property
    def lat(self) -> float:
        return float(self.x[0])

    @property
    def lon(self) -> float:
        return float(self.x[1])

    @property
    def v_lat(self) -> float:
        return float(self.x[2])

    @property
    def v_lon(self) -> float:
        return float(self.x[3])

    @property
    def u_kmh(self) -> float:
        """East-west velocity component in km/h."""
        cos_lat = math.cos(math.radians(self.lat))
        return float(self.v_lon * KM_PER_DEG_LAT * cos_lat)

    @property
    def v_kmh(self) -> float:
        """North-south velocity component in km/h."""
        return float(self.v_lat * KM_PER_DEG_LAT)

    @property
    def speed_kmh(self) -> float:
        return float(math.sqrt(self.u_kmh**2 + self.v_kmh**2))

    @property
    def heading_deg(self) -> float:
        """Meteorological heading in degrees (0 = North, 90 = East, 180 = South, 270 = West)."""
        if self.speed_kmh < 0.5:
            return 0.0
        angle = math.degrees(math.atan2(self.u_kmh, self.v_kmh))
        return float((angle + 360.0) % 360.0)

    def predict_path(self, leads_min: tuple[int, ...] = (15, 30, 45, 60)) -> list[tuple[float, float]]:
        """Project future centroid lat/lon positions at specified lead times."""
        out = []
        for m in leads_min:
            h = m / 60.0
            out.append((float(self.lat + self.v_lat * h), float(self.lon + self.v_lon * h)))
        return out

    def uncertainty_cone(
        self,
        leads_min: tuple[int, ...] = (15, 30, 45, 60),
        base_radius_km: float = 12.0,
        vel_sigma_kmh: float = 12.0,
    ) -> list[list[float]]:
        """Generate polygon boundary representing the 60-minute cone of uncertainty.

        Coordinates are returned as [[lon, lat], ...] suitable for GeoJSON Polygon rings.
        """
        speed = self.speed_kmh
        cos_lat = max(1e-4, math.cos(math.radians(self.lat)))

        if speed < 1.0:
            # Omnidirectional circular expansion when storm is nearly stationary
            coords = []
            max_r = base_radius_km + 1.645 * vel_sigma_kmh
            dlat = max_r / KM_PER_DEG_LAT
            dlon = max_r / (KM_PER_DEG_LAT * cos_lat)
            for step in range(17):
                th = 2.0 * math.pi * step / 16
                coords.append([round(self.lon + dlon * math.cos(th), 4),
                               round(self.lat + dlat * math.sin(th), 4)])
            return coords

        # Unit normal vector perpendicular to motion
        nx = -self.v_kmh / speed
        ny = self.u_kmh / speed

        left_pts: list[list[float]] = []
        right_pts: list[list[float]] = []

        # Current position lateral envelope
        dlat_n = (ny * base_radius_km) / KM_PER_DEG_LAT
        dlon_n = (nx * base_radius_km) / (KM_PER_DEG_LAT * cos_lat)
        left_pts.append([round(self.lon + dlon_n, 4), round(self.lat + dlat_n, 4)])
        right_pts.append([round(self.lon - dlon_n, 4), round(self.lat - dlat_n, 4)])

        for m in leads_min:
            h = m / 60.0
            plat = self.lat + self.v_lat * h
            plon = self.lon + self.v_lon * h
            p_cos = max(1e-4, math.cos(math.radians(plat)))

            r_km = base_radius_km + 1.645 * vel_sigma_kmh * h
            p_dlat = (ny * r_km) / KM_PER_DEG_LAT
            p_dlon = (nx * r_km) / (KM_PER_DEG_LAT * p_cos)

            left_pts.append([round(plon + p_dlon, 4), round(plat + p_dlat, 4)])
            right_pts.append([round(plon - p_dlon, 4), round(plat - p_dlat, 4)])

        # Semi-circular cap at the furthest forecast point
        last_m = leads_min[-1]
        last_h = last_m / 60.0
        c_lat = self.lat + self.v_lat * last_h
        c_lon = self.lon + self.v_lon * last_h
        c_cos = max(1e-4, math.cos(math.radians(c_lat)))
        last_r = base_radius_km + 1.645 * vel_sigma_kmh * last_h

        heading_rad = math.atan2(self.u_kmh, self.v_kmh)
        cap_pts: list[list[float]] = []
        for i in range(1, 6):
            ang = heading_rad + (math.pi / 2.0) - (math.pi * i / 6.0)
            cap_lat = c_lat + (last_r * math.cos(ang)) / KM_PER_DEG_LAT
            cap_lon = c_lon + (last_r * math.sin(ang)) / (KM_PER_DEG_LAT * c_cos)
            cap_pts.append([round(cap_lon, 4), round(cap_lat, 4)])

        # Assemble closed ring: left forward -> cap -> right backward -> close
        polygon = left_pts + cap_pts + list(reversed(right_pts)) + [left_pts[0]]
        return polygon


@dataclass
class Track:
    cell_id: str
    detections: list[Detection] = field(default_factory=list)
    kalman: KalmanFilter2D | None = None
    prev_v_lat: float = 0.0
    prev_v_lon: float = 0.0
    prev_time: datetime | None = None
    has_initial_vel: bool = False

    @property
    def latest(self) -> Detection | None:
        return self.detections[-1] if self.detections else None


def compute_kinematic_acceleration(
    current_vel: tuple[float, float],  # (v_lat, v_lon) in deg/h
    prev_vel: tuple[float, float],     # (v_lat, v_lon) in deg/h
    dt_hours: float,
    lat: float,
) -> tuple[float, float, float, list[float]]:
    """Compute kinematic storm acceleration vector a = Delta v / Delta t.

    Parameters
    ----------
    current_vel:
        (v_lat, v_lon) at current step in deg/h.
    prev_vel:
        (v_lat, v_lon) at previous step in deg/h.
    dt_hours:
        Time delta in hours.
    lat:
        Mean latitude in degrees.

    Returns
    -------
    (accel_dlat, accel_dlon, accel_kmh2, accel_vector)
    """
    dt_h = max(1e-4, dt_hours)
    a_dlat = (current_vel[0] - prev_vel[0]) / dt_h
    a_dlon = (current_vel[1] - prev_vel[1]) / dt_h
    cos_lat = max(0.1, math.cos(math.radians(lat)))
    ay = a_dlat * KM_PER_DEG_LAT
    ax = a_dlon * KM_PER_DEG_LAT * cos_lat
    a_mag = math.sqrt(ax ** 2 + ay ** 2)
    return float(a_dlat), float(a_dlon), float(a_mag), [round(ax, 2), round(ay, 2)]


def detect_lightning_jump(
    flash_counts_history: list[int] | list[float],
    min_flash_rate: float = 6.0,
    sigma_threshold: float = 2.0,
) -> tuple[bool, float, float]:
    """Schulz et al. (2009, 2011) 2-Sigma Lightning Jump Detection algorithm.

    A lightning jump is defined as a sudden surge in the flash rate:
        Delta F >= sigma_threshold * sigma_hist
    where sigma_hist = sqrt(mean_hist) under Poisson statistics, requiring
    F_recent >= min_flash_rate (default 6 flashes/min) to suppress Poisson noise at low counts.

    Parameters
    ----------
    flash_counts_history:
        Sequence of historical flash counts or rates, with the last element being recent rate.
    min_flash_rate:
        Minimum recent flash count required to trigger a jump (default: 6.0).
    sigma_threshold:
        Multiplier for historical standard deviation (default: 2.0).

    Returns
    -------
    (is_jump, delta_f, required_threshold)
    """
    if not flash_counts_history:
        return False, 0.0, 0.0

    recent = float(flash_counts_history[-1])
    if recent < min_flash_rate:
        return False, 0.0, 0.0

    if len(flash_counts_history) < 2:
        return True, recent, 0.0

    history = [float(x) for x in flash_counts_history[:-1]]
    past_rate = float(np.mean(history))
    delta_f = recent - past_rate

    # Poisson standard deviation
    sigma_hist = max(1.0, math.sqrt(max(0.0, past_rate)))
    threshold = sigma_threshold * sigma_hist

    is_jump = bool(delta_f >= threshold and recent >= min_flash_rate)
    return is_jump, float(round(delta_f, 2)), float(round(threshold, 2))


def classify_cell_lifecycle(
    detections: list[Detection],
    px_area_km2: float,
    is_split: bool = False,
    is_merge: bool = False,
) -> tuple[StormLifecycleState, float, float]:
    """Classify storm cell lifecycle stage and compute volumetric growth rates.

    Parameters
    ----------
    detections:
        Chronological list of detections for this track, ending with recent.
    px_area_km2:
        Area of one grid pixel in km^2.
    is_split:
        True if cell emerged as daughter split from nearby parent.
    is_merge:
        True if cell merged multiple antecedent cells into single core.

    Returns
    -------
    (lifecycle_state, d_area_dt, d_vil_dt)
    """
    if is_split:
        return StormLifecycleState.SPLIT, 0.0, 0.0
    if is_merge:
        return StormLifecycleState.MERGE, 0.0, 0.0

    if not detections or len(detections) <= 1:
        return StormLifecycleState.INITIATING, 0.0, 0.0

    curr = detections[-1]
    prev = detections[-2]
    dt_h = max(1e-4, (curr.time - prev.time).total_seconds() / 3600.0)

    # Area expansion rate in km^2 / h
    d_area_km2 = (curr.area_px - prev.area_px) * px_area_km2
    d_area_dt = d_area_km2 / dt_h

    # Core intensity / VIL growth rate in dBZ / h (or raw units / h)
    d_intensity = curr.max_intensity - prev.max_intensity
    d_vil_dt = d_intensity / dt_h

    # Classification rules
    if d_area_dt > 15.0 or d_vil_dt > 5.0:
        stage = StormLifecycleState.INTENSIFYING
    elif d_area_dt < -15.0 or d_vil_dt < -5.0:
        stage = StormLifecycleState.DECAYING
    elif len(detections) >= 3 or curr.area_px * px_area_km2 >= 60.0 or curr.max_intensity >= 40.0:
        stage = StormLifecycleState.MATURE
    else:
        stage = StormLifecycleState.INITIATING

    return stage, float(round(d_area_dt, 2)), float(round(d_vil_dt, 2))


def detect_cells(
    field: np.ndarray, threshold: float, min_area_px: int
) -> list[tuple[int, int, int, int, int, float, float]]:
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


def watershed_cell_segmentation(
    field: np.ndarray,
    thresholds: tuple[float, ...] = (35.0, 45.0, 55.0),
    min_area_px: int = 4,
) -> list[tuple[int, int, int, int, int, float, float, int]]:
    """Multi-threshold watershed convective cell segmentation (tobac-like).

    Extracts convective storm cores (e.g. 45/55 dBZ) and partitions merged
    cloud shields at the base threshold (35 dBZ).

    Returns
    -------
    list of (i0, j0, i1, j1, area_px, max_int, mean_int, core_area_px)
    """
    t_base = thresholds[0]
    t_core = thresholds[1] if len(thresholds) > 1 else t_base

    mask = np.isfinite(field) & (field >= t_base)
    if not mask.any():
        return []

    lab, n = cc_label(mask)
    out: list[tuple[int, int, int, int, int, float, float, int]] = []

    for k in range(1, n + 1):
        comp_mask = lab == k
        core_mask = comp_mask & (field >= t_core)

        if not core_mask.any():
            ys, xs = np.nonzero(comp_mask)
            if ys.size >= min_area_px:
                vals = field[ys, xs]
                out.append((
                    int(ys.min()), int(xs.min()), int(ys.max()), int(xs.max()),
                    int(ys.size), float(vals.max()), float(vals.mean()), 0,
                ))
            continue

        core_lab, n_cores = cc_label(core_mask)
        valid_cores = []
        for c in range(1, n_cores + 1):
            c_ys, c_xs = np.nonzero(core_lab == c)
            if c_ys.size >= 2:
                valid_cores.append((c, float(c_ys.mean()), float(c_xs.mean()), c_ys.size))

        if len(valid_cores) <= 1:
            ys, xs = np.nonzero(comp_mask)
            if ys.size >= min_area_px:
                vals = field[ys, xs]
                core_px = int(np.count_nonzero(vals >= t_core))
                out.append((
                    int(ys.min()), int(xs.min()), int(ys.max()), int(xs.max()),
                    int(ys.size), float(vals.max()), float(vals.mean()), core_px,
                ))
        else:
            # Multiple distinct convective cores: Voronoi watershed partition
            ys, xs = np.nonzero(comp_mask)
            core_cents = np.array([[c[1], c[2]] for c in valid_cores])
            pts = np.column_stack([ys, xs])
            dists = np.sum((pts[:, None, :] - core_cents[None, :, :]) ** 2, axis=2)
            assignments = np.argmin(dists, axis=1)

            for idx in range(len(valid_cores)):
                c_mask = assignments == idx
                c_ys = ys[c_mask]
                c_xs = xs[c_mask]
                if c_ys.size >= min_area_px:
                    vals = field[c_ys, c_xs]
                    core_px = int(np.count_nonzero(vals >= t_core))
                    out.append((
                        int(c_ys.min()), int(c_xs.min()), int(c_ys.max()), int(c_xs.max()),
                        int(c_ys.size), float(vals.max()), float(vals.mean()), core_px,
                    ))

    return out


class CellTracker:
    """Kalman-filtered convective storm cell tracker across consecutive frames."""

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

    def step(
        self,
        t: datetime,
        field: np.ndarray,
        use_watershed: bool = False,
        thresholds: tuple[float, ...] = (35.0, 45.0, 55.0),
    ) -> list[Cell]:
        """Consume one frame; returns Cell objects for this frame (tracked)."""
        detections: list[Detection] = []

        if use_watershed:
            raw_dets = watershed_cell_segmentation(
                field, thresholds=thresholds, min_area_px=self.cfg.min_area_px
            )
            for (i0, j0, i1, j1, area, vmax, vmean, core_px) in raw_dets:
                ci, cj = (i0 + i1) / 2.0, (j0 + j1) / 2.0
                lat = self.grid.lat0 + self.grid.dlat * ci
                lon = self.grid.lon0 + self.grid.dlon * cj
                detections.append(Detection(
                    t, ci, cj, float(lat), float(lon),
                    (i0, j0, i1, j1), area, vmax, vmean, core_area_px=core_px,
                ))
        else:
            for (i0, j0, i1, j1, area, vmax, vmean) in detect_cells(
                field, self.cfg.vil_threshold, self.cfg.min_area_px
            ):
                ci, cj = (i0 + i1) / 2.0, (j0 + j1) / 2.0
                lat = self.grid.lat0 + self.grid.dlat * ci
                lon = self.grid.lon0 + self.grid.dlon * cj
                detections.append(Detection(
                    t, ci, cj, float(lat), float(lon),
                    (i0, j0, i1, j1), area, vmax, vmean,
                ))

        max_step = self._max_step_deg()
        unmatched_prev = list(self._prev)
        split_cell_ids: set[str] = set()
        merged_cell_ids: set[str] = set()

        for det in detections:
            best, best_d = None, 1e9
            for p in unmatched_prev:
                d = float(np.hypot(det.centroid_lat - p.centroid_lat,
                                   det.centroid_lon - p.centroid_lon))
                if d < best_d:
                    best, best_d = p, d
            if best is not None and best_d <= max_step:
                # Inherit cell ID and update Kalman filter
                det.cell_id = best.cell_id
                track = self.tracks[det.cell_id]
                last = track.detections[-1]
                dt_hours = max(1e-4, (det.time - last.time).total_seconds() / 3600.0)

                if track.kalman is not None:
                    track.kalman.update(det.centroid_lat, det.centroid_lon, dt_hours)
                else:
                    track.kalman = KalmanFilter2D(last.centroid_lat, last.centroid_lon)
                    track.kalman.update(det.centroid_lat, det.centroid_lon, dt_hours)

                track.detections.append(det)
                det.track_age = len(track.detections) - 1
                unmatched_prev.remove(best)

                # Check if another previous cell was close to this detection and got merged
                for other_p in list(unmatched_prev):
                    d_other = float(np.hypot(det.centroid_lat - other_p.centroid_lat,
                                             det.centroid_lon - other_p.centroid_lon))
                    if d_other <= max_step * 1.2:
                        merged_cell_ids.add(det.cell_id)
                        unmatched_prev.remove(other_p)
            else:
                self._counter += 1
                det.cell_id = f"C{self._counter:04d}"
                kf = KalmanFilter2D(det.centroid_lat, det.centroid_lon)
                self.tracks[det.cell_id] = Track(det.cell_id, [det], kalman=kf)
                det.track_age = 0

                # Check if this new detection split from an existing active previous cell
                for p in self._prev:
                    d_parent = float(np.hypot(det.centroid_lat - p.centroid_lat,
                                              det.centroid_lon - p.centroid_lon))
                    if d_parent <= max_step * 1.5:
                        split_cell_ids.add(det.cell_id)
                        break

        self._prev = detections

        # Convert detections -> schema Cells with Kalman velocity & projected track
        cells: list[Cell] = []
        cycle_h = self.cycle_minutes / 60.0
        px_area_km2 = (self.grid.dlon * KM_PER_DEG_LAT) * (abs(self.grid.dlat) * KM_PER_DEG_LAT)

        for det in detections:
            track = self.tracks[det.cell_id]
            idx = track.detections.index(det)
            if idx >= 1:
                prev_det = track.detections[idx - 1]
                mlat = (det.centroid_lat - prev_det.centroid_lat) / cycle_h * cycle_h
                mlon = (det.centroid_lon - prev_det.centroid_lon) / cycle_h * cycle_h
            else:
                mlat = mlon = 0.0

            kf = track.kalman
            vel_kmh = kf.speed_kmh if kf else 0.0
            heading = kf.heading_deg if kf else 0.0
            proj_pts = kf.predict_path((15, 30, 45, 60)) if kf else []
            base_r_km = max(8.0, math.sqrt(det.area_px * px_area_km2 / math.pi))
            cone_pts = kf.uncertainty_cone((15, 30, 45, 60), base_radius_km=base_r_km) if kf else []
            core_km2 = det.core_area_px * px_area_km2

            i0, j0, i1, j1 = det.bbox
            bbox_ll = [
                self.grid.lon0 + self.grid.dlon * j0 - self.grid.dlon / 2,
                self.grid.lat0 + self.grid.dlat * i1 - abs(self.grid.dlat) / 2,
                self.grid.lon0 + self.grid.dlon * j1 + self.grid.dlon / 2,
                self.grid.lat0 + self.grid.dlat * i0 + abs(self.grid.dlat) / 2,
            ]

            # Kinematic acceleration a = Delta v / Delta t
            if kf and track.has_initial_vel and track.prev_time:
                dt_accel_h = max(1e-4, (t - track.prev_time).total_seconds() / 3600.0)
                a_dlat, a_dlon, a_mag, a_vec = compute_kinematic_acceleration(
                    current_vel=(kf.v_lat, kf.v_lon),
                    prev_vel=(track.prev_v_lat, track.prev_v_lon),
                    dt_hours=dt_accel_h,
                    lat=det.centroid_lat,
                )
            else:
                a_dlat = a_dlon = a_mag = 0.0
                a_vec = [0.0, 0.0]

            if kf:
                track.prev_v_lat = kf.v_lat
                track.prev_v_lon = kf.v_lon
                track.prev_time = t
                if len(track.detections) >= 2:
                    track.has_initial_vel = True

            # Lifecycle classification and volumetric growth rates
            is_split = det.cell_id in split_cell_ids
            is_merge = det.cell_id in merged_cell_ids
            lifecycle, d_area_dt, d_vil_dt = classify_cell_lifecycle(
                detections=track.detections,
                px_area_km2=px_area_km2,
                is_split=is_split,
                is_merge=is_merge,
            )

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
                velocity_kmh=round(vel_kmh, 1),
                heading_deg=round(heading, 1),
                projected_track=[[round(p[1], 4), round(p[0], 4)] for p in proj_pts],
                uncertainty_cone=cone_pts,
                dbz_max=round(det.max_intensity, 1) if det.max_intensity > 20 else 0.0,
                core_area_km2=round(core_km2, 1),
                accel_dlat=round(a_dlat, 5),
                accel_dlon=round(a_dlon, 5),
                acceleration_kmh2=round(a_mag, 2),
                acceleration_vector=a_vec,
                lifecycle_state=lifecycle,
                d_area_dt=d_area_dt,
                d_vil_dt=d_vil_dt,
            ))
        return cells

    def predicted_path(self, cell_id: str, lead_minutes: int) -> list[tuple[float, float]]:
        """Extrapolated centroid positions at +lead/2 and +lead."""
        track = self.tracks.get(cell_id)
        if not track or not track.detections:
            return []
        if track.kalman and len(track.detections) >= 2:
            return track.kalman.predict_path((lead_minutes // 2, lead_minutes))
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


def flashes_near(
    points: np.ndarray | None, lat: float, lon: float, radius_km: float,
    t_from: datetime, t_to: datetime, point_times: np.ndarray | None = None
) -> int:
    """Count flashes within radius_km of (lat, lon) between t_from and t_to."""
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
