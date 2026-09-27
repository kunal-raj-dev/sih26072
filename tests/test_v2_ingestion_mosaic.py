"""Comprehensive verification test suite for Phase V2-1:
Sensor Harmonization, Multi-Radar Mosaic Engine, INSAT Radiometry & Pure-Python NWP.
"""

from __future__ import annotations

import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from vajra.config import Settings
from vajra.grid import GridSpec, make_india_grid
from vajra.providers.gfs import (
    compute_bulk_richardson_number,
    compute_bulk_wind_shear_0_6km,
    create_mock_gfs_grib2,
    decode_grib2_messages,
    encode_grib2_message,
    extract_thermodynamic_sounding,
    thermodynamic_gating_factor,
)
from vajra.providers.imerg import (
    make_imerg_highres_grid,
    regrid_imerg,
)
from vajra.providers.mosdac import (
    MosdacProvider,
    compute_btd_ir_wv,
    compute_split_window_btd,
    counts_to_kelvin,
    create_mock_mosdac_hdf5,
    kelvin_to_radiance,
    radiance_to_kelvin,
)
from vajra.providers.radar_mosaic import (
    RADAR_STATIONS,
    RadarMosaicEngine,
    RadarPolarSweep,
    polar_sweep_to_cartesian,
    simulate_synthetic_polar_sweep,
    simulate_synthetic_radar_scan,
    volume_to_maxz,
)


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        yield Path(td)


@pytest.fixture
def pilot_grid():
    """High-resolution pilot grid for Eastern India convective corridor."""
    return GridSpec(
        name="pilot_eastern_india",
        lat0=21.0,
        lon0=82.0,
        dlat=0.1,
        dlon=0.1,
        nlat=60,
        nlon=70,
        geolocation="exact",
    )


# =============================================================================
# 1. Multi-Radar Polar Sweeps, MaxZ & Cressman Composite Engine
# =============================================================================

def test_polar_sweep_to_cartesian_projection(pilot_grid):
    """Verify polar PPI sweep projection into Cartesian MaxZ volume scan."""
    patna = RADAR_STATIONS["patna"]
    cores = [(25.5, 85.1, 55.0, 15.0)]  # Severe core near Patna
    now = datetime(2026, 5, 12, 14, 0, tzinfo=timezone.utc)

    sweep_0p5 = simulate_synthetic_polar_sweep(patna, cores, elevation_deg=0.5, time=now, seed=10)
    sweep_1p5 = simulate_synthetic_polar_sweep(patna, cores, elevation_deg=1.5, time=now, seed=11)

    assert sweep_0p5.reflectivity_dbz.shape == (360, 250)
    assert np.max(sweep_0p5.reflectivity_dbz) >= 45.0

    # Project single sweep to Cartesian
    vol_0p5 = polar_sweep_to_cartesian(sweep_0p5, pilot_grid)
    assert vol_0p5.reflectivity_dbz.shape == (pilot_grid.nlat, pilot_grid.nlon)
    assert np.max(vol_0p5.reflectivity_dbz) >= 40.0
    assert vol_0p5.coverage_mask is not None

    # Column-Maximum (MaxZ) across multiple tilts
    vol_maxz = volume_to_maxz([sweep_0p5, sweep_1p5], pilot_grid)
    assert vol_maxz.reflectivity_dbz.shape == (pilot_grid.nlat, pilot_grid.nlon)
    assert np.max(vol_maxz.reflectivity_dbz) >= np.max(vol_0p5.reflectivity_dbz)


def test_multi_radar_mosaic_blending_and_seamless_boundaries(pilot_grid):
    """Verify multi-radar MaxZ and Cressman blending across Patna, Kolkata, and Ranchi."""
    patna = RADAR_STATIONS["patna"]
    kolkata = RADAR_STATIONS["kolkata"]
    ranchi = RADAR_STATIONS["ranchi"]
    now = datetime(2026, 5, 12, 14, 0, tzinfo=timezone.utc)

    # Core situated in the triangular overlap region between Patna, Ranchi, and Kolkata
    cores = [(24.0, 86.0, 52.0, 25.0)]

    scan_patna = simulate_synthetic_radar_scan(patna, pilot_grid, cores, time=now, noise_sigma=0.0)
    scan_kolkata = simulate_synthetic_radar_scan(kolkata, pilot_grid, cores, time=now, noise_sigma=0.0)
    scan_ranchi = simulate_synthetic_radar_scan(ranchi, pilot_grid, cores, time=now, noise_sigma=0.0)

    engine = RadarMosaicEngine([patna, kolkata, ranchi])

    # 1. MaxZ compositing
    maxz_field, meta_maxz = engine.composite([scan_patna, scan_kolkata, scan_ranchi], pilot_grid, method="max")
    assert maxz_field.shape == (pilot_grid.nlat, pilot_grid.nlon)
    assert meta_maxz["station_count"] == 3
    assert meta_maxz["overlap_area_km2"] > 0
    assert np.all(maxz_field >= 0.0)
    assert not np.any(np.isnan(maxz_field))
    assert not np.any(np.isinf(maxz_field))

    # 2. Cressman range-squared weighted compositing
    cress_field, meta_cress = engine.composite(
        [scan_patna, scan_kolkata, scan_ranchi],
        pilot_grid,
        method="cressman",
        cressman_radius_km=150.0,
        station_weights={"patna": 1.0, "kolkata": 1.0, "ranchi": 1.2},
    )
    assert cress_field.shape == (pilot_grid.nlat, pilot_grid.nlon)
    assert np.all(cress_field >= 0.0)
    assert not np.any(np.isnan(cress_field))

    # Boundary smoothness: gradient between adjacent pixels in overlap area must be bounded
    grad_y, grad_x = np.gradient(cress_field)
    max_gradient = float(np.max(np.hypot(grad_y, grad_x)))
    assert max_gradient < 25.0, f"Mosaic boundary discontinuity detected: max gradient {max_gradient} dBZ/pixel"


