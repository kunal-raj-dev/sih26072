"""Canonical grid definitions and geometry helpers.

Two grids exist in the system:
- the canonical nowcast grid (default: India at 0.1 deg), used for forecasts/alerts;
- source grids (e.g. the SEVIR 2 km sector), which are regridded/annotated onto the
  canonical grid or served with their own metadata.

SEVIR geolocation is APPROXIMATE (equirectangular around a fixed sector centre);
the verified GOES-East geotransform is research backlog item C-9. All outputs carry
this caveat via grid metadata.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class GridSpec:
    """A regular lat/lon grid. lat0/lon0 = centre of the [0,0] pixel."""

    name: str
    lat0: float          # centre latitude of pixel [0, 0] (top row)
    lon0: float          # centre longitude of pixel [0, 0] (left col)
    dlat: float          # degrees per row (positive => lat decreases downward)
    dlon: float          # degrees per col
    nlat: int
    nlon: int
    geolocation: str = "exact"  # "exact" | "approximate"

    @property
    def lats(self) -> np.ndarray:
        return self.lat0 + self.dlat * np.arange(self.nlat)

    @property
    def lons(self) -> np.ndarray:
        return self.lon0 + self.dlon * np.arange(self.nlon)

    @property
    def lat_edges(self) -> tuple[float, float]:
        lats = self.lats
        half = abs(self.dlat) / 2.0
        return (float(lats[-1] - half), float(lats[0] + half))

    @property
    def lon_edges(self) -> tuple[float, float]:
        lons = self.lons
        half = self.dlon / 2.0
        return (float(lons[0] - half), float(lons[-1] + half))

    def cell_polygon(self, i: int, j: int) -> list[list[float]]:
        """GeoJSON-style ring (lon, lat) for pixel (i, j), closed."""
        half_lat = abs(self.dlat) / 2.0
        half_lon = self.dlon / 2.0
        lat = self.lat0 + self.dlat * i
        lon = self.lon0 + self.dlon * j
        return [
            [lon - half_lon, lat - half_lat],
            [lon + half_lon, lat - half_lat],
            [lon + half_lon, lat + half_lat],
            [lon - half_lon, lat + half_lat],
            [lon - half_lon, lat - half_lat],
        ]

    def index_of(self, lat: float, lon: float) -> tuple[int, int] | None:
        i = int(round((lat - self.lat0) / self.dlat))
        j = int(round((lon - self.lon0) / self.dlon))
        if 0 <= i < self.nlat and 0 <= j < self.nlon:
            return i, j
        return None


def india_grid(step_deg: float = 0.1) -> GridSpec:
    lat_min, lat_max, lon_min, lon_max = 6.0, 38.0, 66.0, 98.0
    nlat = int(round((lat_max - lat_min) / step_deg)) + 1
    nlon = int(round((lon_max - lon_min) / step_deg)) + 1
    return GridSpec(
        name=f"india_{str(step_deg).replace('.', 'p')}",
        lat0=lat_max, lon0=lon_min, dlat=-step_deg, dlon=step_deg,
        nlat=nlat, nlon=nlon, geolocation="exact",
    )


def sevir_grid(center_lat: float, center_lon: float, km_per_px: float, n: int) -> GridSpec:
    """Approximate lat/lon grid for the SEVIR fixed sector (equirectangular)."""
    deg_per_px = km_per_px / 111.0
    half = (n - 1) / 2.0
    return GridSpec(
        name="sevir_2km",
        lat0=center_lat + half * deg_per_px,
        lon0=center_lon - half * deg_per_px,
        dlat=-deg_per_px,
        dlon=deg_per_px,
        nlat=n,
        nlon=n,
        geolocation="approximate",
    )


KM_PER_DEG_LAT = 111.32


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


@dataclass
class RegridWeights:
    """Nearest-neighbour mapping from a source grid to the target grid.

    Good enough for 2 km -> 0.1 deg downscaling where cells are >=5 source px wide;
    documented as an approximation, not area-averaging.
    """

    target: GridSpec
    src: GridSpec
    ii: np.ndarray = field(init=False)
    jj: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        t_lats, t_lons = self.target.lats, self.target.lons
        # For each target row/col find nearest source index.
        src_lat_step = abs(self.src.dlat)
        src_lon_step = self.src.dlon
        ti = np.round((t_lats - self.src.lat0) / self.src.dlat).astype(int)
        tj = np.round((t_lons - self.src.lon0) / src_lon_step).astype(int)
        ti = np.clip(ti, 0, self.src.nlat - 1)
        tj = np.clip(tj, 0, self.src.nlon - 1)
        self.ii, self.jj = np.meshgrid(ti, tj, indexing="ij")

    def regrid(self, field: np.ndarray) -> np.ndarray:
        if field.shape != (self.src.nlat, self.src.nlon):
            raise ValueError(f"field shape {field.shape} != source grid {(self.src.nlat, self.src.nlon)}")
        return field[self.ii, self.jj]
