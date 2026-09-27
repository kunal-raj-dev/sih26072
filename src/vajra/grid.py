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
        return (float(min(lats[0], lats[-1]) - half), float(max(lats[0], lats[-1]) + half))

    @property
    def lon_edges(self) -> tuple[float, float]:
        lons = self.lons
        half = abs(self.dlon) / 2.0
        return (float(min(lons[0], lons[-1]) - half), float(max(lons[0], lons[-1]) + half))

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """Returns (min_lon, min_lat, max_lon, max_lat)."""
        min_lat, max_lat = self.lat_edges
        min_lon, max_lon = self.lon_edges
        return (min_lon, min_lat, max_lon, max_lat)


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


make_india_grid = india_grid


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


class LAEAProjection:
    """Lambert Azimuthal Equal Area (LAEA) projection.

    Supports exact spherical transformation (Snyder 1987) and leverages
    pyproj if installed for high-speed C-optimized projection transforms.
    Standard SEVIR projection parameters:
        lat_0 = 38.0 N, lon_0 = -98.0 E, a = 6370997.0 m, b = 6370997.0 m
    """

    def __init__(self, lat_0: float = 38.0, lon_0: float = -98.0,
                 a: float = 6370997.0, b: float = 6370997.0):
        self.lat_0 = float(lat_0)
        self.lon_0 = float(lon_0)
        self.a = float(a)
        self.b = float(b)
        self._lat_0_rad = math.radians(self.lat_0)
        self._lon_0_rad = math.radians(self.lon_0)
        self._pyproj_crs = None
        try:
            import pyproj
            proj_str = (f"+proj=laea +lat_0={self.lat_0} +lon_0={self.lon_0} "
                        f"+units=m +a={self.a} +b={self.b} +no_defs")
            self._pyproj_crs = pyproj.Proj(proj_str)
        except Exception:
            self._pyproj_crs = None

    def forward(self, lat: float | np.ndarray, lon: float | np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Convert latitude and longitude (degrees) to LAEA x and y (meters)."""
        if self._pyproj_crs is not None:
            x, y = self._pyproj_crs(lon, lat)
            return np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)

        # Pure-python / numpy analytical spherical LAEA (Snyder 1987)
        lat_rad = np.radians(np.asarray(lat, dtype=np.float64))
        lon_rad = np.radians(np.asarray(lon, dtype=np.float64))
        dlon = lon_rad - self._lon_0_rad

        phi0 = self._lat_0_rad
        cos_c = np.sin(phi0) * np.sin(lat_rad) + np.cos(phi0) * np.cos(lat_rad) * np.cos(dlon)
        cos_c = np.clip(cos_c, -1.0, 1.0)
        denom = np.maximum(1.0 + cos_c, 1e-12)
        k_prime = np.sqrt(2.0 / denom)

        x = self.a * k_prime * np.cos(lat_rad) * np.sin(dlon)
        y = self.a * k_prime * (np.cos(phi0) * np.sin(lat_rad) - np.sin(phi0) * np.cos(lat_rad) * np.cos(dlon))
        return x, y

    def inverse(self, x: float | np.ndarray, y: float | np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Convert LAEA x and y (meters) to latitude and longitude (degrees)."""
        if self._pyproj_crs is not None:
            lon, lat = self._pyproj_crs(x, y, inverse=True)
            return np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64)

        # Pure-python / numpy analytical spherical LAEA inverse (Snyder 1987)
        xa = np.asarray(x, dtype=np.float64)
        ya = np.asarray(y, dtype=np.float64)
        rho = np.hypot(xa, ya)

        phi0 = self._lat_0_rad
        c = 2.0 * np.arcsin(np.clip(rho / (2.0 * self.a), -1.0, 1.0))
        sin_c = np.sin(c)
        cos_c = np.cos(c)

        with np.errstate(divide="ignore", invalid="ignore"):
            sin_phi = cos_c * np.sin(phi0) + np.where(rho > 0, (ya * sin_c * np.cos(phi0)) / rho, 0.0)
            sin_phi = np.clip(sin_phi, -1.0, 1.0)
            lat_rad = np.arcsin(sin_phi)

            term_y = np.where(rho > 0, rho * np.cos(phi0) * cos_c - ya * np.sin(phi0) * sin_c, 1.0)
            term_x = np.where(rho > 0, xa * sin_c, 0.0)
            dlon = np.arctan2(term_x, term_y)

        lon_rad = self._lon_0_rad + dlon
        lat_deg = np.degrees(lat_rad)
        lon_deg = (np.degrees(lon_rad) + 180.0) % 360.0 - 180.0
        return lat_deg, lon_deg


def sevir_laea_projection() -> LAEAProjection:
    """Official SEVIR Lambert Azimuthal Equal Area projection."""
    return LAEAProjection(lat_0=38.0, lon_0=-98.0, a=6370997.0, b=6370997.0)


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
