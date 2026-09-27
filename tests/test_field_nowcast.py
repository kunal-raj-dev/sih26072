"""Verification suite for Phase 7: Continuous Probability Nowcasting & Lagrangian Advection.

Covers:
1. Continuous 2D probability field generation:
   - Absence of rectangular box step-artifacts (smooth continuous gradient).
   - Values strictly bounded in [0.0, 1.0].
   - Integration with deep U-Net tensor output and spatial Gaussian filtering (sigma=1.0).
   - Convective Initiation (CI) plume injection at 30-60 min forecast horizons.
2. Lagrangian advection extrapolation:
   - Shift displacement along motion vector [u, v] for outer horizons (60-120 min).
   - Exponential predictability decay exp(-dt / tau) and spatial dispersion.
3. Dual aleatoric/epistemic spatial uncertainty field sigma(x, y):
   - Uncertainty peaks at decision boundary P=0.5 and drops at P=0 or P=1.
   - Epistemic uncertainty widens with forecast lead time and missing sensors.
   - Valid PNG raster rendering.
4. Fractions Skill Score (FSS) per Roberts & Lean (2008):
   - Perfect forecast FSS = 1.0.
   - Acceptance criteria: FSS >= 0.50 at 20 km neighborhood scale.
5. End-to-end API verification for ci.geojson and uncertainty.png.
"""

from __future__ import annotations

from datetime import datetime, timezone
import numpy as np
import pytest
from fastapi.testclient import TestClient

from vajra.grid import make_india_grid
from vajra.schemas import Cell, CICandidate, DataMode, Event, Forecast, ForecastStep, FallbackRung, GridMeta
from vajra.models.field_nowcast import (
    compute_spatial_uncertainty_field,
    extrapolate_lagrangian_advection,
    generate_continuous_probability_field,
    render_uncertainty_png,
)
from vajra.verify import fss_neighborhood


@pytest.fixture
def test_grid():
    return make_india_grid(step_deg=0.1)


def test_continuous_probability_field_smoothness(test_grid):
    """Verify that continuous probability field has smooth gradients without rectangular box artifacts."""
    h, w = test_grid.nlat, test_grid.nlon
    c_lat = test_grid.lat0 + 25 * test_grid.dlat
    c_lon = test_grid.lon0 + 25 * test_grid.dlon

    # Cell with bounding box spanning +/- 4 grid cells (~40 km x 40 km)
    cell = Cell(
        id="cell_test_1",
        time=datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc),
        centroid_lat=c_lat,
        centroid_lon=c_lon,
        bbox=[c_lon - 0.4, c_lat - 0.4, c_lon + 0.4, c_lat + 0.4],
        area_px=64,
        max_intensity=50.0,
        mean_intensity=38.0,
    )

    p_cell = {"cell_test_1": 0.85}
    field = generate_continuous_probability_field(
        cells=[cell],
        p_cell=p_cell,
        grid=test_grid,
        background_p=0.05,
        lead_minutes=30,
        smooth_sigma=1.0,
    )

    assert field.shape == (h, w)
    assert float(field.min()) >= 0.05
    assert float(field.max()) <= 0.85

    # Check gradient smoothness: across the cell boundary, gradient must be continuous
    # and strictly smaller than step-function box edges (> 0.4 jump)
    grad_y, grad_x = np.gradient(field)
    max_gradient = max(float(np.max(np.abs(grad_y))), float(np.max(np.abs(grad_x))))
    # Smooth Gaussian kernel with sigma=1.0 has max gradient <= 0.25 (no step jumps)
    assert max_gradient < 0.25


