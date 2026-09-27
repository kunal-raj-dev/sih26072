"""Unit tests for modernized schemas and multi-hazard enums (Phase V2-0 / TASK-V2-0.2)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from vajra.schemas import (
    Alert,
    Cell,
    DataMode,
    FallbackRung,
    ForecastStep,
    HazardType,
    StormLifecycleState,
    utcnow,
)


def test_hazard_type_enum():
    """Verify HazardType enum variants."""
    assert HazardType.LIGHTNING.value == "LIGHTNING"
    assert HazardType.SEVERE_THUNDERSTORM.value == "SEVERE_THUNDERSTORM"
    assert HazardType.HAIL.value == "HAIL"
    assert HazardType.CONVECTIVE_INITIATION.value == "CONVECTIVE_INITIATION"


def test_storm_lifecycle_state_enum():
    """Verify StormLifecycleState enum variants."""
    assert StormLifecycleState.INITIATING.value == "INITIATING"
    assert StormLifecycleState.INTENSIFYING.value == "INTENSIFYING"
    assert StormLifecycleState.MATURE.value == "MATURE"
    assert StormLifecycleState.DECAYING.value == "DECAYING"
    assert StormLifecycleState.SPLIT.value == "SPLIT"
    assert StormLifecycleState.MERGE.value == "MERGE"


def test_cell_schema_modernization():
    """Verify Cell schema backwards compatibility and new kinematic/lifecycle fields."""
    now = utcnow()
    # Baseline instantiation without new fields
    c1 = Cell(
        id="c1",
        time=now,
        centroid_lat=25.5,
        centroid_lon=85.1,
        bbox=[85.0, 25.4, 85.2, 25.6],
        area_px=20,
        max_intensity=52.0,
        mean_intensity=38.0,
    )
    assert c1.lifecycle_state == StormLifecycleState.INITIATING
    assert c1.lightning_jump_times == []
    assert c1.accel_dlat == 0.0
    assert c1.accel_dlon == 0.0
    assert c1.acceleration_kmh2 == 0.0
    assert c1.acceleration_vector == [0.0, 0.0]

    # Instantiation with V2 fields
    jump_time = datetime(2026, 5, 12, 14, 30, tzinfo=timezone.utc)
    c2 = Cell(
        id="c2",
        time=now,
        centroid_lat=25.5,
        centroid_lon=85.1,
        bbox=[85.0, 25.4, 85.2, 25.6],
        area_px=35,
        max_intensity=58.0,
        mean_intensity=45.0,
        lifecycle_state=StormLifecycleState.INTENSIFYING,
        lightning_jump_times=[jump_time],
        accel_dlat=0.01,
        accel_dlon=0.02,
        acceleration_kmh2=12.5,
        acceleration_vector=[0.02, 0.01],
    )
    assert c2.lifecycle_state == StormLifecycleState.INTENSIFYING
    assert len(c2.lightning_jump_times) == 1
    assert c2.accel_dlat == 0.01
    assert c2.accel_dlon == 0.02
    assert c2.acceleration_kmh2 == 12.5
    assert c2.acceleration_vector == [0.02, 0.01]

    # Serialization test
    d = c2.model_dump()
    assert d["lifecycle_state"] == "INTENSIFYING"
    assert d["acceleration_kmh2"] == 12.5


def test_forecast_step_schema_expansion():
    """Verify ForecastStep schema supports decoupled probability grids and serialization."""
    now = utcnow()
    step_base = ForecastStep(
        valid_time=now,
        lead_minutes=30,
        p_flash_max=0.85,
        risk_band="HIGH",
    )
    assert step_base.p_flash_grid is None
    assert step_base.p_storm_grid is None
    assert step_base.p_ci_grid is None
    assert step_base.uncertainty_grid is None

    # Instantiate with 2D numpy arrays
    flash_arr = np.array([[0.1, 0.2], [0.8, 0.9]], dtype=np.float32)
    storm_arr = np.array([[0.05, 0.15], [0.75, 0.85]], dtype=np.float32)
    ci_arr = np.zeros((2, 2), dtype=np.float32)
    u_arr = np.full((2, 2), 0.12, dtype=np.float32)

    step_grids = ForecastStep(
        valid_time=now,
        lead_minutes=30,
        p_flash_max=0.9,
        risk_band="HIGH",
        p_flash_grid=flash_arr,
        p_storm_grid=storm_arr,
        p_ci_grid=ci_arr,
        uncertainty_grid=u_arr,
    )

    # Test serialization to JSON converts numpy arrays cleanly
    dumped_json = step_grids.model_dump_json()
    data = json.loads(dumped_json)
    assert isinstance(data["p_flash_grid"], list)
    assert data["p_flash_grid"][1][1] == pytest.approx(0.9, abs=1e-4)
    assert data["p_storm_grid"][1][1] == pytest.approx(0.85, abs=1e-4)
    assert data["uncertainty_grid"][0][0] == pytest.approx(0.12, abs=1e-4)


def test_alert_hazard_compatibility():
    """Verify Alert accepts both legacy strings and new HazardType enums."""
    now = utcnow()
    a1 = Alert(
        event_id="test_ev",
        valid_from=now,
        valid_until=now,
        severity="WARNING",
        hazard=HazardType.LIGHTNING,
        region_name="Patna",
        bbox=[85.0, 25.0, 86.0, 26.0],
        probability=0.8,
        confidence=0.85,
        lead_minutes=30,
        preset="protective",
        reason="Severe lightning activity detected",
        model_version="vajra-v2.0",
        mode=DataMode.SIMULATION,
    )
    assert a1.hazard == HazardType.LIGHTNING

    a2 = Alert(
        event_id="test_ev",
        valid_from=now,
        valid_until=now,
        severity="WATCH",
        hazard="THUNDERSTORM",
        region_name="Gaya",
        bbox=[84.5, 24.5, 85.5, 25.5],
        probability=0.6,
        confidence=0.7,
        lead_minutes=45,
        preset="operational",
        reason="Approaching squall line",
        model_version="vajra-v2.0",
        mode=DataMode.SIMULATION,
    )
    assert a2.hazard == "THUNDERSTORM"


def test_baseline_lock_fixture():
    """Verify that tests/fixtures/v1_baseline_lock.json exists and contains frozen baseline metrics."""
    repo_root = Path(__file__).resolve().parents[1]
    lock_path = repo_root / "tests" / "fixtures" / "v1_baseline_lock.json"
    assert lock_path.exists(), "v1_baseline_lock.json must exist"

    data = json.loads(lock_path.read_text(encoding="utf-8"))
    assert data["test_suite"]["total_tests"] == 132
    assert data["test_suite"]["tests_passed"] == 132
    assert data["burn_in_benchmark"]["mean_latency_ms"] <= 1000.0
    assert data["scientific_verification_baseline"]["benchmark_event"] == "sevir_s810646"
    assert data["scientific_verification_baseline"]["brier_skill_score_vs_climatology"] == pytest.approx(0.498, abs=1e-3)
