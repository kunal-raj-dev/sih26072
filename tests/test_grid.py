from __future__ import annotations

import math
import numpy as np
import pytest

from vajra.grid import (
    GridSpec,
    LAEAProjection,
    haversine_km,
    india_grid,
    sevir_grid,
    sevir_laea_projection,
)


def test_laea_center_maps_to_origin():
    proj = LAEAProjection(lat_0=38.0, lon_0=-98.0)
    x, y = proj.forward(38.0, -98.0)
    assert abs(float(x)) < 1e-3
    assert abs(float(y)) < 1e-3

    lat, lon = proj.inverse(0.0, 0.0)
    assert abs(float(lat) - 38.0) < 1e-5
    assert abs(float(lon) - (-98.0)) < 1e-5


def test_laea_round_trip():
    proj = sevir_laea_projection()
    lats = np.array([28.0, 32.5, 38.0, 42.0, 48.0])
    lons = np.array([-105.0, -98.0, -95.0, -90.0, -85.0])

    x, y = proj.forward(lats, lons)
    lat_rec, lon_rec = proj.inverse(x, y)

    np.testing.assert_allclose(lat_rec, lats, atol=1e-5)
    np.testing.assert_allclose(lon_rec, lons, atol=1e-5)


def test_laea_distance_preservation():
    proj = sevir_laea_projection()
    # 1 degree north along central meridian
    x0, y0 = proj.forward(38.0, -98.0)
    x1, y1 = proj.forward(39.0, -98.0)
    # At spherical Earth R=6370997m, 1 deg lat is ~ 111.195 km
    dy_km = (float(y1) - float(y0)) / 1000.0
    assert 110.0 < dy_km < 112.5


def test_gridspec_bounds_negative_dlat():
    g = GridSpec(name="test_neg", lat0=30.0, lon0=80.0, dlat=-0.1, dlon=0.1, nlat=10, nlon=10)
    min_lon, min_lat, max_lon, max_lat = g.bounds
    assert min_lat < max_lat
    assert min_lon < max_lon
    assert abs(max_lat - 30.05) < 1e-4
    assert abs(min_lat - 29.05) < 1e-4


def test_gridspec_bounds_positive_dlat():
    g = GridSpec(name="test_pos", lat0=20.0, lon0=80.0, dlat=0.1, dlon=0.1, nlat=10, nlon=10)
    min_lon, min_lat, max_lon, max_lat = g.bounds
    assert min_lat < max_lat
    assert min_lon < max_lon
    assert abs(min_lat - 19.95) < 1e-4
    assert abs(max_lat - 20.95) < 1e-4


def test_india_grid_edges():
    g = india_grid(0.1)
    min_lon, min_lat, max_lon, max_lat = g.bounds
    assert 5.9 < min_lat < 6.1
    assert 37.9 < max_lat < 38.1
    assert 65.9 < min_lon < 66.1
    assert 97.9 < max_lon < 98.1