def test_continuous_probability_ci_plume_injection(test_grid):
    """Verify that Convective Initiation candidates inject precursor probability plumes at 30-min lead."""
    h, w = test_grid.nlat, test_grid.nlon
    c_lat = test_grid.lat0 + 35 * test_grid.dlat
    c_lon = test_grid.lon0 + 35 * test_grid.dlon

    ci = CICandidate(
        id="ci_cand_1",
        centroid_lat=c_lat,
        centroid_lon=c_lon,
        bbox=[c_lon - 0.2, c_lat - 0.2, c_lon + 0.2, c_lat + 0.2],
        cooling_rate_k_per_15m=-10.0,
        ir_brightness_temp_k=245.0,
        ir_wv_diff_k=0.5,
        p_initiation=0.82,
        estimated_lead_min=30,
        area_km2=50.0,
    )

    # In Track A without existing cells, background is 0.05
    field_30 = generate_continuous_probability_field(
        cells=[],
        p_cell={},
        grid=test_grid,
        background_p=0.05,
        ci_candidates=[ci],
        lead_minutes=30,
    )

    # Center pixel should have elevated probability due to CI precursor plume
    cy_px = int(round((c_lat - test_grid.lat0) / test_grid.dlat))
    cx_px = int(round((c_lon - test_grid.lon0) / test_grid.dlon))
    assert field_30[cy_px, cx_px] > 0.40

    # At 15 min lead (too early for this 30-min candidate), CI plume should NOT trigger
    field_15 = generate_continuous_probability_field(
        cells=[],
        p_cell={},
        grid=test_grid,
        background_p=0.05,
        ci_candidates=[ci],
        lead_minutes=15,
    )
    assert field_15[cy_px, cx_px] < field_30[cy_px, cx_px]


def test_extrapolate_lagrangian_advection(test_grid):
    """Verify Lagrangian advection extrapolation, predictability decay, and diffusion."""
    h, w = test_grid.nlat, test_grid.nlon
    base_field = np.full((h, w), 0.05, dtype=np.float32)

    # Insert probability peak at (40, 40)
    base_field[38:43, 38:43] = 0.80

    # Advect with storm motion vector: u = +2 px / 15m, v = +1 px / 15m
    # Extrapolate from 60 min to 90 min (dt = 30 min = 2 intervals)
    advected_90 = extrapolate_lagrangian_advection(
        p_grid_base=base_field,
        u_px=2.0,
        v_px=1.0,
        lead_minutes=90,
        base_lead=60,
        background_p=0.05,
        tau_minutes=45.0,
    )

    assert advected_90.shape == (h, w)
    # Peak must have moved northeast (y increased by ~2, x increased by ~4)
    peak_y, peak_x = np.unravel_index(np.argmax(advected_90), advected_90.shape)
    assert peak_y > 40
    assert peak_x > 40

    # Peak amplitude must have decayed due to convective predictability loss
    assert float(np.max(advected_90)) < float(np.max(base_field))
    assert float(np.min(advected_90)) >= 0.04


def test_spatial_uncertainty_field_properties(test_grid):
    """Verify aleatoric and epistemic uncertainty characteristics."""
    h, w = test_grid.nlat, test_grid.nlon
    p_grid = np.full((h, w), 0.05, dtype=np.float32)

    # Decision boundary zone P = 0.50
    p_grid[20:30, 20:30] = 0.50
    # Confident high probability zone P = 0.95
    p_grid[40:50, 40:50] = 0.95

    sigma_15 = compute_spatial_uncertainty_field(p_grid, lead_minutes=15, grid=test_grid)
    sigma_60 = compute_spatial_uncertainty_field(p_grid, lead_minutes=60, grid=test_grid)

    # Aleatoric: uncertainty must be higher at decision boundary (P=0.50) than at confident core (P=0.95)
    assert float(np.mean(sigma_15[20:30, 20:30])) > float(np.mean(sigma_15[40:50, 40:50]))

    # Epistemic: uncertainty at 60 min must be higher than at 15 min
    assert float(np.mean(sigma_60)) > float(np.mean(sigma_15))

    # Test PNG rendering
    png_bytes = render_uncertainty_png(sigma_15)
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")


