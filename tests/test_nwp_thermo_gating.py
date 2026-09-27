"""Verification suite for Phase 5: NWP Environmental Intelligence & Thermodynamic Gating.

Covers:
1. Pure-Python GRIB2 Template 5.0 Simple Packing encode/decode round-trip.
2. Bulk wind shear (0-6 km) and Bulk Richardson Number (BRN) computation.
3. Scientific thermodynamic gating logic (CAPE/CIN penalties and probability suppression).
4. Spatial resampling of GFS 0.25° grid to canonical 0.1° regional grid.
5. Ingestion of multi-field GFS GRIB2 granules and QC physical range checks.
6. Feature matrix population with all 16 features without NaNs.
7. NowcastPipeline lifecycle, fallback routing (FULL_FUSION vs REDUCED_MODALITY), and REST API.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pytest
from starlette.testclient import TestClient

from vajra.config import Settings
from vajra.grid import make_india_grid
from vajra.schemas import (
    Cell, DataMode, FallbackRung, Modality, ObsFrame, ObsFrameMeta,
    QualityInfo, QualityStatus, GridMeta,
)
from vajra.cells import CellTracker
from vajra.features import FEATURE_NAMES, build_features
from vajra.models.baselines import AdvectionModel, ClimatologyModel, PersistenceModel
from vajra.models.router import ModelRouter
from vajra.pipeline import NowcastPipeline
from vajra.providers.gfs import (
    GfsNomadsProvider,
    encode_grib2_message,
    decode_grib2_messages,
    compute_bulk_wind_shear_0_6km,
    compute_bulk_richardson_number,
    thermodynamic_gating_factor,
    apply_thermodynamic_gating,
    resample_gfs_to_grid,
    create_mock_gfs_grib2,
)
from vajra.api.app import create_app


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        yield Path(d)


# =============================================================================
# 1. GRIB2 Simple Packing Encode / Decode Roundtrip
# =============================================================================

def test_grib2_simple_packing_roundtrip():
    """Verify that pure-Python GRIB2 encoding and decoding accurately preserves 2D fields."""
    nlat, nlon = 129, 129
    # Synthesize realistic convective CAPE field
    y, x = np.ogrid[:nlat, :nlon]
    cape_field = (500.0 + 2500.0 * np.exp(-((y - 64) ** 2 + (x - 64) ** 2) / (2 * 15 ** 2))).astype(np.float32)

    msg_bytes = encode_grib2_message("cape", cape_field, bits_per_value=16)
    assert len(msg_bytes) > 0
    assert msg_bytes.startswith(b"GRIB")
    assert msg_bytes.endswith(b"7777")

    decoded = decode_grib2_messages(msg_bytes)
    assert len(decoded) == 1
    assert decoded[0]["variable"] == "cape"
    assert decoded[0]["nlat"] == nlat
    assert decoded[0]["nlon"] == nlon

    rec = decoded[0]["data"]
    # 16-bit simple packing quantization error must be < 0.1 J/kg over range [500, 3000]
    max_err = float(np.max(np.abs(cape_field - rec)))
    assert max_err < 0.1, f"Quantization error too large: {max_err}"


def test_grib2_multi_message_decoding():
    """Verify multi-message GRIB2 granule decoding (CAPE, CIN, Wind, RH)."""
    nlat, nlon = 129, 129
    cape = np.full((nlat, nlon), 2200.0, dtype=np.float32)
    cin = np.full((nlat, nlon), 45.0, dtype=np.float32)
    rh = np.full((nlat, nlon), 75.0, dtype=np.float32)

    stream = (
        encode_grib2_message("cape", cape)
        + encode_grib2_message("cin", cin)
        + encode_grib2_message("rh_700", rh)
    )

    decoded = decode_grib2_messages(stream)
    assert len(decoded) == 3
    vars_found = [m["variable"] for m in decoded]
    assert vars_found == ["cape", "cin", "rh_700"]
    assert np.allclose(decoded[0]["data"], 2200.0, atol=0.1)
    assert np.allclose(decoded[1]["data"], 45.0, atol=0.1)
    assert np.allclose(decoded[2]["data"], 75.0, atol=0.1)


# =============================================================================
# 2. Bulk Wind Shear and Bulk Richardson Number
# =============================================================================

def test_bulk_wind_shear_and_brn():
    """Verify bulk vertical wind shear vector magnitude and Bulk Richardson Number."""
    # Test vector shear: u10=-6, v10=2, u500=18, v500=9 -> du=24, dv=7 -> shear=sqrt(576+49)=25 m/s
    u10 = np.array([[-6.0]], dtype=np.float32)
    v10 = np.array([[2.0]], dtype=np.float32)
    u500 = np.array([[18.0]], dtype=np.float32)
    v500 = np.array([[9.0]], dtype=np.float32)

    shear = compute_bulk_wind_shear_0_6km(u10, v10, u500, v500)
    assert np.isclose(shear[0, 0], 25.0, atol=1e-4)

    # Bulk Richardson Number: BRN = CAPE / (0.5 * shear^2) = 2500 / (0.5 * 625) = 8.0
    cape = np.array([[2500.0]], dtype=np.float32)
    brn = compute_bulk_richardson_number(cape, shear)
    assert np.isclose(brn[0, 0], 8.0, atol=1e-4)

    # Edge cases: zero shear -> BRN is finite (clamped to 500.0 maximum)
    zero_shear = np.array([[0.0]], dtype=np.float32)
    brn_zero = compute_bulk_richardson_number(cape, zero_shear)
    assert brn_zero[0, 0] == 500.0

    # Negative or zero CAPE -> BRN is 0.0
    zero_cape = np.array([[0.0]], dtype=np.float32)
    brn_neg = compute_bulk_richardson_number(zero_cape, shear)
    assert brn_neg[0, 0] == 0.0


# =============================================================================
# 3. Scientific Thermodynamic Gating Logic
# =============================================================================

def test_thermodynamic_gating_factor_rules():
    """Verify thermodynamic gating rules for CAPE and CIN suppression."""
    # 1. Uninhibited strong convection: CAPE >= 1000, CIN <= 200 -> gamma = 1.0
    gamma = thermodynamic_gating_factor(cape=2400.0, cin=30.0)
    assert gamma == 1.0

    # 2. Weak updraft energy: CAPE < 1000 -> linear reduction
    gamma_weak = thermodynamic_gating_factor(cape=600.0, cin=50.0)
    assert np.isclose(gamma_weak, 0.6, atol=1e-4)

    # 3. Floor clamping: very low CAPE clamped to 0.1 minimum
    gamma_floor = thermodynamic_gating_factor(cape=30.0, cin=50.0)
    assert np.isclose(gamma_floor, 0.1, atol=1e-4)

    # 4. Strong capping inversion: CIN > 200 -> linear penalty
    # CIN = 300 -> 1.0 - (300-200)/200 = 0.5
    gamma_cap = thermodynamic_gating_factor(cape=2000.0, cin=300.0)
    assert np.isclose(gamma_cap, 0.5, atol=1e-4)

    # 5. Compound suppression: weak CAPE (500 J/kg -> 0.5) and cap (CIN 300 J/kg -> 0.5)
    gamma_compound = thermodynamic_gating_factor(cape=500.0, cin=300.0)
    assert np.isclose(gamma_compound, 0.25, atol=1e-4)

    # 6. Missing NWP (NaN): returns 1.0 without throwing errors
    gamma_nan = thermodynamic_gating_factor(cape=np.nan, cin=np.nan)
    assert gamma_nan == 1.0


def test_apply_thermodynamic_gating_suppression():
    """Verify that apply_thermodynamic_gating suppresses false alarms on decaying anvils."""
    raw_p = 0.80

    # In explosive environment: probability preserved
    p_explosive = apply_thermodynamic_gating(raw_p, cape=2500.0, cin=40.0)
    assert np.isclose(p_explosive, 0.80, atol=1e-4)

    # In decaying anvil (cold IR / leftover radar, but atmosphere dead: CAPE=350, CIN=250)
    # gamma_cape = 0.35, gamma_cin = 1.0 - 50/200 = 0.75 -> gamma = 0.2625
    p_decaying = apply_thermodynamic_gating(raw_p, cape=350.0, cin=250.0)
    expected_p = 0.80 * (350.0 / 1000.0) * (1.0 - 50.0 / 200.0)
    assert np.isclose(p_decaying, expected_p, atol=1e-4)
    assert p_decaying < 0.25


# =============================================================================
# 4. Spatial Resampling to Canonical Indian Grid
# =============================================================================

def test_resample_gfs_to_grid():
    """Verify bilinear interpolation from GFS 0.25° to canonical 0.1° grid."""
    grid = make_india_grid()
    nlat, nlon = 129, 129
    lats = np.linspace(38.0, 6.0, nlat, dtype=np.float32)
    lons = np.linspace(66.0, 98.0, nlon, dtype=np.float32)

    # Synthetic cone centered at 25.0°N, 85.0°E
    y_grid, x_grid = np.ogrid[:nlat, :nlon]
    i_c = int(round((38.0 - 25.0) / 0.25))
    j_c = int(round((85.0 - 66.0) / 0.25))
    dist = np.hypot(y_grid - i_c, x_grid - j_c)
    gfs_data = 2500.0 * np.exp(-0.5 * (dist / 10.0) ** 2).astype(np.float32)

    resampled = resample_gfs_to_grid(gfs_data, lats, lons, target_grid=grid)

    assert resampled.shape == (grid.nlat, grid.nlon)
    assert resampled.dtype == np.float32
    assert not np.isnan(resampled).any()
    # Peak must be preserved near 2500 J/kg
    assert np.isclose(float(np.max(resampled)), 2500.0, rtol=0.05)


# =============================================================================
# 5. GFS Provider Ingestion and QC Validation
# =============================================================================

def test_gfs_provider_ingest_and_qc(tmp_dir, settings):
    """Verify GfsNomadsProvider parses GRIB2 files, extracts 4 indices, and passes QC."""
    t0 = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    grib_path = tmp_dir / "test_gfs.grb2"
    create_mock_gfs_grib2(
        grib_path,
        timestamp=t0,
        cape_peak=3200.0,
        cin_peak=25.0,
        shear_peak=28.0,
        rh_peak=82.0,
    )

    provider = GfsNomadsProvider(settings)
    frame = provider.ingest_file(grib_path, timestamp=t0)

    assert frame.meta.modality == Modality.MODEL
    assert frame.meta.variable == "cape_jkg"
    assert provider.health().status == DataMode.REPLAY

    # Retrieve history frames
    history = provider.get_history(t0, minutes=60)
    assert len(history) == 4  # cape_jkg, cin_jkg, shear_0_6km_ms, rh_700hpa_pct
    vars_found = {f.meta.variable for f in history}
    assert vars_found == {"cape_jkg", "cin_jkg", "shear_0_6km_ms", "rh_700hpa_pct"}

    # Verify physical ranges against QC rules
    for f in history:
        assert f.field is not None
        assert not np.isnan(f.field).any()
        if f.meta.variable == "cape_jkg":
            assert 0.0 <= np.min(f.field) and np.max(f.field) <= 7500.0
        elif f.meta.variable == "cin_jkg":
            assert 0.0 <= np.min(f.field) and np.max(f.field) <= 2000.0
        elif f.meta.variable == "shear_0_6km_ms":
            assert 0.0 <= np.min(f.field) and np.max(f.field) <= 120.0
        elif f.meta.variable == "rh_700hpa_pct":
            assert 0.0 <= np.min(f.field) and np.max(f.field) <= 100.0


# =============================================================================
# 6. Feature Matrix Population (16 Features without NaNs)
# =============================================================================

def test_feature_matrix_populates_16_features_without_nans(tmp_dir, settings):
    """Verify build_features populates all 16 features without NaNs when NWP is healthy."""
    t0 = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    grid = make_india_grid()

    # Create mock NWP provider
    grib_path = tmp_dir / "gfs_feats.grb2"
    create_mock_gfs_grib2(grib_path, timestamp=t0, cape_peak=2800.0, cin_peak=35.0)
    provider = GfsNomadsProvider(settings)
    provider.ingest_file(grib_path, timestamp=t0)
    model_frames = provider.get_history(t0, 60)

    # Setup storm cell in Gangetic plain
    cell = Cell(
        id="CELL_001",
        time=t0,
        centroid_lat=25.5,
        centroid_lon=85.0,
        area_px=150,
        max_intensity=52.0,
        mean_intensity=40.0,
        bbox=(84.5, 25.0, 85.5, 26.0),
    )
    tracker = CellTracker(grid, settings.cells, cycle_minutes=10)
    tracker.step(t0, np.zeros((grid.nlat, grid.nlon), dtype=np.float32))

    # Build features with NWP frames
    df = build_features(
        t=t0,
        cells=[cell],
        tracker=tracker,
        radar_frames=[],
        satellite_frames=[],
        lightning_frames=[],
        flash_radius_km=12.0,
        grid=grid,
        model_frames=model_frames,
    )

    assert len(df) == 1
    # Check that all 16 features exist
    for col in FEATURE_NAMES:
        assert col in df.columns, f"Missing feature {col}"

    # Verify that the 4 NWP features are not NaN
    assert not np.isnan(df["cape_jkg"].iloc[0])
    assert not np.isnan(df["cin_jkg"].iloc[0])
    assert not np.isnan(df["shear_0_6km_ms"].iloc[0])
    assert not np.isnan(df["rh_700hpa_pct"].iloc[0])

    # Check that values reflect convective environment
    assert df["cape_jkg"].iloc[0] > 1000.0
    assert df["cin_jkg"].iloc[0] < 100.0
    assert df["shear_0_6km_ms"].iloc[0] > 10.0


# =============================================================================
# 7. Pipeline Cycle and Router Fallback Routing
# =============================================================================

def test_pipeline_cycle_with_nwp_and_fallback(tmp_dir, settings):
    """Verify that NowcastPipeline includes NWP when present, and executes fallback when missing."""
    t0 = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    grid = make_india_grid()

    # Create synthetic radar frame with storm
    refl = np.zeros((grid.nlat, grid.nlon), dtype=np.float32)
    i_c, j_c = int(round((grid.lat0 - 25.5) / grid.dlat)), int(round((85.0 - grid.lon0) / grid.dlon))
    refl[max(0, i_c - 10):min(grid.nlat, i_c + 10), max(0, j_c - 10):min(grid.nlon, j_c + 10)] = 55.0

    meta_grid = GridMeta(name=grid.name, lat0=grid.lat0, lon0=grid.lon0,
                         dlat=grid.dlat, dlon=grid.dlon, nlat=grid.nlat, nlon=grid.nlon,
                         geolocation="exact")
    meta_radar = ObsFrameMeta(source="test_radar", modality=Modality.RADAR, variable="reflectivity",
                              units="dBZ", time=t0, grid=meta_grid, quality=QualityInfo(status=QualityStatus.OK),
                              mode=DataMode.REPLAY)
    radar_frame = ObsFrame(meta=meta_radar, field=refl)

    # Ingest GFS NWP
    grib_path = tmp_dir / "pipe_gfs.grb2"
    create_mock_gfs_grib2(grib_path, timestamp=t0, cape_peak=3000.0)
    gfs_provider = GfsNomadsProvider(settings)
    gfs_provider.ingest_file(grib_path, timestamp=t0)

    class MockRadarProvider:
        def get_history(self, t, minutes):
            return [radar_frame]

    router = ModelRouter(
        fusion=None,
        physics=AdvectionModel(vil_threshold=settings.cells.vil_threshold),
        persistence=PersistenceModel(),
        climatology=ClimatologyModel(),
    )

    # Case A: Pipeline with NWP present
    sources_with_nwp = {
        Modality.RADAR: MockRadarProvider(),
        Modality.MODEL: gfs_provider,
    }
    pipe_with_nwp = NowcastPipeline(settings, sources=sources_with_nwp, router=router, model_version="test-phase5")
    fc_with_nwp, _ = pipe_with_nwp.run_cycle(t0, event_id="TEST_NWP_ON", mode=DataMode.REPLAY)

    assert Modality.MODEL in fc_with_nwp.modalities_used
    assert fc_with_nwp.data_quality["model"] == "OK"
    assert len(fc_with_nwp.steps) > 0

    # Case B: Pipeline without NWP (missing / delayed)
    empty_gfs = GfsNomadsProvider(settings)  # no files ingested
    sources_without_nwp = {
        Modality.RADAR: MockRadarProvider(),
        Modality.MODEL: empty_gfs,
    }
    pipe_without_nwp = NowcastPipeline(settings, sources=sources_without_nwp, router=router, model_version="test-phase5")
    fc_without_nwp, _ = pipe_without_nwp.run_cycle(t0, event_id="TEST_NWP_OFF", mode=DataMode.REPLAY)

    assert Modality.MODEL not in fc_without_nwp.modalities_used
    assert fc_without_nwp.data_quality["model"] == "MISSING"
    assert any("NWP" in n or "reduced-modality" in n for n in fc_without_nwp.notes)


# =============================================================================
# 8. REST API Endpoints for NWP
# =============================================================================

def test_nwp_api_endpoints(settings, tmp_dir):
    """Verify REST API status and indices endpoints for NOAA GFS NWP."""
    app = create_app(settings)
    client = TestClient(app)

    # 1. GFS Status endpoint
    r_status = client.get("/api/v1/nwp/gfs/status")
    assert r_status.status_code == 200
    data_status = r_status.json()
    assert data_status["source"] == "gfs_nomads"
    assert data_status["modality"] == "model"
    assert "variables" in data_status
    assert set(data_status["variables"]) == {"cape_jkg", "cin_jkg", "shear_0_6km_ms", "rh_700hpa_pct"}

    # 2. GFS Indices endpoint (initial state before ingestion)
    r_indices = client.get("/api/v1/nwp/gfs/indices")
    assert r_indices.status_code == 200
    data_indices = r_indices.json()
    assert "available" in data_indices
