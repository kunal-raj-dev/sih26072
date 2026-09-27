"""Unit and integration tests for Project Vajra's administrative boundaries & geocoding engine.

Verifies:
- STRtree spatial indexing initialization and topological integrity.
- Microsecond point-in-polygon queries for key Indian administrative headquarters.
- Cell polygon intersection, overlap fraction, and exposed population calculation.
- Query execution latency is strictly < 50 ms (SLA performance requirement).
- AlertEngine integration with administrative strings and population exposure.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
import pytest

from vajra.alerts import AlertEngine
from vajra.config import Settings, load_settings
from vajra.geocoding import AdminEntity, AdminIntersection, SpatialIndex
from vajra.schemas import Cell, DataMode, FallbackRung, Forecast, ForecastStep


@pytest.fixture(scope="module")
def spatial_idx() -> SpatialIndex:
    return SpatialIndex()


def test_spatial_index_initialization(spatial_idx: SpatialIndex):
    assert spatial_idx.is_ready()
    assert len(spatial_idx.districts) >= 15
    assert len(spatial_idx.blocks) >= 50

    d_fc = spatial_idx.get_district_geojson()
    assert d_fc["type"] == "FeatureCollection"
    assert len(d_fc["features"]) == len(spatial_idx.districts)

    b_fc = spatial_idx.get_blocks_geojson()
    assert b_fc["type"] == "FeatureCollection"
    assert len(b_fc["features"]) == len(spatial_idx.blocks)


def test_point_query_known_pilot_locations(spatial_idx: SpatialIndex):
    # 1. Patna Sadar, Bihar
    patna_blocks = spatial_idx.query_point(25.61, 85.15)
    assert len(patna_blocks) > 0
    names = [b.name for b in patna_blocks]
    assert "Patna Sadar" in names
    assert patna_blocks[0].district == "Patna"
    assert patna_blocks[0].state == "Bihar"

    # District query
    patna_dist = spatial_idx.query_district_for_point(25.61, 85.15)
    assert patna_dist is not None
    assert patna_dist.name == "Patna"
    assert patna_dist.state == "Bihar"

    # 2. Danapur, Bihar
    danapur_blocks = spatial_idx.query_point(25.63, 85.04)
    assert any("Danapur" in b.name for b in danapur_blocks)

    # 3. Kolkata / Alipore, West Bengal
    kolkata_blocks = spatial_idx.query_point(22.53, 88.33)
    assert any("Alipore" in b.name for b in kolkata_blocks)
    assert any(b.state == "West Bengal" for b in kolkata_blocks)

    # 4. Cuttack Sadar, Odisha
    cuttack_blocks = spatial_idx.query_point(20.46, 85.88)
    assert any("Cuttack" in b.name for b in cuttack_blocks)
    assert any(b.state == "Odisha" for b in cuttack_blocks)

    # 5. Varanasi, Uttar Pradesh
    varanasi_blocks = spatial_idx.query_point(25.32, 82.97)
    assert any("Varanasi" in b.name for b in varanasi_blocks)
    assert any(b.state == "Uttar Pradesh" for b in varanasi_blocks)


def test_point_query_latency_strictly_under_50ms(spatial_idx: SpatialIndex):
    test_points = [
        (25.61, 85.15),  # Patna Sadar
        (25.63, 85.04),  # Danapur
        (24.80, 85.00),  # Gaya Town
        (26.12, 85.42),  # Mushahari (Muzaffarpur)
        (22.57, 88.36),  # Kolkata Core
        (22.53, 88.33),  # Alipore
        (20.46, 85.88),  # Cuttack Sadar
        (20.29, 85.82),  # Bhubaneswar Municipal
        (25.32, 82.97),  # Varanasi Sadar
        (26.76, 83.37),  # Gorakhpur Sadar
    ]

    latencies_ms = []
    # Warmup
    for lat, lon in test_points:
        spatial_idx.query_point(lat, lon)

    # Measure 100 queries
    for _ in range(10):
        for lat, lon in test_points:
            t0 = time.perf_counter()
            res = spatial_idx.query_point(lat, lon)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(dt_ms)
            assert len(res) > 0

    max_latency = max(latencies_ms)
    avg_latency = sum(latencies_ms) / len(latencies_ms)

    # Required SLA: < 50 ms. Typically sub-millisecond with STRtree.
    assert max_latency < 50.0, f"Max latency exceeded SLA: {max_latency:.2f} ms >= 50 ms"
    assert avg_latency < 5.0, f"Average latency too high: {avg_latency:.2f} ms"


def test_cell_intersection_and_population_exposure(spatial_idx: SpatialIndex):
    # Create synthetic storm cell positioned right over Danapur block
    now = datetime.now(timezone.utc)
    cell = Cell(
        id="CELL_TEST_01",
        time=now,
        centroid_lat=25.63,
        centroid_lon=85.04,
        bbox=[84.98, 25.57, 85.10, 25.69],
        area_px=120,
        max_intensity=52.5,
        mean_intensity=38.0,
    )

    intersections = spatial_idx.intersect_cell(cell, min_overlap_fraction=0.05)
    assert len(intersections) > 0

    danapur_match = next((x for x in intersections if "Danapur" in x.entity.name), None)
    assert danapur_match is not None
    assert danapur_match.overlap_fraction > 0.05
    assert danapur_match.overlap_area_sqkm > 0.0
    assert danapur_match.exposed_population > 0

    # Human-readable region formatting
    region_str = spatial_idx.format_region_name(intersections)
    assert "Bihar" in region_str
    assert "Patna" in region_str


def test_cell_intersection_latency_strictly_under_50ms(spatial_idx: SpatialIndex):
    now = datetime.now(timezone.utc)
    # Generate 50 storm cells across Eastern India
    cells = []
    for i, (lat, lon) in enumerate([
        (25.60, 85.10), (25.50, 85.00), (24.80, 85.00), (26.10, 85.40),
        (22.50, 88.30), (20.50, 85.90), (20.30, 85.80), (25.30, 83.00),
    ] * 6):
        cells.append(
            Cell(
                id=f"CELL_PERF_{i}",
                time=now,
                centroid_lat=lat,
                centroid_lon=lon,
                bbox=[lon - 0.08, lat - 0.08, lon + 0.08, lat + 0.08],
                area_px=100,
                max_intensity=45.0,
                mean_intensity=32.0,
            )
        )

    latencies_ms = []
    for cell in cells:
        t0 = time.perf_counter()
        ix = spatial_idx.intersect_cell(cell)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(dt_ms)
        assert len(ix) > 0

    max_lat = max(latencies_ms)
    avg_lat = sum(latencies_ms) / len(latencies_ms)

    assert max_lat < 50.0, f"Max intersection latency exceeded SLA: {max_lat:.2f} ms"
    assert avg_lat < 5.0, f"Avg intersection latency too high: {avg_lat:.2f} ms"


def test_format_region_name_hierarchical():
    idx = SpatialIndex()
    # Mock admin entities
    e1 = AdminEntity("danapur", "Danapur", "Patna", "Bihar", "Bihar / Patna / Danapur Block", 380000, 150.0, (0,0,1,1), None)
    e2 = AdminEntity("phulwari", "Phulwari Sharif", "Patna", "Bihar", "Bihar / Patna / Phulwari Sharif Block", 320000, 140.0, (0,0,1,1), None)
    e3 = AdminEntity("gaya_sadar", "Gaya Sadar", "Gaya", "Bihar", "Bihar / Gaya / Gaya Sadar Block", 410000, 160.0, (0,0,1,1), None)

    # 1 entity
    assert idx.format_region_name([e1]) == "Bihar / Patna / Danapur Block"

    # 2 entities same district
    assert idx.format_region_name([e1, e2]) == "Bihar / Patna (Danapur, Phulwari Sharif)"

    # 2 entities across different districts
    cross = idx.format_region_name([e1, e3])
    assert "Bihar" in cross and "Gaya" in cross and "Patna" in cross

    # Empty list fallback
    assert idx.format_region_name([], fallback="Fallback Name") == "Fallback Name"


def test_alert_engine_outputs_administrative_strings_and_exposure():
    settings = load_settings()
    spatial_index = SpatialIndex()
    engine = AlertEngine(settings, spatial_index=spatial_index)

    now = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
    # Cell placed directly over Danapur / Patna Sadar
    cell = Cell(
        id="CELL_PATNA_01",
        time=now,
        centroid_lat=25.63,
        centroid_lon=85.04,
        bbox=[84.98, 25.57, 85.10, 25.69],
        area_px=150,
        max_intensity=55.0,
        mean_intensity=40.0,
    )

    forecast = Forecast(
        event_id="SIM_BIHAR_001",
        replay_time=now,
        mode=DataMode.SIMULATION,
        fallback_rung=FallbackRung.PHYSICS_BASELINE,
        model_version="xgb-test-v1",
        modalities_used=[],
        steps=[ForecastStep(valid_time=now, lead_minutes=30, p_flash_max=0.85, risk_band="HIGH")],
        confidence=0.90,
    )

    # High probability triggering WARNING / WATCH
    alerts = engine.generate(forecast, [cell], lead_minutes=30, p_cell={"CELL_PATNA_01": 0.85})
    assert len(alerts) > 0

    alert = alerts[0]
    # Acceptance Criterion 1: Alert.region_name outputs human-readable administrative strings
    assert "Bihar" in alert.region_name
    assert "Patna" in alert.region_name
    assert "Danapur" in alert.region_name or "Block" in alert.region_name
    assert "Patna" in alert.affected_districts
    assert len(alert.affected_blocks) > 0
    assert alert.population_exposed > 0