def test_radar_offline_fallback(pilot_grid):
    """Verify system gracefully falls back when one or more radars go offline."""
    patna = RADAR_STATIONS["patna"]
    ranchi = RADAR_STATIONS["ranchi"]
    now = datetime(2026, 5, 12, 14, 0, tzinfo=timezone.utc)
    cores = [(24.5, 85.5, 48.0, 20.0)]

    scan_patna = simulate_synthetic_radar_scan(patna, pilot_grid, cores, time=now)
    # Ranchi is offline; only Patna scan provided
    engine = RadarMosaicEngine([patna, ranchi])
    field, meta = engine.composite([scan_patna], pilot_grid, method="cressman")

    assert meta["stations_used"] == ["patna"]
    assert "radar_available" in meta
    assert "radar_unavailable" in meta
    # Points near Patna are available; distant points are flagged unavailable
    assert np.any(meta["radar_available"])
    assert np.any(meta["radar_unavailable"])


# =============================================================================
# 2. INSAT-3DS Radiometric Calibration & Split-Window BTD
# =============================================================================

def test_insat_planck_inversion_tolerance():
    """Verify forward and inverse Planck calibration within +/- 0.1 K tolerance across all channels."""
    channels = ("TIR1", "WV", "TIR2", "MIR")
    temps = np.linspace(200.0, 320.0, 25, dtype=np.float32)

    for ch in channels:
        # Radiance from temperature
        rad = kelvin_to_radiance(temps, channel=ch)
        assert np.all(rad > 0.0), f"Radiances for channel {ch} must be strictly positive"

        # Inverse Planck recovering temperature
        t_recovered = radiance_to_kelvin(rad, channel=ch, apply_band_correction=False)
        diff = np.abs(t_recovered - temps)
        max_diff = float(np.max(diff))
        assert max_diff <= 0.1, f"Channel {ch} inverse Planck exceeded 0.1 K tolerance (max error {max_diff:.4f} K)"


def test_insat_split_window_and_multispectral_parsing(tmp_dir):
    """Verify mock HDF5 generation, 10-bit count conversion, and split-window BTD computation."""
    settings = Settings()
    settings.paths.data_root = str(tmp_dir / "data")
    settings.paths.store_dir = str(tmp_dir / "store")
    settings.paths.models_dir = str(tmp_dir / "models")

    provider = MosdacProvider(settings)
    h5_path = tmp_dir / "mock_insat.h5"
    now = datetime(2026, 5, 12, 14, 0, tzinfo=timezone.utc)

    # Generate mock with convective cores and 10-bit counts
    create_mock_mosdac_hdf5(
        h5_path,
        timestamp=now,
        grid=provider.grid,
        convective_cores=[(25.5, 85.2, 212.0)],
        channel_counts=True,
    )

    frame, aux = provider.parse_mosdac_file(h5_path)
    assert frame.meta.modality.value == "satellite"
    assert frame.field.shape == (provider.grid.nlat, provider.grid.nlon)
    assert np.min(frame.field) <= 220.0  # Cold convective core detected

    # Verify auxiliary channels
    assert "wv" in aux
    assert "tir2" in aux
    assert "mir" in aux
    assert "split_window_btd" in aux

    # Verify split-window BTD calculation
    tir1 = frame.field
    tir2 = aux["tir2"]
    btd_split = compute_split_window_btd(tir1, tir2)
    np.testing.assert_allclose(aux["split_window_btd"], btd_split, rtol=1e-5)


# =============================================================================
# 3. Pure-Python NWP & Thermodynamic Sounding Extractor
# =============================================================================

