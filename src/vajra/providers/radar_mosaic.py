"""Multi-Radar Ingestion and Composite Mosaic Engine for Project Vajra.

Fulfills Problem Statement 26072's explicit mandate for multiple Doppler Weather
Radars (DWR) across Indian pilot domains (Bihar, Eastern UP, West Bengal, Odisha).

Key Capabilities:
1. Station Registry: Physical parameters, beam geometry, coordinates, and range rings
   (100 km quantitative surveillance, 250 km surveillance).
2. Mosaic Compositing:
   - Maximum Reflectivity (MaxZ) Compositing (MRMS operational standard)
   - Distance-Weighted Cressman Interpolation:
       w_k(d) = (R_max^2 - d^2) / (R_max^2 + d^2)  for d <= R_max
   - Nearest-Station Coverage
3. Seamless Overlap: Eliminates boundary seamlines across overlapping sweeps
   (e.g., Patna DWR + Kolkata DWR + Ranchi DWR).
4. Range Rings GeoJSON: Generates geodesic rings (100 km, 250 km) for MapLibre GIS.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import numpy as np

from ..grid import GridSpec, KM_PER_DEG_LAT, haversine_km
from ..logsetup import get_logger
from ..schemas import DataHealth, DataMode, Modality, ObsFrame, ObsFrameMeta, QualityInfo, QualityStatus, GridMeta

logger = get_logger("vajra.providers.radar_mosaic")


@dataclass(frozen=True)
class RadarStation:
    """Doppler Weather Radar (DWR) Station metadata."""

    id: str
    name: str
    lat: float
    lon: float
    altitude_m: float = 50.0
    max_range_km: float = 250.0
    rings_km: tuple[float, ...] = (100.0, 250.0)
    band: str = "S-band"
    status: str = "ACTIVE"


# Canonical Indian DWR Station Registry for Project Vajra Pilot Domain
RADAR_STATIONS: dict[str, RadarStation] = {
    "patna": RadarStation(
        id="patna",
        name="Patna DWR",
        lat=25.591,
        lon=85.088,
        altitude_m=58.0,
        max_range_km=250.0,
        band="S-band",
    ),
    "kolkata": RadarStation(
        id="kolkata",
        name="Kolkata (Subhashgram) DWR",
        lat=22.427,
        lon=88.423,
        altitude_m=12.0,
        max_range_km=250.0,
        band="S-band",
    ),
    "ranchi": RadarStation(
        id="ranchi",
        name="Ranchi DWR",
        lat=23.322,
        lon=85.321,
        altitude_m=650.0,
        max_range_km=250.0,
        band="S-band",
    ),
    "lucknow": RadarStation(
        id="lucknow",
        name="Lucknow DWR",
        lat=26.761,
        lon=80.883,
        altitude_m=128.0,
        max_range_km=250.0,
        band="S-band",
    ),
    "paradip": RadarStation(
        id="paradip",
        name="Paradip DWR",
        lat=20.296,
        lon=86.708,
        altitude_m=15.0,
        max_range_km=250.0,
        band="S-band",
    ),
    "gopalpur": RadarStation(
        id="gopalpur",
        name="Gopalpur DWR",
        lat=19.308,
        lon=84.914,
        altitude_m=22.0,
        max_range_km=250.0,
        band="S-band",
    ),
    "visakhapatnam": RadarStation(
        id="visakhapatnam",
        name="Visakhapatnam DWR",
        lat=17.728,
        lon=83.338,
        altitude_m=45.0,
        max_range_km=250.0,
        band="S-band",
    ),
    "delhi": RadarStation(
        id="delhi",
        name="Delhi (Palam) DWR",
        lat=28.583,
        lon=77.083,
        altitude_m=228.0,
        max_range_km=250.0,
        band="C-band",
    ),
}


@dataclass
class RadarVolumeScan:
    """A gridded 2D maximum reflectivity (MaxZ) or sweep scan from one DWR station."""

    station: RadarStation
    time: datetime
    reflectivity_dbz: np.ndarray  # (nlat, nlon) in dBZ (-10 to 75 typical)
    grid: GridSpec
    coverage_mask: np.ndarray | None = None  # True where within beam range & unobstructed
    quality_status: QualityStatus = QualityStatus.OK


class RadarMosaicEngine:
    """Composites multiple Doppler Weather Radar feeds into a continuous 2D field."""

    def __init__(self, stations: list[RadarStation] | None = None) -> None:
        self.stations = stations or list(RADAR_STATIONS.values())
        self._station_lookup = {s.id: s for s in self.stations}

    def get_station(self, station_id: str) -> RadarStation | None:
        return self._station_lookup.get(station_id.lower())

    def compute_distance_grid_km(self, station: RadarStation, grid: GridSpec) -> np.ndarray:
        """Calculate great-circle distance (km) from station to all grid points."""
        dlat = (grid.lats[:, None] - station.lat) * KM_PER_DEG_LAT
        mean_lat_rad = np.radians((grid.lats[:, None] + station.lat) / 2.0)
        dlon = (grid.lons[None, :] - station.lon) * KM_PER_DEG_LAT * np.cos(mean_lat_rad)
        return np.sqrt(dlat**2 + dlon**2)

    def composite(
        self,
        scans: list[RadarVolumeScan],
        target_grid: GridSpec,
        method: Literal["max", "cressman", "nearest"] = "max",
        min_dbz: float = 5.0,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Combine overlapping radar scans into a single composite mosaic grid.

        Parameters
        ----------
        scans:
            List of RadarVolumeScan objects from 1 or more radar stations.
        target_grid:
            GridSpec of the composite output.
        method:
            "max": Operational Maximum Reflectivity (MRMS standard).
            "cressman": Range-squared distance-weighted blend over overlap zones.
            "nearest": Strict nearest-station selection.
        min_dbz:
            Threshold below which echoes are treated as clear air / zero.

        Returns
        -------
        composite_dbz:
            (nlat, nlon) float32 array in dBZ.
        meta:
            Dictionary of mosaic metadata (stations used, overlap fraction, stats).
        """
        if not scans:
            empty = np.zeros((target_grid.nlat, target_grid.nlon), dtype=np.float32)
            return empty, {"stations_used": [], "max_dbz": 0.0, "mean_dbz": 0.0, "overlap_area_km2": 0.0}

        nlat, nlon = target_grid.nlat, target_grid.nlon
        accum_dbz = np.zeros((nlat, nlon), dtype=np.float64)
        accum_weights = np.zeros((nlat, nlon), dtype=np.float64)
        max_dbz_grid = np.full((nlat, nlon), -np.inf, dtype=np.float64)
        min_dist_grid = np.full((nlat, nlon), np.inf, dtype=np.float64)
        nearest_dbz_grid = np.zeros((nlat, nlon), dtype=np.float64)

        coverage_counts = np.zeros((nlat, nlon), dtype=np.int32)
        stations_contributing: list[str] = []

        for scan in scans:
            st = scan.station
            stations_contributing.append(st.id)

            # Re-interpolate scan to target grid if geometries differ
            if scan.grid == target_grid:
                raw_dbz = np.nan_to_num(scan.reflectivity_dbz, nan=0.0).astype(np.float64)
            else:
                raw_dbz = self._resample_grid(scan.reflectivity_dbz, scan.grid, target_grid)

            # Calculate station distance matrix
            dist_km = self.compute_distance_grid_km(st, target_grid)

            # Range gating: only within station's maximum operational range
            in_range = dist_km <= st.max_range_km
            if scan.coverage_mask is not None:
                in_range &= scan.coverage_mask

            coverage_counts[in_range] += 1

            # 1. MaxZ compositing accumulator
            np.maximum(max_dbz_grid, raw_dbz, out=max_dbz_grid, where=in_range)

            # 2. Nearest station accumulator
            closer = in_range & (dist_km < min_dist_grid)
            min_dist_grid[closer] = dist_km[closer]
            nearest_dbz_grid[closer] = raw_dbz[closer]

            # 3. Cressman distance-weighting accumulator
            # Weight: w(d) = (R_max^2 - d^2) / (R_max^2 + d^2)
            r_max_sq = st.max_range_km ** 2
            d_sq = np.clip(dist_km ** 2, 0, r_max_sq)
            w = np.zeros_like(dist_km)
            w[in_range] = (r_max_sq - d_sq[in_range]) / (r_max_sq + d_sq[in_range] + 1e-6)

            accum_dbz += raw_dbz * w
            accum_weights += w

        # Resolve composite according to selected method
        if method == "max":
            max_dbz_grid[np.isneginf(max_dbz_grid)] = 0.0
            composite_field = np.clip(max_dbz_grid, 0.0, 75.0)
        elif method == "cressman":
            valid = accum_weights > 1e-6
            cressman_field = np.zeros((nlat, nlon), dtype=np.float64)
            cressman_field[valid] = accum_dbz[valid] / accum_weights[valid]
            # In single-coverage or low-weight margins, blend with MaxZ to prevent boundary seams
            blend = np.where(coverage_counts > 1, cressman_field, np.maximum(0.0, max_dbz_grid))
            composite_field = np.clip(blend, 0.0, 75.0)
        elif method == "nearest":
            composite_field = np.clip(nearest_dbz_grid, 0.0, 75.0)
        else:
            raise ValueError(f"Unknown compositing method: '{method}'")

        # Suppress noise below min_dbz
        composite_field[composite_field < min_dbz] = 0.0
        result = composite_field.astype(np.float32)

        # Calculate scientific metadata
        multi_coverage = coverage_counts >= 2
        px_area_km2 = (target_grid.dlon * KM_PER_DEG_LAT) * (abs(target_grid.dlat) * KM_PER_DEG_LAT)
        overlap_area_km2 = float(np.count_nonzero(multi_coverage) * px_area_km2)

        echoes = result[result >= min_dbz]
        convective_echoes = result[result >= 40.0]

        meta = {
            "method": method,
            "stations_used": sorted(set(stations_contributing)),
            "station_count": len(stations_contributing),
            "max_dbz": float(round(np.max(result), 1)) if result.size else 0.0,
            "mean_echo_dbz": float(round(np.mean(echoes), 1)) if len(echoes) else 0.0,
            "echo_area_km2": float(round(len(echoes) * px_area_km2, 1)),
            "convective_area_km2": float(round(len(convective_echoes) * px_area_km2, 1)),
            "overlap_area_km2": float(round(overlap_area_km2, 1)),
            "overlap_fraction": float(round(np.count_nonzero(multi_coverage) / max(1, np.count_nonzero(coverage_counts > 0)), 3)),
        }

        return result, meta

    def _resample_grid(self, src: np.ndarray, src_grid: GridSpec, dst_grid: GridSpec) -> np.ndarray:
        """Bilinear spatial resampling of a 2D field between regular lat/lon grids."""
        lat_frac = (dst_grid.lats[:, None] - src_grid.lat0) / src_grid.dlat
        lon_frac = (dst_grid.lons[None, :] - src_grid.lon0) / src_grid.dlon

        i0 = np.clip(np.floor(lat_frac).astype(int), 0, src_grid.nlat - 2)
        j0 = np.clip(np.floor(lon_frac).astype(int), 0, src_grid.nlon - 2)
        i1 = i0 + 1
        j1 = j0 + 1

        di = np.clip(lat_frac - i0, 0.0, 1.0)
        dj = np.clip(lon_frac - j0, 0.0, 1.0)

        top = (1.0 - dj) * src[i0, j0] + dj * src[i0, j1]
        bot = (1.0 - dj) * src[i1, j0] + dj * src[i1, j1]
        resampled = (1.0 - di) * top + di * bot
        return resampled

    def generate_rings_geojson(
        self,
        stations: list[RadarStation] | None = None,
        n_points: int = 64,
    ) -> dict[str, Any]:
        """Generate GeoJSON FeatureCollection of range rings (100 km and 250 km)."""
        active_stations = stations or self.stations
        features: list[dict[str, Any]] = []

        for st in active_stations:
            # 1. Station Point
            features.append({
                "type": "Feature",
                "id": f"station_{st.id}",
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(st.lon, 4), round(st.lat, 4)],
                },
                "properties": {
                    "type": "station",
                    "station_id": st.id,
                    "name": st.name,
                    "altitude_m": st.altitude_m,
                    "band": st.band,
                    "status": st.status,
                },
            })

            # 2. Concentric Range Rings (100 km and 250 km)
            for r_km in st.rings_km:
                ring_coords = self._generate_circle_coords(st.lat, st.lon, r_km, n_points)
                features.append({
                    "type": "Feature",
                    "id": f"ring_{st.id}_{int(r_km)}",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": ring_coords,
                    },
                    "properties": {
                        "type": "range_ring",
                        "station_id": st.id,
                        "name": f"{st.name} {int(r_km)} km Ring",
                        "radius_km": r_km,
                        "ring_type": "surveillance" if r_km > 150 else "quantitative",
                    },
                })

        return {"type": "FeatureCollection", "features": features}

    @staticmethod
    def _generate_circle_coords(
        center_lat: float, center_lon: float, radius_km: float, n_points: int = 64
    ) -> list[list[float]]:
        """Calculate great-circle boundary coordinates."""
        coords = []
        d_lat_deg = radius_km / KM_PER_DEG_LAT
        cos_lat = math.cos(math.radians(center_lat))
        d_lon_deg = radius_km / max(1e-4, KM_PER_DEG_LAT * cos_lat)

        for step in range(n_points + 1):
            theta = 2.0 * math.pi * step / n_points
            lat = center_lat + d_lat_deg * math.sin(theta)
            lon = center_lon + d_lon_deg * math.cos(theta)
            coords.append([round(lon, 4), round(lat, 4)])
        return coords