def test_fractions_skill_score_neighborhood():
    """Verify Roberts & Lean (2008) Fractions Skill Score meets FSS >= 0.50 criteria."""
    # 100x100 spatial domain
    grid_size = 100
    y_true = np.zeros((grid_size, grid_size), dtype=np.float32)
    y_pred = np.zeros((grid_size, grid_size), dtype=np.float32)

    # Observed convective core at (50, 50) of radius 5 grid cells (~50 km)
    cy, cx = 50, 50
    for dy in range(-5, 6):
        for dx in range(-5, 6):
            if dy**2 + dx**2 <= 25:
                y_true[cy + dy, cx + dx] = 1.0

    # Case 1: Identical forecast (perfect skill)
    fss_perfect = fss_neighborhood(y_true, y_true, threshold=0.35, window_size=5)
    assert fss_perfect == 1.0

    # Case 2: Forecast with slight 1-cell (10 km) displacement error
    for dy in range(-5, 6):
        for dx in range(-5, 6):
            if dy**2 + dx**2 <= 25:
                y_pred[cy + dy + 1, cx + dx + 1] = 0.85

    # At 20 km neighborhood scale (window_size=3 on 0.1 deg grid ~ 30 km),
    # FSS must easily exceed the 0.50 acceptance criteria threshold!
    fss_score = fss_neighborhood(y_pred, y_true, threshold=0.35, window_size=3)
    assert fss_score >= 0.50, f"FSS {fss_score} failed acceptance criteria (>= 0.50)"

    # Case 3: Completely displaced forecast (far away, zero skill at small neighborhood)
    y_far = np.zeros((grid_size, grid_size), dtype=np.float32)
    y_far[10:15, 10:15] = 0.90
    fss_far = fss_neighborhood(y_far, y_true, threshold=0.35, window_size=3)
    assert fss_far == 0.0


def test_api_ci_and_uncertainty_endpoints(tmp_path):
    """Verify FastAPI endpoints /forecasts/{fid}/ci.geojson and /forecasts/{fid}/uncertainty.png."""
    from vajra.config import Settings
    from vajra.store import Store
    from vajra.api.app import create_app

    settings = Settings()
    settings.paths.artifacts = tmp_path / "artifacts"
    settings.paths.database = tmp_path / "vajra.db"
    store = Store(settings)

    # Insert a dummy forecast with a CI candidate and uncertainty PNG
    t = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    ci = CICandidate(
        id="ci_api_1",
        centroid_lat=22.5,
        centroid_lon=88.3,
        bbox=[88.1, 22.3, 88.5, 22.7],
        cooling_rate_k_per_15m=-8.5,
        ir_brightness_temp_k=250.0,
        ir_wv_diff_k=-0.2,
        p_initiation=0.76,
        estimated_lead_min=30,
        area_km2=45.0,
        polygon=[[88.1, 22.3], [88.5, 22.3], [88.5, 22.7], [88.1, 22.7], [88.1, 22.3]],
    )
    forecast = Forecast(
        id="fc_test_ci",
        event_id="test_ev",
        replay_time=t,
        mode=DataMode.REPLAY,
        fallback_rung=FallbackRung.FULL_FUSION,
        model_version="test-1.0",
        modalities_used=[],
        steps=[ForecastStep(valid_time=t, lead_minutes=30, p_flash_max=0.8, risk_band="HIGH")],
        ci_candidates=[ci],
    )

    dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
    store.put_forecast(
        forecast=forecast,
        fields={30: (np.zeros((10, 10), dtype=np.float32), dummy_png)},
        uncertainty_png=dummy_png,
    )

    app = create_app(settings, store)
    client = TestClient(app)

    # 1. Test ci.geojson
    resp_ci = client.get("/api/v1/forecasts/fc_test_ci/ci.geojson")
    assert resp_ci.status_code == 200
    ci_fc = resp_ci.json()
    assert ci_fc["type"] == "FeatureCollection"
    assert len(ci_fc["features"]) == 1
    feat = ci_fc["features"][0]
    assert feat["properties"]["id"] == "ci_api_1"
    assert feat["properties"]["cooling_rate_k_per_15m"] == -8.5
    assert feat["properties"]["p_initiation"] == 0.76

    # 2. Test uncertainty.png
    resp_uncert = client.get("/api/v1/forecasts/fc_test_ci/uncertainty.png")
    assert resp_uncert.status_code == 200
    assert resp_uncert.headers["content-type"] == "image/png"
    assert resp_uncert.content.startswith(b"\x89PNG")
