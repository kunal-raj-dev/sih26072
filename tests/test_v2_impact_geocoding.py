"""Unit and integration test suite for Phase V2-7: Sub-District Administrative Geocoding & Impact Risk.

Verifies:
1. TASK-V2-7.1: Census Block GeoJSON Integration & Spatial Indexing
   - Ingestion of Jharkhand administrative districts and sub-district blocks into SpatialIndex.
   - Microsecond point-in-polygon queries for Ranchi, East Singhbhum, Dhanbad, Bokaro, and Deoghar.
   - query_blocks_in_bbox spatial bounds filtering.
   - Batch polygon-polygon intersection join (intersect_cells) with vectorized STRtree.
   - Benchmark SLA: 10 convective storm cells joined against administrative blocks in < 15 ms.
2. TASK-V2-7.2: Quantitative Impact Risk Engine
   - compute_hazard_severity combining flash rate, rain rate, and reflectivity in [0, 1].
   - compute_exposed_population_factor logarithmic scaling.
   - compute_vulnerability_weight temporal multiplier (1.5x agricultural peak between 11:00-17:00 IST).
   - compute_impact_risk: H * S * E * V.
3. TASK-V2-7.3: IMD 4-Stage Warning Color Band Alignment
   - GREEN (No Warning): P < 0.20 or Impact < 0.15
   - YELLOW (Watch / Be Updated): 0.20 <= P < 0.50
   - ORANGE (Alert / Be Prepared): 0.50 <= P < 0.75 or 2-sigma lightning jump
   - RED (Warning / Take Action): P >= 0.75 with high population exposure / extreme impact
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
import pytest
import numpy as np

from vajra.geocoding import AdminEntity, AdminIntersection, SpatialIndex
from vajra.risk import (
    IMDColorCode,
    compute_hazard_severity,
    compute_exposed_population_factor,
    compute_vulnerability_weight,
    compute_impact_risk,
    compute_imd_warning_level,
)
from vajra.schemas import Cell


@pytest.fixture(scope="module")
def spatial_idx() -> SpatialIndex:
    return SpatialIndex()


# =========================================================================
# TASK-V2-7.1: Census Block GeoJSON Integration & Spatial Indexing
# =========================================================================

def test_jharkhand_administrative_ingestion(spatial_idx: SpatialIndex):
    """Verify Jharkhand districts and sub-district blocks are successfully ingested."""
    assert spatial_idx.is_ready()
    # At least 24 districts (including 5 Jharkhand) and 85 blocks
    assert len(spatial_idx.districts) >= 24
    assert len(spatial_idx.blocks) >= 85

    jh_districts = [d for d in spatial_idx.districts if d.state == "Jharkhand"]
    assert len(jh_districts) >= 5
    jh_names = {d.name for d in jh_districts}
    assert {"Ranchi", "East Singhbhum", "Dhanbad", "Bokaro", "Deoghar"}.issubset(jh_names)

    jh_blocks = [b for b in spatial_idx.blocks if b.state == "Jharkhand"]
    assert len(jh_blocks) >= 14
    block_names = {b.name for b in jh_blocks}
    assert "Ranchi Sadar" in block_names
    assert "Golmuri Cum Jugsalai" in block_names
    assert "Dhanbad Sadar" in block_names
    assert "Chas" in block_names
    assert "Deoghar Sadar" in block_names


def test_jharkhand_point_queries(spatial_idx: SpatialIndex):
    """Verify point queries resolve accurately to Jharkhand districts and blocks."""
    # 1. Ranchi Sadar (23.36 N, 85.33 E)
    ranchi_blocks = spatial_idx.query_point(23.36, 85.33)
    assert len(ranchi_blocks) > 0
    assert any("Ranchi Sadar" in b.name for b in ranchi_blocks)
    assert ranchi_blocks[0].district == "Ranchi"
    assert ranchi_blocks[0].state == "Jharkhand"

    ranchi_dist = spatial_idx.query_district_for_point(23.36, 85.33)
    assert ranchi_dist is not None
    assert ranchi_dist.name == "Ranchi"
    assert ranchi_dist.state == "Jharkhand"

    # 2. Golmuri / Jamshedpur, East Singhbhum (22.80 N, 86.22 E)
    jamshedpur_blocks = spatial_idx.query_point(22.80, 86.22)
    assert len(jamshedpur_blocks) > 0
    assert any("Golmuri" in b.name for b in jamshedpur_blocks)
    assert jamshedpur_blocks[0].district == "East Singhbhum"

    # 3. Dhanbad Sadar (23.80 N, 86.43 E)
    dhanbad_blocks = spatial_idx.query_point(23.80, 86.43)
    assert len(dhanbad_blocks) > 0
    assert any("Dhanbad Sadar" in b.name for b in dhanbad_blocks)

    # 4. Chas, Bokaro (23.63 N, 86.17 E)
    chas_blocks = spatial_idx.query_point(23.63, 86.17)
    assert len(chas_blocks) > 0
    assert any("Chas" in b.name for b in chas_blocks)

    # 5. Deoghar Sadar (24.49 N, 86.70 E)
    deoghar_blocks = spatial_idx.query_point(24.49, 86.70)
    assert len(deoghar_blocks) > 0
    assert any("Deoghar Sadar" in b.name for b in deoghar_blocks)


def test_query_blocks_in_bbox(spatial_idx: SpatialIndex):
    """Verify spatial bounding box filtering returns all intersecting blocks."""
    # Bbox covering Ranchi region: [85.20, 23.20, 85.50, 23.50]
    bbox = (85.20, 23.20, 85.50, 23.50)
    blocks = spatial_idx.query_blocks_in_bbox(bbox)
    assert len(blocks) >= 3
    names = {b.name for b in blocks}
    assert "Ranchi Sadar" in names or "Kanke" in names or "Namkum" in names


def test_batch_intersect_cells_benchmark_under_15ms(spatial_idx: SpatialIndex):
    """Benchmark: 10 convective storm cells joined against administrative blocks completes in < 15 ms."""
    now = datetime.now(timezone.utc)
    coords = [
        (23.36, 85.33),  # Ranchi Sadar
        (23.43, 85.32),  # Kanke
        (22.80, 86.22),  # Golmuri
        (23.80, 86.43),  # Dhanbad Sadar
        (23.63, 86.17),  # Chas
        (25.61, 85.15),  # Patna Sadar
        (25.63, 85.04),  # Danapur
        (22.53, 88.33),  # Kolkata / Alipore
        (20.46, 85.88),  # Cuttack
        (25.32, 82.97),  # Varanasi
    ]

    cells = [
        Cell(
            id=f"CELL_BATCH_{i:02d}",
            time=now,
            centroid_lat=lat,
            centroid_lon=lon,
            bbox=[lon - 0.06, lat - 0.06, lon + 0.06, lat + 0.06],
            area_px=100,
            max_intensity=50.0,
            mean_intensity=35.0,
            flash_count_history=10,
        )
        for i, (lat, lon) in enumerate(coords)
    ]
    assert len(cells) == 10

    # Warmup
    _ = spatial_idx.intersect_cells(cells)

    # Measure batch join latency across 20 iterations
    latencies_ms = []
    for _ in range(20):
        t0 = time.perf_counter()
        batch_results = spatial_idx.intersect_cells(cells, min_overlap_fraction=0.05)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(dt_ms)

    avg_ms = sum(latencies_ms) / len(latencies_ms)
    min_ms = min(latencies_ms)
    max_ms = max(latencies_ms)

    # Verification Gate SLA: < 15 ms
    assert avg_ms < 15.0, f"Average batch join latency exceeded SLA: {avg_ms:.2f} ms >= 15 ms"
    assert min_ms < 15.0

    # Verify results parity with single cell join
    single_res = spatial_idx.intersect_cell(cells[0], min_overlap_fraction=0.05)
    batch_res = batch_results[cells[0].id]
    assert len(single_res) == len(batch_res)
    if single_res:
        assert single_res[0].entity.id == batch_res[0].entity.id


# =========================================================================
# TASK-V2-7.2: Quantitative Impact Risk Engine
# =========================================================================

def test_hazard_severity_normalization():
    """Verify compute_hazard_severity is bounded in [0, 1] and combines multi-sensor inputs."""
    # Zero inputs -> 0.0
    s_zero = compute_hazard_severity(cell=None, flash_rate=0.0, rain_rate_mmh=0.0)
    assert s_zero == 0.0

    # Max inputs -> 1.0
    s_max = compute_hazard_severity(cell=None, flash_rate=60.0, rain_rate_mmh=75.0, max_intensity_dbz=65.0)
    assert s_max == 1.0

    # Partial inputs: moderate flash + rain
    s_mid = compute_hazard_severity(cell=None, flash_rate=25.0, rain_rate_mmh=30.0)
    assert 0.45 <= s_mid <= 0.55

    # Cell max intensity only
    cell_moderate = Cell(
        id="c1",
        time=datetime.now(timezone.utc),
        centroid_lat=23.0,
        centroid_lon=85.0,
        bbox=[84.9, 22.9, 85.1, 23.1],
        area_px=50,
        max_intensity=47.5,
        mean_intensity=35.0,
    )
    s_cell = compute_hazard_severity(cell=cell_moderate)
    assert 0.45 <= s_cell <= 0.55


def test_exposed_population_factor_logarithmic():
    """Verify compute_exposed_population_factor logarithmic scaling in [0, 1]."""
    assert compute_exposed_population_factor(0) == 0.0
    assert compute_exposed_population_factor(-500) == 0.0
    assert compute_exposed_population_factor(500_000, ref_population=500_000) == 1.0
    assert compute_exposed_population_factor(1_000_000, ref_population=500_000) == 1.0

    # Monotonicity check
    f_1k = compute_exposed_population_factor(1_000)
    f_10k = compute_exposed_population_factor(10_000)
    f_100k = compute_exposed_population_factor(100_000)
    f_500k = compute_exposed_population_factor(500_000)
    assert 0.0 < f_1k < f_10k < f_100k < f_500k == 1.0


def test_vulnerability_weight_temporal_multiplier():
    """Verify 1.5x multiplier during 11:00-17:00 IST (agricultural peak) vs 1.0x outside."""
    ist = timezone(timedelta(hours=5, minutes=30))

    # 1. 2:00 PM IST (14:00 IST) -> Daytime agricultural peak -> 1.5x
    t_peak_ist = datetime(2026, 6, 15, 14, 0, tzinfo=ist)
    assert compute_vulnerability_weight(t_peak_ist) == 1.5

    # Equivalent UTC: 14:00 IST is 08:30 UTC
    t_peak_utc = datetime(2026, 6, 15, 8, 30, tzinfo=timezone.utc)
    assert compute_vulnerability_weight(t_peak_utc) == 1.5

    # 2. 8:00 AM IST (08:00 IST) -> Morning, before peak -> 1.0x
    t_morning_ist = datetime(2026, 6, 15, 8, 0, tzinfo=ist)
    assert compute_vulnerability_weight(t_morning_ist) == 1.0

    # 3. 11:00 PM IST (23:00 IST) -> Nighttime -> 1.0x
    t_night_ist = datetime(2026, 6, 15, 23, 0, tzinfo=ist)
    assert compute_vulnerability_weight(t_night_ist) == 1.0

    # 4. Boundary cases: 11:00 IST (exact start) -> 1.5x, 17:00 IST (exact end) -> 1.5x
    assert compute_vulnerability_weight(datetime(2026, 6, 15, 11, 0, tzinfo=ist)) == 1.5
    assert compute_vulnerability_weight(datetime(2026, 6, 15, 17, 0, tzinfo=ist)) == 1.5
    assert compute_vulnerability_weight(datetime(2026, 6, 15, 17, 1, tzinfo=ist)) == 1.0


def test_compute_impact_risk_multiplication():
    """Verify ImpactRisk = P * S * E * V formula."""
    ist = timezone(timedelta(hours=5, minutes=30))
    t_peak = datetime(2026, 6, 15, 14, 0, tzinfo=ist)
    t_night = datetime(2026, 6, 15, 22, 0, tzinfo=ist)

    # Daytime peak test
    risk_day = compute_impact_risk(
        p_hazard=0.80,
        hazard_severity=0.75,
        exposed_population=500_000,
        t=t_peak,
    )
    # P=0.8, S=0.75, E=1.0, V=1.5 => 0.8 * 0.75 * 1.0 * 1.5 = 0.9000
    assert abs(risk_day - 0.9000) < 1e-3

    # Nighttime test
    risk_night = compute_impact_risk(
        p_hazard=0.80,
        hazard_severity=0.75,
        exposed_population=500_000,
        t=t_night,
    )
    # P=0.8, S=0.75, E=1.0, V=1.0 => 0.8 * 0.75 * 1.0 * 1.0 = 0.6000
    assert abs(risk_night - 0.6000) < 1e-3
    assert risk_day == pytest.approx(risk_night * 1.5, rel=1e-3)

    # Zero hazard probability -> 0.0
    assert compute_impact_risk(0.0, 0.9, 200_000, t=t_peak) == 0.0


# =========================================================================
# TASK-V2-7.3: IMD 4-Stage Warning Color Band Alignment
# =========================================================================

def test_imd_color_code_matrix_alignment():
    """Verify alignment with official IMD Color Code matrix: GREEN, YELLOW, ORANGE, RED."""
    # 1. GREEN (No Warning): P < 0.20 or Impact < 0.15
    assert compute_imd_warning_level(p_hazard=0.10, impact_risk=0.08) == IMDColorCode.GREEN
    assert compute_imd_warning_level(p_hazard=0.15, impact_risk=0.12) == IMDColorCode.GREEN

    # 2. YELLOW (Watch / Be Updated): 0.20 <= P < 0.50 or Impact >= 0.15
    assert compute_imd_warning_level(p_hazard=0.25, impact_risk=0.10) == IMDColorCode.YELLOW
    assert compute_imd_warning_level(p_hazard=0.45, impact_risk=0.25) == IMDColorCode.YELLOW
    # Low P but high impact
    assert compute_imd_warning_level(p_hazard=0.18, impact_risk=0.20) == IMDColorCode.YELLOW

    # 3. ORANGE (Alert / Be Prepared): 0.50 <= P < 0.75 or 2-sigma jump
    assert compute_imd_warning_level(p_hazard=0.55, impact_risk=0.30) == IMDColorCode.ORANGE
    assert compute_imd_warning_level(p_hazard=0.70, exposed_population=50_000) == IMDColorCode.ORANGE
    # 2-sigma jump triggers ORANGE even with lower probability
    assert compute_imd_warning_level(p_hazard=0.35, is_lightning_jump=True) == IMDColorCode.ORANGE

    # 4. RED (Warning / Take Action): P >= 0.75 with High Population Exposure or extreme impact
    # High population (>= 100,000) with P >= 0.75
    assert compute_imd_warning_level(p_hazard=0.80, exposed_population=150_000) == IMDColorCode.RED
    # High impact (>= 0.50) with P >= 0.75
    assert compute_imd_warning_level(p_hazard=0.85, impact_risk=0.55) == IMDColorCode.RED
    # 2-sigma jump with high probability (P >= 0.70) escalates directly to RED
    assert compute_imd_warning_level(p_hazard=0.72, is_lightning_jump=True) == IMDColorCode.RED


def test_imd_color_code_enum_values():
    """Verify IMDColorCode enum string representations."""
    assert IMDColorCode.GREEN == "GREEN"
    assert IMDColorCode.YELLOW == "YELLOW"
    assert IMDColorCode.ORANGE == "ORANGE"
    assert IMDColorCode.RED == "RED"