def simulate_synthetic_radar_scan(
    station: RadarStation,
    grid: GridSpec,
    storm_cores: list[tuple[float, float, float, float]],  # (lat, lon, peak_dbz, radius_km)
    time: datetime | None = None,
    noise_sigma: float = 0.5,
    seed: int = 42,
) -> RadarVolumeScan:
    """Helper to simulate realistic DWR sweeps with beam broadening and attenuation."""
    t = time or datetime.now(timezone.utc)
    rng = np.random.default_rng(seed + hash(station.id) % 8191)

    dlat = (grid.lats[:, None] - station.lat) * KM_PER_DEG_LAT
    mean_lat_rad = np.radians((grid.lats[:, None] + station.lat) / 2.0)
    dlon = (grid.lons[None, :] - station.lon) * KM_PER_DEG_LAT * np.cos(mean_lat_rad)
    dist_km = np.sqrt(dlat**2 + dlon**2)

    coverage_mask = dist_km <= station.max_range_km
    field_dbz = np.zeros((grid.nlat, grid.nlon), dtype=np.float64)

    for (clat, clon, peak_dbz, radius_km) in storm_cores:
        # Distance from storm center
        c_dlat = (grid.lats[:, None] - clat) * KM_PER_DEG_LAT
        c_dlon = (grid.lons[None, :] - clon) * KM_PER_DEG_LAT * np.cos(mean_lat_rad)
        c_dist_km = np.sqrt(c_dlat**2 + c_dlon**2)

        # Beam broadening effect at longer ranges: effective core radius widens slightly
        range_broadening = 1.0 + 0.15 * (dist_km / station.max_range_km)
        eff_radius = radius_km * range_broadening
        echo = peak_dbz * np.exp(-0.5 * (c_dist_km / eff_radius) ** 2)
        field_dbz = np.maximum(field_dbz, echo)

    # Slight measurement noise
    if noise_sigma > 0:
        noise = rng.normal(0.0, noise_sigma, (grid.nlat, grid.nlon))
        field_dbz = np.where(field_dbz > 5.0, field_dbz + noise, field_dbz)

    # Zero out beyond range
    field_dbz[~coverage_mask] = 0.0
    field_dbz = np.clip(field_dbz, 0.0, 75.0).astype(np.float32)

    return RadarVolumeScan(
        station=station,
        time=t,
        reflectivity_dbz=field_dbz,
        grid=grid,
        coverage_mask=coverage_mask,
    )