def test_pure_python_grib2_encoder_decoder_zero_c_extension():
    """Verify GRIB2 simple-packing encoding and decoding under zero binary C extensions."""
    nlat, nlon = 30, 40
    cape_raw = np.linspace(500.0, 3500.0, nlat * nlon, dtype=np.float32).reshape((nlat, nlon))
    now = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)

    # Encode to binary GRIB2
    buf = encode_grib2_message(cape_raw, variable="CAPE", timestamp=now)
    assert buf.startswith(b"GRIB")
    assert buf.endswith(b"7777")

    # Decode from binary GRIB2
    messages = decode_grib2_messages(buf)
    assert len(messages) == 1
    msg = messages[0]
    assert msg["variable"] == "cape"
    assert msg["nlat"] == nlat
    assert msg["nlon"] == nlon

    # Decoded values match within 16-bit packing precision (<0.5 J/kg)
    np.testing.assert_allclose(msg["data"], cape_raw, atol=0.5)


def test_extract_thermodynamic_sounding_and_gating():
    """Verify extract_thermodynamic_sounding computes CAPE, CIN, shear, RH, BRN, and gating."""
    india_grid = make_india_grid()
    nlat, nlon = india_grid.nlat, india_grid.nlon

    # Favorable severe thunderstorm parameters
    cape = np.full((nlat, nlon), 2500.0, dtype=np.float32)
    cin = np.full((nlat, nlon), 25.0, dtype=np.float32)
    u_10 = np.full((nlat, nlon), 5.0, dtype=np.float32)
    v_10 = np.full((nlat, nlon), 2.0, dtype=np.float32)
    u_500 = np.full((nlat, nlon), 20.0, dtype=np.float32)
    v_500 = np.full((nlat, nlon), 15.0, dtype=np.float32)
    rh_700 = np.full((nlat, nlon), 75.0, dtype=np.float32)

    gfs_dict = {
        "cape": cape,
        "cin": cin,
        "ugrd_10m": u_10,
        "vgrd_10m": v_10,
        "ugrd_500": u_500,
        "vgrd_500": v_500,
        "rh_700": rh_700,
    }

    sounding = extract_thermodynamic_sounding(gfs_dict, target_grid=india_grid)

    assert "cape" in sounding
    assert "cin" in sounding
    assert "shear_0_6km" in sounding
    assert "rh_700" in sounding
    assert "brn" in sounding
    assert "gating_array" in sounding

    # Shear magnitude: sqrt((20-5)^2 + (15-2)^2) = sqrt(225 + 169) = sqrt(394) ~ 19.85 m/s
    expected_shear = math.sqrt((20.0 - 5.0) ** 2 + (15.0 - 2.0) ** 2)
    assert sounding["shear_0_6km"][0, 0] == pytest.approx(expected_shear, abs=0.1)

    # BRN = CAPE / (0.5 * shear^2) = 2500 / (0.5 * 394) ~ 12.69 (supercellular regime)
    assert sounding["brn"][0, 0] == pytest.approx(2500.0 / (0.5 * 394.0), abs=0.2)

    # Gating array: favorable CAPE and low CIN yield high gating factor (~1.0)
    assert sounding["gating_array"][0, 0] >= 0.95

    # Capped environment test: CIN = 350 J/kg should heavily penalize gating array
    gfs_capped = dict(gfs_dict)
    gfs_capped["cin"] = np.full((nlat, nlon), 350.0, dtype=np.float32)
    sounding_capped = extract_thermodynamic_sounding(gfs_capped, target_grid=india_grid)
    assert sounding_capped["gating_array"][0, 0] <= 0.35


# =============================================================================
# 4. NASA IMERG Half-Hourly Precipitation Regridding
# =============================================================================

def test_imerg_precipitation_regridding():
    """Verify regridding half-hourly rainfall rates to canonical 0.1° and 0.02° grids."""
    src_grid = GridSpec(
        name="imerg_src",
        lat0=6.0,
        lon0=66.0,
        dlat=0.1,
        dlon=0.1,
        nlat=50,
        nlon=50,
        geolocation="exact",
    )
    # Simulated rain rate with localized cloudburst (45 mm/hr)
    raw_rain = np.zeros((src_grid.nlat, src_grid.nlon), dtype=np.float32)
    raw_rain[20:30, 20:30] = 45.0

    # 1. Regrid to 0.1° target
    target_0p1 = GridSpec(
        name="target_0p1",
        lat0=7.0,
        lon0=67.0,
        dlat=0.1,
        dlon=0.1,
        nlat=30,
        nlon=30,
        geolocation="exact",
    )
    regridded_0p1 = regrid_imerg(raw_rain, src_grid, target_0p1)
    assert regridded_0p1.shape == (target_0p1.nlat, target_0p1.nlon)
    assert np.max(regridded_0p1) == pytest.approx(45.0, abs=1.0)
    assert np.all(regridded_0p1 >= 0.0)

    # 2. Regrid to 0.02° high-resolution target
    target_0p02 = GridSpec(
        name="target_0p02",
        lat0=8.0,
        lon0=68.0,
        dlat=0.02,
        dlon=0.02,
        nlat=50,
        nlon=50,
        geolocation="exact",
    )
    regridded_0p02 = regrid_imerg(raw_rain, src_grid, target_0p02)
    assert regridded_0p02.shape == (50, 50)
    assert np.all(regridded_0p02 >= 0.0)
    assert not np.any(np.isnan(regridded_0p02))
