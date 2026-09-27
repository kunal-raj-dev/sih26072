"""Unit and integration tests for Multi-Radar Ingestion & Composite Mosaic Engine (Phase 3).

Verifies:
1. Doppler Weather Radar (DWR) station registry and geodesic range ring generation.
2. Multi-radar compositing: Maximum Reflectivity (MaxZ) and Cressman distance-weighting.
3. Multi-threshold watershed convective cell segmentation (tobac-like 35, 45, 55 dBZ cores).
4. 2D linear Kalman filter for storm velocity, heading, and projected 60-min cone of uncertainty.
5. Standard meteorological radar reflectivity PNG rendering.
6. REST API endpoints under /api/v1/radar/*.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vajra.api.app import create_app
from vajra.cells import CellTracker, KalmanFilter2D, watershed_cell_segmentation
from vajra.config import CellsConfig, load_settings
from vajra.grid import india_grid
from vajra.providers.radar_mosaic import (
    RADAR_STATIONS,
    RadarMosaicEngine,
    RadarStation,
    simulate_synthetic_radar_scan,
)
from vajra.render import render_reflectivity_png


@pytest.fixture(scope="module")
def grid():
    return india_grid(0.1)


@pytest.fixture(scope="module")
def mosaic_engine():
    return RadarMosaicEngine()


@pytest.fixture
def client(settings):
    app = create_app(settings)
    return TestClient(app)


def test_radar_stations_registry(mosaic_engine: RadarMosaicEngine):
    stations = mosaic_engine.stations
    assert len(stations) >= 6
    station_ids = {s.id for s in stations}
    assert {"patna", "kolkata", "ranchi", "lucknow", "paradip"}.issubset(station_ids)

    for st in stations:
        assert 10.0 <= st.lat <= 35.0
        assert 68.0 <= st.lon <= 95.0
        assert st.max_range_km >= 200.0
        assert 100.0 in st.rings_km and 250.0 in st.rings_km
        assert st.status == "ACTIVE"


def test_range_rings_geojson_generation(mosaic_engine: RadarMosaicEngine):
    fc = mosaic_engine.generate_rings_geojson()
    assert fc["type"] == "FeatureCollection"
    features = fc["features"]
    assert len(features) > 0

    station_points = [f for f in features if f["properties"].get("type") == "station"]
    rings = [f for f in features if f["properties"].get("type") == "range_ring"]

    assert len(station_points) == len(mosaic_engine.stations)
    assert len(rings) == len(mosaic_engine.stations) * 2  # 100 km and 250 km for each

    # Verify closed LineString coordinates for rings
    for r in rings:
        coords = r["geometry"]["coordinates"]
        assert len(coords) >= 60
        # Ring should close back to start
        assert coords[0] == coords[-1]


def test_multi_radar_compositing_max_and_cressman(mosaic_engine: RadarMosaicEngine, grid):
    patna = mosaic_engine.get_station("patna")
    ranchi = mosaic_engine.get_station("ranchi")
    assert patna is not None and ranchi is not None

    # Place an intense convective storm core in the overlap zone between Patna & Ranchi (lat 24.5, lon 85.2)
    cores = [(24.5, 85.2, 58.0, 20.0)]
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)

    scan_patna = simulate_synthetic_radar_scan(patna, grid, cores, time=now)
    scan_ranchi = simulate_synthetic_radar_scan(ranchi, grid, cores, time=now)

    assert scan_patna.reflectivity_dbz.max() > 40.0
    assert scan_ranchi.reflectivity_dbz.max() > 40.0

    # 1. Test MaxZ compositing
    comp_max, meta_max = mosaic_engine.composite([scan_patna, scan_ranchi], grid, method="max")
    assert comp_max.shape == (grid.nlat, grid.nlon)
    assert meta_max["max_dbz"] >= 50.0
    assert meta_max["overlap_area_km2"] > 0.0
    assert {"patna", "ranchi"}.issubset(set(meta_max["stations_used"]))

    # Peak reflectivity conservation
    assert abs(meta_max["max_dbz"] - 58.0) < 4.0

    # 2. Test Cressman distance-weighted compositing
    comp_cress, meta_cress = mosaic_engine.composite([scan_patna, scan_ranchi], grid, method="cressman")
    assert comp_cress.shape == (grid.nlat, grid.nlon)
    assert meta_cress["max_dbz"] >= 45.0
    assert not np.isnan(comp_cress).any()
    assert not np.isinf(comp_cress).any()


def test_watershed_cell_segmentation_partitions_multicell_system(grid):
    # Construct a synthetic reflectivity field with two 55 dBZ cores embedded in a single 38 dBZ cloud shield
    field = np.zeros((grid.nlat, grid.nlon), dtype=np.float32)

    # Core 1 at index (100, 100), Core 2 at index (100, 115)
    # Distance is 15 pixels. Base cloud shield covers both:
    y_idx, x_idx = np.ogrid[:grid.nlat, :grid.nlon]

    d1 = np.sqrt((y_idx - 100)**2 + (x_idx - 100)**2)
    d2 = np.sqrt((y_idx - 100)**2 + (x_idx - 115)**2)

    # Broad stratiform bridge (39 dBZ >= 35 base threshold)
    field = np.maximum(field, 39.0 * np.exp(-0.5 * (d1 / 20.0)**2))
    field = np.maximum(field, 39.0 * np.exp(-0.5 * (d2 / 20.0)**2))

    # Intense convective cores (55 dBZ)
    field = np.maximum(field, 55.0 * np.exp(-0.5 * (d1 / 4.0)**2))
    field = np.maximum(field, 52.0 * np.exp(-0.5 * (d2 / 4.0)**2))

    # Single threshold at 35 dBZ would yield only 1 merged component:
    from vajra.cells import detect_cells
    merged = detect_cells(field, threshold=35.0, min_area_px=4)
    assert len(merged) == 1, "Single threshold should merge the touching cores"

    # Multi-threshold watershed segmentation must partition the two distinct convective cores:
    segmented = watershed_cell_segmentation(field, thresholds=(35.0, 45.0, 55.0), min_area_px=4)
    assert len(segmented) == 2, f"Watershed should partition into 2 cells, got {len(segmented)}"

    for det in segmented:
        i0, j0, i1, j1, area_px, vmax, vmean, core_px = det
        assert vmax >= 50.0
        assert core_px > 0
        assert area_px >= 4


def test_kalman_filter_velocity_heading_and_cone():
    kf = KalmanFilter2D(lat=25.0, lon=85.0)

    # Simulate eastward motion of ~70 km/h: ~0.1 deg lon in 10 minutes (0.1667 h)
    t_step_h = 10.0 / 60.0
    kf.update(25.0, 85.1, t_step_h)
    kf.update(25.0, 85.2, t_step_h)

    # Filtered velocity check
    speed = kf.speed_kmh
    assert 40.0 <= speed <= 100.0, f"Expected speed ~60-75 km/h, got {speed:.1f}"

    # Heading check: eastward motion must be near 90 degrees
    heading = kf.heading_deg
    assert 70.0 <= heading <= 110.0, f"Expected heading near 90 deg (East), got {heading:.1f}"

    # 60-min Projected Path
    path = kf.predict_path(leads_min=(15, 30, 45, 60))
    assert len(path) == 4
    # Longitude should increase eastward
    assert path[0][1] < path[1][1] < path[2][1] < path[3][1]

    # Uncertainty cone geometry
    cone = kf.uncertainty_cone(leads_min=(15, 30, 45, 60), base_radius_km=10.0)
    assert len(cone) >= 10
    # Must be a closed polygon (first == last)
    assert cone[0] == cone[-1]


def test_cell_tracker_kalman_integration(grid):
    cfg = CellsConfig(vil_threshold=35.0, min_area_px=4, max_track_speed_km_h=180.0)
    tracker = CellTracker(grid, cfg, cycle_minutes=10)

    t0 = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    f1 = np.zeros((grid.nlat, grid.nlon), dtype=np.float32)
    # Core at 25.0 N, 85.0 E
    i_c, j_c = round((25.0 - grid.lat0) / grid.dlat), round((85.0 - grid.lon0) / grid.dlon)
    f1[i_c - 3:i_c + 4, j_c - 3:j_c + 4] = 52.0

    cells1 = tracker.step(t0, f1, use_watershed=True)
    assert len(cells1) == 1
    assert cells1[0].dbz_max >= 50.0

    # Step 2: advect east by 0.1 deg
    t1 = t0 + timedelta(minutes=10)
    f2 = np.zeros((grid.nlat, grid.nlon), dtype=np.float32)
    j_c2 = round((85.1 - grid.lon0) / grid.dlon)
    f2[i_c - 3:i_c + 4, j_c2 - 3:j_c2 + 4] = 54.0

    cells2 = tracker.step(t1, f2, use_watershed=True)
    assert len(cells2) == 1
    assert cells2[0].id == cells1[0].id
    assert cells2[0].velocity_kmh > 0
    assert 70.0 <= cells2[0].heading_deg <= 110.0
    assert len(cells2[0].projected_track) > 0
    assert len(cells2[0].uncertainty_cone) > 0


def test_reflectivity_png_rendering():
    dbz = np.zeros((100, 100), dtype=np.float32)
    # Add gradients from light rain to severe hail core
    dbz[10:30, 10:30] = 12.0  # Light rain (blue)
    dbz[30:50, 30:50] = 32.0  # Moderate rain (green)
    dbz[50:70, 50:70] = 48.0  # Heavy rain / convective (amber/orange)
    dbz[70:90, 70:90] = 62.0  # Severe / hail (magenta)

    png_bytes = render_reflectivity_png(dbz)
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    # Read back image and verify dimensions
    img = Image.open(io.BytesIO(png_bytes))
    assert img.size == (100, 100)
    assert img.mode == "RGBA"


def test_api_radar_endpoints(client: TestClient):
    # 1. Stations
    r_st = client.get("/api/v1/radar/stations")
    assert r_st.status_code == 200
    st_list = r_st.json()
    assert len(st_list) >= 6
    patna = next(s for s in st_list if s["id"] == "patna")
    assert patna["name"] == "Patna DWR"
    assert patna["max_range_km"] == 250.0

    # 2. Rings GeoJSON
    r_rings = client.get("/api/v1/radar/rings.geojson")
    assert r_rings.status_code == 200
    fc = r_rings.json()
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) > 0

    # 3. Mosaic Latest
    r_meta = client.get("/api/v1/radar/mosaic/latest")
    assert r_meta.status_code == 200
    meta = r_meta.json()
    assert "stations_used" in meta
    assert "max_dbz" in meta
    assert meta["max_dbz"] > 0.0

    # 4. Mosaic Field PNG
    r_png = client.get("/api/v1/radar/mosaic/field.png")
    assert r_png.status_code == 200
    assert r_png.headers["content-type"] == "image/png"
    assert len(r_png.content) > 500
