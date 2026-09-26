"""End-to-end vertical slice on the labelled SIMULATION event.

Historical event -> ingest -> QC -> cells -> features -> models -> forecast ->
risk/alert -> API-visible artifacts -> actual-outcome verification.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from vajra.models import (AdvectionModel, ClimatologyModel, LightningJumpModel,
                          ModelRouter, PersistenceModel)
from vajra.pipeline import NowcastPipeline
from vajra.schemas import DataMode, Event, FallbackRung
from vajra.store import Store


def _pipeline(settings, synthetic_sources):
    from vajra.config import Settings

    router = ModelRouter(
        fusion=None,
        physics=AdvectionModel(vil_threshold=settings.cells.vil_threshold),
        persistence=PersistenceModel(),
        climatology=ClimatologyModel(),
    )
    return NowcastPipeline(settings, synthetic_sources, router, model_version="baselines-test")


def _event(bihar_event):
    return Event(id="SIM_BIHAR_001", title="test", mode=DataMode.SIMULATION,
                 domain="india_0p1", time_start=bihar_event.start,
                 time_end=bihar_event.start + timedelta(hours=3),
                 source="synthetic")


def test_vertical_slice_end_to_end(settings, synthetic_sources, bihar_event):
    pipe = _pipeline(settings, synthetic_sources)
    store = Store(settings)
    pipe.attach_store(store)
    ev = _event(bihar_event)
    store.put_event(ev)

    run = pipe.run_replay(ev, ev.time_start, ev.time_end)

    assert run.cycles >= 15
    assert len(run.forecasts) == run.cycles
    # Alerts must fire during the storm's active phase (deterministic generator)
    assert len(run.alerts) >= 5
    # Outcome settlement: labels exist for both leads
    samples = run.metrics.get("samples", {})
    assert set(samples) == {"30", "60"}
    assert len(samples["30"]) >= 10
    # Verification summary present with real numbers
    m = run.metrics["metrics"]
    assert "30" in m and "60" in m
    for lead in ("30", "60"):
        assert 0.0 <= m[lead]["pod"] <= 1.0
        assert 0.0 <= m[lead]["far"] <= 1.0
    # Stored and retrievable
    assert store.get_run(run.id).cycles == run.cycles
    fcs = store.list_forecasts(run_id=run.id)
    assert len(fcs) == run.cycles
    alerts = store.list_alerts(run_id=run.id)
    assert len(alerts) == len(run.alerts)
    # Every forecast is honestly labelled
    for f in fcs:
        assert f.mode == DataMode.SIMULATION
        assert f.grid is not None
    fid = fcs[len(fcs) // 2].id
    assert store.get_field_paths(fid, 30) is not None
    assert (store.artifacts / fid / "obs.png").exists()
    # Verification stored
    assert store.get_verification(run.id)["metrics"]


def test_fallback_rung_when_all_sources_missing(settings, bihar_event):
    from vajra.schemas import Modality

    empty_sources = {m: type("Dead", (), {
        "get_history": lambda self, t, minutes: [],
        "health": lambda self: None,
        "name": "dead", "modality": m, "mode": DataMode.UNAVAILABLE,
    })() for m in (Modality.RADAR, Modality.SATELLITE, Modality.LIGHTNING)}
    pipe = _pipeline(settings, empty_sources)
    ev = _event(bihar_event)
    forecast, alerts = pipe.run_cycle(ev.time_start + timedelta(minutes=30),
                                      ev.id, DataMode.SIMULATION)
    assert forecast.fallback_rung == FallbackRung.CLIMATOLOGY
    assert forecast.confidence <= 0.1
    assert "climatology" in " ".join(forecast.notes).lower()


def test_alert_suppression_within_window(settings, synthetic_sources, bihar_event):
    pipe = _pipeline(settings, synthetic_sources)
    t = bihar_event.start + timedelta(minutes=100)  # storm active
    fc1, a1 = pipe.run_cycle(t, "SIM_BIHAR_001", DataMode.SIMULATION)
    fc2, a2 = pipe.run_cycle(t + timedelta(minutes=10), "SIM_BIHAR_001", DataMode.SIMULATION)
    if a1:
        # same cell+severity+preset must be suppressed within 30 minutes
        keys1 = {(a.region_name, a.severity, a.preset) for a in a1}
        keys2 = {(a.region_name, a.severity, a.preset) for a in a2}
        assert not (keys1 & keys2), "suppression failed"
