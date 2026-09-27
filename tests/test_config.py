"""Unit tests for Project Vajra configuration management (Phase V2-0 / TASK-V2-0.1)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from vajra.config import (
    CIConfig,
    ImpactConfig,
    MosaicConfig,
    Settings,
    V2ModelsConfig,
    load_settings,
)


def test_v2_configuration_defaults():
    """Verify that default settings include all V2 configuration blocks with expected parameters."""
    settings = load_settings()

    # V2 Models configuration
    assert isinstance(settings.v2_models, V2ModelsConfig)
    assert settings.v2_models.backbone == "attention_unet"
    assert settings.v2_models.patch_size == 192
    assert settings.v2_models.alpha_focal == 0.25
    assert settings.v2_models.gamma_focal == 2.0
    assert settings.v2_models.lambda_dice == 0.5

    # Mosaic configuration
    assert isinstance(settings.mosaic, MosaicConfig)
    assert settings.mosaic.max_range_km == 250.0
    assert settings.mosaic.cressman_radius_km == 10.0
    assert "patna" in settings.mosaic.station_weights
    assert "kolkata" in settings.mosaic.station_weights
    assert "ranchi" in settings.mosaic.station_weights
    assert "delhi" in settings.mosaic.station_weights

    # CI Precursor configuration
    assert isinstance(settings.ci, CIConfig)
    assert settings.ci.cooling_rate_threshold_k_per_15m == -4.0
    assert settings.ci.freezing_level_k == 273.15
    assert settings.ci.split_window_diff_k == -1.0
    assert settings.ci.min_area_km2 == 15.0

    # Impact configuration
    assert isinstance(settings.impact, ImpactConfig)
    assert settings.impact.vulnerability_weight == 1.0
    assert settings.impact.population_exposure_threshold == 50000
    assert settings.impact.rural_labor_multiplier == 1.5
    assert settings.impact.rural_labor_start_hour == 11
    assert settings.impact.rural_labor_end_hour == 17
    assert settings.impact.rural_labor_gating is True


def test_v2_environment_overrides(monkeypatch):
    """Verify that VAJRA_* environment variables override default settings correctly with type conversions."""
    monkeypatch.setenv("VAJRA_V2_MODELS__BACKBONE", "hybrid")
    monkeypatch.setenv("VAJRA_V2_MODELS__PATCH_SIZE", "256")
    monkeypatch.setenv("VAJRA_V2_MODELS__ALPHA_FOCAL", "0.30")
    monkeypatch.setenv("VAJRA_MOSAIC__MAX_RANGE_KM", "300.0")
    monkeypatch.setenv("VAJRA_CI__COOLING_RATE_THRESHOLD_K_PER_15M", "-5.5")
    monkeypatch.setenv("VAJRA_IMPACT__POPULATION_EXPOSURE_THRESHOLD", "75000")
    monkeypatch.setenv("VAJRA_IMPACT__RURAL_LABOR_GATING", "false")

    settings = load_settings()

    assert settings.v2_models.backbone == "hybrid"
    assert settings.v2_models.patch_size == 256
    assert abs(settings.v2_models.alpha_focal - 0.30) < 1e-6
    assert abs(settings.mosaic.max_range_km - 300.0) < 1e-6
    assert abs(settings.ci.cooling_rate_threshold_k_per_15m - (-5.5)) < 1e-6
    assert settings.impact.population_exposure_threshold == 75000
    assert settings.impact.rural_labor_gating is False


def test_paths_resolution():
    """Verify that path resolution behaves consistently."""
    settings = load_settings()
    assert isinstance(settings.data_root, Path)
    assert isinstance(settings.models_dir, Path)
    assert isinstance(settings.store_dir, Path)
    assert isinstance(settings.web_dist, Path)
