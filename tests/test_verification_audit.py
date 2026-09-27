"""Verification and Historical Case Study Audit Test Suite (Phase 10 / EPIC 10).

Covers:
1. Murphy (1973) Brier score resolution, reliability loss, and uncertainty decomposition.
2. Strict reliability diagram monotonicity on calibrated probabilities.
3. Multiscale spatial Fractions Skill Score (FSS) scaling properties (Roberts & Lean 2008).
4. 5-Baseline comparison matrix invariants and superiority proofs.
5. Packaging, validation, and bundle integrity of all 6 historical case studies.
6. Automated background forecast settlement engine (matured observation matching).
7. Scoreboard API endpoint (/api/v1/runs/{run_id}/scoreboard).
8. CLI case study runner script execution.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from starlette.testclient import TestClient

from vajra.case_studies import (
    export_case_study_bundles,
    get_case_study,
    list_case_studies,
)
from vajra.config import load_settings
from vajra.models.baselines import (
    AdvectionModel,
    ClimatologyModel,
    ImdTextBulletinModel,
    LightningJumpModel,
    NwpThresholdModel,
    PersistenceModel,
    UncalibratedGBDTModel,
)
from vajra.models.calibration import apply_isotonic, fit_isotonic
from vajra.store import Store
from vajra.verify import (
    brier_score,
    brier_skill_score,
    compute_multiscale_fss,
    compute_verification_suite,
    contingency,
    evaluate_baselines,
    fss_neighborhood,
    is_monotone_reliability,
    murphy_decomposition,
    pod_far_csi,
    reliability_curve,
    roc_auc_score,
    settle_pending_forecasts,
)


# ---------------------------------------------------------------------------
# 1. Murphy (1973) Decomposition Test
# ---------------------------------------------------------------------------
def test_murphy_decomposition_identity():
    """Verify Murphy (1973) identity: BS = Reliability - Resolution + Uncertainty."""
    rng = np.random.default_rng(2026)
    n = 1000
    p = rng.uniform(0.1, 0.9, size=n)
    y = (rng.uniform(0, 1, size=n) < p).astype(int)

    decomp = murphy_decomposition(p, y, n_bins=10)
    assert not np.isnan(decomp["brier_score"])
    assert not np.isnan(decomp["reliability"])
    assert not np.isnan(decomp["resolution"])
    assert not np.isnan(decomp["uncertainty"])

    # Identity holds within binning approximation error
    reconstructed_bs = decomp["reliability"] - decomp["resolution"] + decomp["uncertainty"]
    assert abs(reconstructed_bs - decomp["brier_score"]) < 0.05


# ---------------------------------------------------------------------------
# 2. Reliability Monotonicity Test
# ---------------------------------------------------------------------------
def test_reliability_monotonicity_on_calibrated_probabilities():
    """Verify that isotonic PAVA calibrated probabilities exhibit strict monotonicity."""
    rng = np.random.default_rng(42)
    n = 1200
    raw_scores = rng.normal(0, 1.5, size=n)
    true_probs = 1.0 / (1.0 + np.exp(-raw_scores))
    y = (rng.uniform(0, 1, size=n) < true_probs).astype(int)

    # Fit and apply isotonic regression
    calibrator = fit_isotonic(true_probs, y)
    calibrated_p = apply_isotonic(calibrator, true_probs)

    # Compute reliability curve across 5 bins
    curve = reliability_curve(calibrated_p, y, n_bins=5)
    assert is_monotone_reliability(curve) is True

    # Check that each bin has valid fields and sharpness sum equals 1.0
    total_sharpness = sum(b["sharpness"] for b in curve)
    assert abs(total_sharpness - 1.0) < 1e-5


# ---------------------------------------------------------------------------
# 3. Multiscale Fractions Skill Score (FSS) Test
# ---------------------------------------------------------------------------
def test_multiscale_fss_spatial_scaling():
    """Verify that FSS increases monotonically with spatial neighborhood scale."""
    ny, nx = 80, 80
    fc = np.zeros((ny, nx), dtype=float)
    obs = np.zeros((ny, nx), dtype=float)

    # Place a storm core in observations, and a slightly displaced forecast core (~2 pixels / 20 km away)
    obs[35:45, 35:45] = 0.8
    fc[37:47, 37:47] = 0.8

    scales = [10, 30, 50, 70]
    scores = compute_multiscale_fss(fc, obs, threshold=0.35, scales_km=scales, km_per_pixel=10.0)

    assert len(scores) == 4
    # At 10 km (pixel scale), displacement hurts score
    # At 50+ km, neighborhood encompasses both cores, so FSS approaches 1.0
    assert scores["70km"] >= scores["50km"] >= scores["30km"] >= scores["10km"]
    assert scores["70km"] > 0.85


# ---------------------------------------------------------------------------
# 4. Five Baseline Models & Comparison Matrix Test
# ---------------------------------------------------------------------------
def test_all_five_baselines_instantiation_and_scoring():
    """Verify all 5 baseline models instantiate and predict valid probabilities."""
    ctx = type("MockCtx", (), {
        "t": datetime.now(timezone.utc),
        "cells": [type("MockCell", (), {"id": "C1", "centroid_lat": 25.5, "centroid_lon": 85.1})()],
        "features": None,
        "radar_frames": [],
        "satellite_frames": [],
        "lightning_frames": [],
        "grid": None,
    })()

    # 1. Climatology / Persistence
    m1 = PersistenceModel()
    m1_climo = ClimatologyModel()
    m1_climo.fit([0, 1, 0, 0, 1])
    assert m1_climo.predict(ctx, 30).p_cell["C1"] == 0.40

    # 2. NWP Environmental Thresholding
    m2 = NwpThresholdModel()
    out2 = m2.predict(ctx, 30)
    assert "C1" in out2.p_cell
    assert 0.0 <= out2.p_cell["C1"] <= 1.0

    # 3. Lagrangian Advection
    m3 = AdvectionModel(vil_threshold=74.0)
    assert m3.name == "advection"

    # 4. Uncalibrated GBDT
    m4 = UncalibratedGBDTModel()
    out4 = m4.predict(ctx, 30)
    assert "C1" in out4.p_cell
    assert 0.0 <= out4.p_cell["C1"] <= 1.0

    # 5. Official IMD Text Bulletin
    m5 = ImdTextBulletinModel(bulletin_prob=0.65)
    out5 = m5.predict(ctx, 30)
    assert out5.p_cell["C1"] == 0.65


def test_evaluate_baselines_matrix():
    """Verify evaluate_baselines computes comparative metrics for all 6 architectures."""
    rng = np.random.default_rng(101)
    n = 200
    y = rng.choice([0, 1], size=n, p=[0.75, 0.25])

    # Well-calibrated, high-skill Vajra predictions
    p_vajra = np.where(y == 1, rng.uniform(0.6, 0.95, size=n), rng.uniform(0.02, 0.25, size=n))

    # Baseline predictions
    p_climo = np.full_like(y, float(y.mean()), dtype=float)
    p_nwp = np.where(y == 1, 0.65, 0.55)  # lots of false alarms
    p_advection = np.clip(p_vajra * 0.7 + rng.normal(0, 0.1, size=n), 0, 1)
    p_uncal = np.where(p_vajra > 0.5, 0.95, 0.05)
    p_imd = np.where(y == 1, 0.65, 0.60)  # broad district blanket warning

    matrix = evaluate_baselines(p_vajra, y, p_climo, p_nwp, p_advection, p_uncal, p_imd, threshold=0.35)

    assert "vajra" in matrix
    assert "climatology_persistence" in matrix
    assert "nwp_environmental_threshold" in matrix
    assert "lagrangian_advection" in matrix
    assert "uncalibrated_gbdt" in matrix
    assert "imd_text_bulletin" in matrix

    # Project Vajra achieves highest CSI and positive BSS
    assert matrix["vajra"]["csi"] > matrix["climatology_persistence"]["csi"]
    assert matrix["vajra"]["csi"] > matrix["imd_text_bulletin"]["csi"]
    assert matrix["vajra"]["bss"] > 0.30
    assert matrix["vajra"]["far"] < matrix["imd_text_bulletin"]["far"]


# ---------------------------------------------------------------------------
# 5. Case Study Suite Integrity & Packaging Test
# ---------------------------------------------------------------------------
def test_all_six_case_studies_exist_and_bundle():
    """Verify that all 6 case studies are defined, valid, and exported to data/events/."""
    studies = list_case_studies()
    assert len(studies) == 6

    expected_ids = {
        "bihar_squall_2026",
        "odisha_kalbaishakhi_2026",
        "andhra_coastal_cluster_2026",
        "himalayan_cloudburst_2026",
        "sevir_s810646",
        "multicell_electrification_2026",
    }
    found_ids = {cs.event_id for cs in studies}
    assert found_ids == expected_ids

    # Export bundles to test serialization
    paths = export_case_study_bundles()
    assert len(paths) == 6
    for p in paths:
        assert p.exists()
        assert p.stat().st_size > 1000
        content = json.loads(p.read_text(encoding="utf-8"))
        assert content["event_id"] in expected_ids
        assert len(content["primary_districts"]) > 0
        assert "imd_bulletin" in content
        assert "bulletin_id" in content["imd_bulletin"]
        assert len(content["baseline_expectations"]) >= 5


# ---------------------------------------------------------------------------
# 6. Automated Forecast Settlement Engine Test
# ---------------------------------------------------------------------------
def test_settle_pending_forecasts():
    """Verify settle_pending_forecasts matures forecasts against delayed lightning truth."""
    settings = load_settings()
    store = Store(settings)

    from vajra.case_studies import get_case_study, create_case_study_sources
    from vajra.api.app import _ensure_pipeline

    cs = get_case_study("bihar_squall_2026")
    state: dict = {}
    pipeline, event, sources = _ensure_pipeline(cs.event_id, settings, store, state)

    # Run 1 cycle with run_id attached
    t0 = event.time_start
    t1 = t0 + timedelta(minutes=10)
    run_id = "run_settle_test"
    forecast_0, alerts_0 = pipeline.run_cycle(t0, event.id, event.mode, run_id=run_id)
    store.put_forecast(forecast_0, {})
    store.put_alerts(alerts_0)

    # Create run record
    from vajra.schemas import InferenceRun
    run = InferenceRun(id=run_id, event_id=event.id, started_at=t0, finished_at=t1, cycles=1)
    run.forecasts.append(forecast_0.id)
    store.put_run(run)


    # Fast forward time to t0 + 65 min (past the 60m lead horizon)
    t_now = t0 + timedelta(minutes=65)
    settled = settle_pending_forecasts(store, sources, t_now)
    assert settled > 0

    verif = store.get_verification(run.id)
    assert verif is not None
    assert "samples" in verif
    assert "metrics" in verif


# ---------------------------------------------------------------------------
# 7. Verification Scoreboard API Test
# ---------------------------------------------------------------------------
def test_scoreboard_api_endpoint():
    """Verify GET /api/v1/runs/{run_id}/scoreboard returns complete audit metrics."""
    from vajra.api.app import create_app
    app = create_app()
    client = TestClient(app)

    # List events to ensure registered
    res = client.get("/api/v1/events")
    assert res.status_code == 200
    events = res.json()
    assert any(e["id"] == "bihar_squall_2026" for e in events)

    # Run replay for 2 cycles
    r = client.post("/api/v1/replay/bihar_squall_2026/run?max_cycles=3")
    assert r.status_code == 200
    run_data = r.json()
    run_id = run_data["id"]

    # Query scoreboard
    sc_res = client.get(f"/api/v1/runs/{run_id}/scoreboard")
    assert sc_res.status_code == 200
    board = sc_res.json()

    assert board["run_id"] == run_id
    assert board["event_id"] == "bihar_squall_2026"
    assert "metrics" in board
    assert "sample_counts" in board
    assert "baselines" in board
    assert "case_study" in board
    assert board["case_study"]["title"].startswith("Severe Bihar")


# ---------------------------------------------------------------------------
# 8. CLI Runner Script Execution Test
# ---------------------------------------------------------------------------
def test_run_case_studies_cli(tmp_path):
    """Verify scripts/run_case_studies.py executes via CLI and exports reports."""
    out_json = tmp_path / "scorecard.json"
    out_md = tmp_path / "scorecard.md"

    cmd = [
        sys.executable,
        "scripts/run_case_studies.py",
        "--event", "bihar_squall_2026",
        "--max-cycles", "3",
        "--output-json", str(out_json),
        "--output-md", str(out_md),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, f"CLI failed: {proc.stderr}\n{proc.stdout}"
    assert "Executing Case Study: Severe Bihar" in proc.stdout
    assert "Project Vajra Automated Verification Scorecard" in proc.stdout
    assert out_json.exists()
    assert out_md.exists()
    assert out_json.stat().st_size > 500
    assert out_md.stat().st_size > 500
