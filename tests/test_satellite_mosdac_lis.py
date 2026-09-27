"""Verification test suite for Phase 4: MOSDAC INSAT-3D/3DR Satellite & NASA ISS LIS Ingestion.

Acceptance Criteria:
1. MosdacProvider successfully extracts Indian window and calibrates IR brightness temperatures (Planck/LUT).
2. Cloud-top cooling rates (<-4 K / 15 min) correctly flag rapidly developing convective clouds (CI).
3. ISS LIS lightning flashes over India are parsed and verified against satellite convective cores.
4. Pipeline & API integration passes cleanly with honest health reporting.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from vajra.api.app import create_app
from vajra.config import Settings
from vajra.grid import make_india_grid
from vajra.models.baselines import AdvectionModel, ClimatologyModel, PersistenceModel
from vajra.models.router import ModelRouter
from vajra.pipeline import NowcastPipeline
from vajra.providers.lis import (
    LisProvider,
    create_mock_lis_hdf5,
    parse_lis_hdf5,
    verify_lightning_against_convective_cores,
)
from vajra.providers.mosdac import (
    MosdacProvider,
    compute_btd_ir_wv,
    compute_cooling_rate,
    counts_to_kelvin,
    create_mock_mosdac_hdf5,
    detect_convective_initiation,
    kelvin_to_radiance,
    load_processed_satellite_frame,
    radiance_to_kelvin,
    resample_to_india_grid,
    save_processed_satellite_frame,
)
from vajra.qc import validate_frame
from vajra.schemas import DataMode, Modality, ObsFrame, QualityStatus


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        yield Path(td)


@pytest.fixture
def settings(tmp_dir):
    s = Settings()
    s.paths.data_root = str(tmp_dir / "data")
    s.paths.store_dir = str(tmp_dir / "store")
    s.paths.models_dir = str(tmp_dir / "models")
    return s


# =============================================================================
# 1. Radiometry, Planck Inversion, & LUT Calibration
# =============================================================================

def test_planck_radiation_and_inversion():
    """Verify forward Planck and inverse radiance-to-Kelvin consistency across physical temperatures."""
    for channel in ("TIR1", "WV", "TIR2"):
        temps = np.array([190.0, 220.0, 250.0, 280.0, 310.0], dtype=np.float32)
        # Forward Planck: temperature -> radiance
        rad = kelvin_to_radiance(temps, channel=channel)
        assert np.all(rad > 0.0), f"Radiances for {channel} must be positive"

        # Inverse Planck without band correction to verify analytical math:
        t_inv = radiance_to_kelvin(rad, channel=channel, apply_band_correction=False)
        np.testing.assert_allclose(
            t_inv, temps, rtol=1e-3,
            err_msg=f"Inverse Planck failed round-trip for {channel}"
        )


def test_counts_to_kelvin_lut_and_linear():
    """Verify count-to-Kelvin mapping via both lookup table and linear calibration."""
    # 1. Lookup table mapping
    lut = np.linspace(180.0, 320.0, 1024, dtype=np.float32)
    counts = np.array([0, 512, 1023], dtype=np.uint16)
    k_lut = counts_to_kelvin(counts, lut=lut, channel="TIR1")
    assert k_lut[0] == pytest.approx(180.0, abs=0.5)
    assert k_lut[1] == pytest.approx(250.0, abs=1.0)
    assert k_lut[2] == pytest.approx(320.0, abs=0.5)

    # 2. Linear slope/intercept calibration
    counts_lin = np.array([100, 200, 300], dtype=np.uint16)
    k_lin = counts_to_kelvin(counts_lin, slope=0.1, intercept=5.0, channel="TIR1")
    assert np.all(k_lin >= 180.0)
    assert np.all(k_lin <= 340.0)


# =============================================================================
# 2. MOSDAC HDF5 Parsing, Grid Resampling, & Frame Storage
# =============================================================================

def test_mosdac_hdf5_parsing_and_india_window(tmp_dir, settings):
    """Acceptance Criterion 1: Verify MosdacProvider extracts Indian window and calibrates IR temperatures."""
    h5_path = tmp_dir / "3RIMG_15JUL2026_1200_L1B_STD.h5"
    t0 = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    grid = make_india_grid()

    # Generate mock MOSDAC HDF5 file with convective storm over Bihar (25.5°N, 85.2°E)
    create_mock_mosdac_hdf5(
        h5_path,
        timestamp=t0,
        grid=grid,
        convective_cores=[(25.5, 85.2, 212.0)],
        channel_counts=True,
    )

    provider = MosdacProvider(settings)
    frame, aux = provider.parse_mosdac_file(h5_path)

    assert frame.meta.modality == Modality.SATELLITE
    assert frame.meta.variable == "bt_ir107"
    assert frame.meta.units == "K"
    assert frame.field.shape == (grid.nlat, grid.nlon)
    assert "wv" in aux
    assert "btd" in aux

    # Verify physical Kelvin ranges
    assert np.nanmin(frame.field) >= 180.0
    assert np.nanmax(frame.field) <= 325.0

    # Verify cold convective core is preserved at the specified coordinates
    i_c = int((25.5 - grid.lat0) / grid.dlat)
    j_c = int((85.2 - grid.lon0) / grid.dlon)
    core_temp = frame.field[i_c, j_c]
    assert core_temp < 230.0, f"Expected deep convective core temperature < 230K, got {core_temp}K"

    # Verify QC validation passes cleanly
    validated = validate_frame(frame)
    assert validated.meta.quality.status == QualityStatus.OK


def test_processed_frame_storage(tmp_dir, settings):
    """Verify calibrated frame persistence into data/processed/insat/."""
    grid = make_india_grid()
    t0 = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    h5_path = tmp_dir / "test_insat.h5"
    create_mock_mosdac_hdf5(h5_path, timestamp=t0, grid=grid)

    provider = MosdacProvider(settings)
    frame, aux = provider.parse_mosdac_file(h5_path)

    # Persist
    npz_path = save_processed_satellite_frame(frame, target_dir=tmp_dir / "processed", auxiliary=aux)
    assert npz_path.exists()
    assert npz_path.stat().st_size > 0

    # Load back
    loaded_frame, loaded_aux = load_processed_satellite_frame(npz_path)
    assert loaded_frame.meta.time == frame.meta.time
    assert loaded_frame.meta.variable == "bt_ir107"
    np.testing.assert_allclose(loaded_frame.field, frame.field, rtol=1e-5)
    assert "wv" in loaded_aux
    np.testing.assert_allclose(loaded_aux["wv"], aux["wv"], rtol=1e-5)


# =============================================================================
# 3. Convective Initiation (CI) & Cloud-Top Cooling Rates
# =============================================================================

def test_cloud_top_cooling_rate_and_convective_initiation():
    """Acceptance Criterion 2: Cloud-top cooling rates (<-4 K / 15 min) correctly flag rapidly developing convective clouds."""
    nlat, nlon = 100, 100
    tir1_t0 = np.full((nlat, nlon), 285.0, dtype=np.float32)  # Initial mid-level warm cloud
    wv_t0 = np.full((nlat, nlon), 245.0, dtype=np.float32)

    # 15 minutes later: rapid convective updraft at index (40, 50)
    # Cloud top rapidly cools by 30 K (from 285 K down to 240 K): -30 K / 15 min!
    tir1_t1 = np.full((nlat, nlon), 285.0, dtype=np.float32)
    wv_t1 = np.full((nlat, nlon), 245.0, dtype=np.float32)

    y, x = np.ogrid[:nlat, :nlon]
    dist = np.hypot(y - 40, x - 50)
    updraft = np.exp(-0.5 * (dist / 4.0) ** 2)
    tir1_t1 = tir1_t1 - 45.0 * updraft
    wv_t1 = wv_t1 - 25.0 * updraft

    # Compute cooling rate
    cooling_rate = compute_cooling_rate(tir1_t1, tir1_t0, dt_minutes=15.0)

    # Center of updraft should exhibit rapid negative rate (<= -20 K / 15 min)
    assert cooling_rate[40, 50] < -20.0
    # Background should have zero cooling
    assert cooling_rate[0, 0] == pytest.approx(0.0, abs=0.1)

    # Detect Convective Initiation candidates
    ci_res = detect_convective_initiation(
        tir1_k=tir1_t1,
        wv_k=wv_t1,
        cooling_rate_15m=cooling_rate,
        cooling_threshold_k=-4.0,
        max_tir1_k=273.15,
        min_btd_k=-5.0,
    )

    assert ci_res["candidate_count"] > 0
    assert len(ci_res["candidates"]) == 1
    cand = ci_res["candidates"][0]
    assert cand["area_px"] >= 3
    assert cand["min_tir1_k"] <= 245.0
    assert cand["mean_cooling_rate_15m"] <= -4.0
    assert cand["ci_confidence"] >= 0.5


def test_btd_overshooting_tops():
    """Verify Brightness Temperature Difference (T_IR1 - T_WV) behavior."""
    tir1 = np.array([210.0, 240.0, 290.0], dtype=np.float32)
    wv = np.array([212.0, 245.0, 250.0], dtype=np.float32)
    btd = compute_btd_ir_wv(tir1, wv)

    # Overshooting / deep convective core: near zero or positive
    assert btd[0] == pytest.approx(-2.0, abs=0.1)
    # Clear sky / warm ground: large positive
    assert btd[2] == pytest.approx(40.0, abs=0.1)


# =============================================================================
# 4. ISS LIS Lightning Parsing & Convective Core Verification
# =============================================================================

def test_iss_lis_hdf5_parsing_and_india_filter(tmp_dir, settings):
    """Acceptance Criterion 3: Parse ISS LIS HDF5 and verify spatial filtering to India."""
    lis_file = tmp_dir / "ISS_LIS_SC_V1.0_20260715.hdf"
    t0 = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    t0_epoch = t0.timestamp()

    # Create mock flashes: 4 inside India, 2 outside India (Equator and Pacific)
    flashes = [
        (25.5, 85.2, 180.0, t0_epoch - 120),  # Bihar (India)
        (22.8, 88.4, 210.0, t0_epoch - 90),   # West Bengal (India)
        (19.0, 84.8, 140.0, t0_epoch - 60),   # Odisha (India)
        (28.6, 77.2, 160.0, t0_epoch - 30),   # Delhi (India)
        (0.5, 10.0, 190.0, t0_epoch - 50),    # Africa (Outside India)
        (-10.0, 140.0, 175.0, t0_epoch - 40), # Australia (Outside India)
    ]
    create_mock_lis_hdf5(lis_file, flashes=flashes, timestamp=t0)

    pts, meta = parse_lis_hdf5(lis_file)
    assert meta["total_raw_flashes"] == 6
    assert meta["india_flashes"] == 4
    assert len(pts) == 4
    # All extracted points must be inside India bounds
    assert np.all(pts[:, 0] >= 6.0) and np.all(pts[:, 0] <= 38.0)
    assert np.all(pts[:, 1] >= 66.0) and np.all(pts[:, 1] <= 98.0)


def test_verify_lightning_against_convective_cores(tmp_dir, settings):
    """Acceptance Criterion 3: Correlate orbital lightning flashes with satellite convective cores."""
    grid = make_india_grid()
    t0 = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)

    # 1. Create satellite frame with a deep convective storm at (25.5°N, 85.2°E)
    h5_sat = tmp_dir / "sat_core.h5"
    create_mock_mosdac_hdf5(h5_sat, timestamp=t0, grid=grid, convective_cores=[(25.5, 85.2, 210.0)])
    mosdac = MosdacProvider(settings)
    sat_frame, _ = mosdac.parse_mosdac_file(h5_sat)

    # 2. Create LIS flashes: 3 flashes inside the Bihar core, 1 isolated flash far away
    lis_file = tmp_dir / "lis_flashes.h5"
    flashes = [
        (25.51, 85.21, 220.0, t0.timestamp()),
        (25.49, 85.19, 190.0, t0.timestamp()),
        (25.53, 85.22, 175.0, t0.timestamp()),
        (12.0, 75.0, 110.0, t0.timestamp()),  # Far away over southern India
    ]
    create_mock_lis_hdf5(lis_file, flashes=flashes, timestamp=t0)
    lis = LisProvider(settings)
    flash_frame = lis.ingest_file(lis_file)

    # 3. Cross-verify
    res = verify_lightning_against_convective_cores(
        flashes_frame=flash_frame,
        satellite_frame=sat_frame,
        tir1_cold_threshold_k=235.0,
        search_radius_km=30.0,
    )

    assert res["total_flashes"] == 4
    assert res["co_located_flashes"] == 3
    assert res["co_location_rate"] == pytest.approx(0.75, abs=0.01)
    assert res["convective_core_pixels"] > 0
    assert res["mean_flash_energy"] > 100.0


# =============================================================================
# 5. Pipeline Integration & API Endpoints
# =============================================================================

def test_pipeline_cycle_with_mosdac_and_lis(tmp_dir, settings):
    """Verify that NowcastPipeline runs a complete cycle using MosdacProvider and LisProvider."""
    grid = make_india_grid()
    t0 = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)

    # Ingest 2 consecutive satellite frames
    h5_sat1 = tmp_dir / "sat1.h5"
    h5_sat2 = tmp_dir / "sat2.h5"
    create_mock_mosdac_hdf5(h5_sat1, timestamp=t0 - timedelta(minutes=15), grid=grid, convective_cores=[(25.5, 85.2, 240.0)])
    create_mock_mosdac_hdf5(h5_sat2, timestamp=t0, grid=grid, convective_cores=[(25.5, 85.2, 215.0)])

    mosdac = MosdacProvider(settings)
    f1, a1 = mosdac.parse_mosdac_file(h5_sat1)
    f2, a2 = mosdac.parse_mosdac_file(h5_sat2)
    mosdac.ingest_frame(f1, a1)
    mosdac.ingest_frame(f2, a2)

    # Ingest LIS flashes
    h5_lis = tmp_dir / "lis.h5"
    create_mock_lis_hdf5(h5_lis, timestamp=t0)
    lis = LisProvider(settings)
    lis.ingest_file(h5_lis)

    # Wire into NowcastPipeline sources
    sources = {
        Modality.SATELLITE: mosdac,
        Modality.LIGHTNING: lis,
    }
    router = ModelRouter(
        fusion=None,
        physics=AdvectionModel(vil_threshold=settings.cells.vil_threshold),
        persistence=PersistenceModel(),
        climatology=ClimatologyModel(),
    )
    pipeline = NowcastPipeline(settings, sources=sources, router=router, model_version="test-phase4")

    forecast, alerts = pipeline.run_cycle(t0, event_id="PHASE4_TEST", mode=DataMode.REPLAY)
    assert forecast.event_id == "PHASE4_TEST"
    assert len(forecast.steps) > 0
    assert Modality.SATELLITE in forecast.modalities_used
    assert Modality.LIGHTNING in forecast.modalities_used


def test_satellite_api_endpoints(settings, tmp_dir):
    """Verify REST API endpoints for MOSDAC and LIS data."""
    app = create_app(settings)
    client = TestClient(app)

    # 1. MOSDAC Status
    r_mosdac = client.get("/api/v1/satellite/mosdac/status")
    assert r_mosdac.status_code == 200
    data_m = r_mosdac.json()
    assert data_m["source"] == "mosdac_insat"
    assert "cache_dir" in data_m

    # 2. Convective Initiation
    r_ci = client.get("/api/v1/satellite/ci/latest")
    assert r_ci.status_code == 200
    data_ci = r_ci.json()
    assert "candidate_count" in data_ci
    assert "candidates" in data_ci

    # 3. ISS LIS Lightning
    r_lis = client.get("/api/v1/satellite/lis/latest")
    assert r_lis.status_code == 200
    data_l = r_lis.json()
    assert data_l["type"] == "FeatureCollection"
    assert "features" in data_l

    # 4. Data Health includes mosdac and lis
    r_dh = client.get("/api/v1/data-health")
    assert r_dh.status_code == 200
    dh_sources = [d["source"] for d in r_dh.json()]
    assert "mosdac_insat" in dh_sources
    assert "iss_lis" in dh_sources
