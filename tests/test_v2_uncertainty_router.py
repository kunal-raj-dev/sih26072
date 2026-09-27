"""Verification suite for Phase V2-6:
Uncertainty Quantification, Isotonic Calibration (PAVA) & Adaptive Fallback Router 2.0.

Covers:
- TASK-V2-6.1:
  - Three-Tier Uncertainty Quantification:
    * Tier 1 (Hazard Probability): Calibrated P in [0.0, 1.0].
    * Tier 2 (Aleatoric Spatial Spread): Variance sigma^2 = P*(1 - P)*(1 + dt / 60) maximized at P=0.5.
    * Tier 3 (Epistemic Sensor Confidence): Deterministic index [0.05, 0.90] reflecting degradation.
- TASK-V2-6.2:
  - Pure-NumPy PAVA Isotonic calibration monotonicity: PAVA(p1) <= PAVA(p2) for all p1 <= p2.
  - Piecewise linear interpolation vs step mapping.
  - Calibration diagnostics: slope ~ 1.0, intercept ~ 0.0, low ECE.
- TASK-V2-6.3:
  - Adaptive 5-Rung Fallback Ladder:
    * Rung 1: FULL_MULTIMODAL (Radar + Sat + NWP + Ltg all healthy)
    * Rung 2: REDUCED_MODALITY (Radar offline, Satellite active)
    * Rung 3: SATELLITE_SURFACE (Radar/NWP delayed, INSAT/IMERG active)
    * Rung 4: KINEMATIC_PERSISTENCE (Cell advection)
    * Rung 5: CLIMATOLOGY (Zero observations / background only)
  - Router decision latency SLA: < 5.0 ms per cycle.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import numpy as np
import pytest

from vajra.grid import india_grid
from vajra.models.base import CycleContext, ModelOutput, NowcastModel
from vajra.models.calibration import (
    apply_isotonic,
    compute_calibration_diagnostics,
    fit_isotonic,
)
from vajra.models.field_nowcast import (
    ThreeTierUncertainty,
    compute_three_tier_uncertainty,
)
from vajra.models.router import ModelRouter, RoutedForecast
from vajra.schemas import Cell, FallbackRung, Modality


# =============================================================================
# 1. TASK-V2-6.1: Three-Tier Uncertainty Quantification
# =============================================================================

def test_three_tier_uncertainty_decomposition():
    """Verify three-tier uncertainty decomposition into hazard, aleatoric, and epistemic components."""
    grid = india_grid(0.25)
    h, w = grid.nlat, grid.nlon
    p_grid = np.full((h, w), 0.05, dtype=np.float32)

    # Core zone (confident high probability P = 0.90)
    p_grid[20:30, 20:30] = 0.90
    # Ambiguous decision boundary zone (P = 0.50)
    p_grid[35:45, 35:45] = 0.50

    unc_15 = compute_three_tier_uncertainty(
        p_grid=p_grid,
        lead_minutes=15,
        grid=grid,
        radar_available=True,
    )

    assert isinstance(unc_15, ThreeTierUncertainty)
    # Tier 1: Hazard Probability
    assert unc_15.p_hazard.shape == (h, w)
    assert float(np.min(unc_15.p_hazard)) >= 0.0
    assert float(np.max(unc_15.p_hazard)) <= 1.0

    # Tier 2: Aleatoric Spatial Spread
    # Maximized at decision boundary P = 0.50, lower at confident core P = 0.90
    aleatoric_boundary = float(np.mean(unc_15.sigma_aleatoric[35:45, 35:45]))
    aleatoric_core = float(np.mean(unc_15.sigma_aleatoric[20:30, 20:30]))
    assert aleatoric_boundary > aleatoric_core

    # Tier 2 expansion with lead time: sigma^2 = P*(1-P)*(1 + dt/60)
    unc_60 = compute_three_tier_uncertainty(
        p_grid=p_grid,
        lead_minutes=60,
        grid=grid,
        radar_available=True,
    )
    aleatoric_60 = float(np.mean(unc_60.sigma_aleatoric[35:45, 35:45]))
    assert aleatoric_60 > aleatoric_boundary

    # Tier 3: Epistemic Sensor Confidence
    # High confidence when all modalities healthy
    assert 0.70 <= unc_15.sensor_confidence <= 0.90

    # Degraded sensor confidence when radar is missing and QC suspects exist
    unc_degraded = compute_three_tier_uncertainty(
        p_grid=p_grid,
        lead_minutes=15,
        grid=grid,
        missing_modalities=["radar", "model"],
        radar_available=False,
        qc_suspect_count=2,
    )
    assert unc_degraded.sensor_confidence < unc_15.sensor_confidence
    assert unc_degraded.sensor_confidence >= 0.05


# =============================================================================
# 2. TASK-V2-6.2: Post-Hoc Isotonic Probability Calibration (PAVA)
# =============================================================================

def test_isotonic_pava_strict_monotonicity():
    """Verify strict monotonicity PAVA(p1) <= PAVA(p2) for all p1 <= p2."""
    rng = np.random.default_rng(42)
    n = 500
    raw_scores = rng.uniform(0.0, 1.0, size=n)
    # Binary outcomes conditioned on underlying true curve
    true_prob = 1.0 / (1.0 + np.exp(-5.0 * (raw_scores - 0.5)))
    y = (rng.uniform(0.0, 1.0, size=n) < true_prob).astype(float)

    mapping = fit_isotonic(raw_scores, y)

    # Dense test grid
    eval_grid = np.linspace(0.0, 1.0, 1000)
    calibrated = apply_isotonic(mapping, eval_grid, method="linear")

    # Strictly non-decreasing
    diffs = np.diff(calibrated)
    assert np.all(diffs >= -1e-12), f"Violated monotonicity: min diff = {np.min(diffs)}"
    assert calibrated[0] <= calibrated[-1]
    assert 0.0 <= calibrated[0] <= 1.0
    assert 0.0 <= calibrated[-1] <= 1.0


def test_isotonic_calibration_reliability_diagnostics():
    """Verify calibrated forecast reliability curve has slope near 1.0 and intercept near 0.0."""
    rng = np.random.default_rng(123)
    n = 1000
    raw = rng.uniform(0.0, 1.0, size=n)
    # Non-linear distortion: raw = p^0.5 (overconfident)
    p_true = raw ** 2
    y = (rng.uniform(0.0, 1.0, size=n) < p_true).astype(float)

    mapping = fit_isotonic(raw, y)
    calibrated = apply_isotonic(mapping, raw, method="linear")

    diag = compute_calibration_diagnostics(calibrated, y, n_bins=10)

    # Reliability line: slope near 1.0, intercept near 0.0
    assert abs(diag["slope"] - 1.0) < 0.20, f"Slope {diag['slope']} not near 1.0"
    assert abs(diag["intercept"]) < 0.15, f"Intercept {diag['intercept']} not near 0.0"
    assert diag["ece"] < 0.08, f"Expected Calibration Error {diag['ece']} too high"


def test_apply_isotonic_linear_vs_step():
    """Verify linear interpolation yields smooth continuous curves compared to step."""
    mapping = {
        "thresholds": [0.1, 0.4, 0.7, 0.9],
        "values": [0.05, 0.35, 0.65, 0.95],
    }
    x_eval = np.array([0.25, 0.55, 0.80])
    lin_out = apply_isotonic(mapping, x_eval, method="linear")
    step_out = apply_isotonic(mapping, x_eval, method="step")

    # Linear interpolation at midpoint x=0.25 (between 0.1 and 0.4, vals 0.05 and 0.35):
    # Expected: 0.05 + (0.15 / 0.30) * 0.30 = 0.20
    assert lin_out[0] == pytest.approx(0.20, abs=1e-3)
    # Both satisfy bounds
    assert np.all(lin_out >= 0.0) and np.all(lin_out <= 1.0)
    assert np.all(step_out >= 0.0) and np.all(step_out <= 1.0)


# =============================================================================
# 3. TASK-V2-6.3: Five-Rung Fallback Router 2.0 & Latency SLA
# =============================================================================

class MockNowcastModel(NowcastModel):
    def __init__(self, name: str, version: str = "v1", is_available: bool = True):
        self.name = name
        self.version = version
        self.is_available = is_available

    def available(self, ctx: CycleContext) -> bool:
        return self.is_available

    def predict(self, ctx: CycleContext, lead_minutes: int) -> ModelOutput:
        return ModelOutput(p_cell={"C1": 0.5}, background_p=0.05)


def make_context(modalities: dict[str, bool], has_cells: bool = True) -> CycleContext:
    cells = [
        Cell(
            id="C1", time=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            centroid_lat=20.0, centroid_lon=80.0,
            bbox=[79.8, 19.8, 80.2, 20.2], area_px=10, max_intensity=45.0, mean_intensity=38.0,
        )
    ] if has_cells else []
    return CycleContext(
        t=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        grid=india_grid(0.25),
        cells=cells,
        radar_frames=[], satellite_frames=[], lightning_frames=[],
        surface_frames=[], model_frames=[],
        features=None,
        modalities_available=modalities,
    )


def test_fallback_router_5_rungs():
    """Verify that Fallback Router 2.0 operationalizes all 5 rungs correctly."""
    unet = MockNowcastModel("unet", "unet-v2")
    fusion = MockNowcastModel("gbdt", "gbdt-v2")
    physics = MockNowcastModel("advection", "adv-v1")
    persistence = MockNowcastModel("persistence", "pers-v1")
    climatology = MockNowcastModel("climatology", "clim-v1")

    router = ModelRouter(
        fusion=fusion,
        physics=physics,
        persistence=persistence,
        climatology=climatology,
        unet=unet,
    )

    # Rung 1: FULL_MULTIMODAL (Radar, Sat, NWP, Ltg healthy)
    ctx1 = make_context({"radar": True, "satellite": True, "lightning": True, "model": True})
    m1, rung1 = router.route(ctx1)
    assert m1.name == "unet"
    assert rung1 in (FallbackRung.FULL_MULTIMODAL, FallbackRung.FULL_FUSION)

    # Rung 2: REDUCED_MODALITY (Radar offline, Satellite active)
    ctx2 = make_context({"radar": False, "satellite": True, "lightning": True, "model": True})
    m2, rung2 = router.route(ctx2)
    assert m2.name == "unet"
    assert rung2 == FallbackRung.REDUCED_MODALITY

    # Rung 3: SATELLITE_SURFACE (U-Net offline, Radar/NWP offline, INSAT/IMERG active)
    router_no_unet = ModelRouter(
        fusion=fusion, physics=physics, persistence=persistence, climatology=climatology, unet=None
    )
    ctx3 = make_context({"radar": False, "satellite": True, "surface": True, "model": False, "lightning": True})
    m3, rung3 = router_no_unet.route(ctx3)
    assert m3.name == "gbdt"
    assert rung3 in (FallbackRung.SATELLITE_SURFACE, FallbackRung.REDUCED_MODALITY)

    # Rung 4: KINEMATIC_PERSISTENCE (ML models offline, cell advection active)
    router_physics_only = ModelRouter(
        fusion=None, physics=physics, persistence=persistence, climatology=climatology, unet=None
    )
    ctx4 = make_context({"radar": False, "satellite": False, "lightning": False}, has_cells=True)
    m4, rung4 = router_physics_only.route(ctx4)
    assert m4.name == "advection"
    assert rung4 in (FallbackRung.KINEMATIC_PERSISTENCE, FallbackRung.PERSISTENCE)

    # Rung 5: CLIMATOLOGY (Zero observations or background only)
    ctx5 = make_context({"radar": False, "satellite": False, "lightning": False}, has_cells=False)
    m5, rung5 = router_physics_only.route(ctx5)
    assert m5.name == "climatology"
    assert rung5 == FallbackRung.CLIMATOLOGY


def test_fallback_router_latency_sla():
    """Verify that ModelRouter routing decision latency strictly satisfies < 5ms SLA."""
    unet = MockNowcastModel("unet", "unet-v2")
    fusion = MockNowcastModel("gbdt", "gbdt-v2")
    physics = MockNowcastModel("advection", "adv-v1")
    persistence = MockNowcastModel("persistence", "pers-v1")
    climatology = MockNowcastModel("climatology", "clim-v1")

    router = ModelRouter(
        fusion=fusion, physics=physics, persistence=persistence, climatology=climatology, unet=unet
    )

    ctx = make_context({"radar": True, "satellite": True, "lightning": True, "model": True})

    # Warmup
    _ = router.route(ctx)

    # Run 100 consecutive routing decisions
    latencies_ms = []
    for _ in range(100):
        t0 = time.perf_counter()
        _ = router.route(ctx)
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    max_lat = max(latencies_ms)
    mean_lat = float(np.mean(latencies_ms))

    # Strict SLA: < 5.0 ms
    assert max_lat < 5.0, f"Max routing latency {max_lat:.3f}ms exceeded 5ms SLA"
    assert mean_lat < 1.0, f"Mean routing latency {mean_lat:.3f}ms exceeded 1ms"
