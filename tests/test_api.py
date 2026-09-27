"""API tests: the vertical slice must be reachable and honest over HTTP."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(settings):
    from vajra.api.app import create_app

    app = create_app(settings)
    return TestClient(app)


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_data_health_is_honest(client):
    r = client.get("/api/v1/data-health")
    assert r.status_code == 200
    items = {i["source"]: i for i in r.json()}
    # NWP is NOT provisioned: it must be reported UNAVAILABLE, never faked
    assert items["gfs_nomads"]["status"] == "UNAVAILABLE"


def test_events_listed_with_mode(client):
    r = client.get("/api/v1/events")
    assert r.status_code == 200
    evs = r.json()
    assert any(e["mode"] == "SIMULATION" for e in evs)


def test_full_replay_flow_over_http(client):
    evs = client.get("/api/v1/events").json()
    sim_id = next(e["id"] for e in evs if e["mode"] == "SIMULATION")

    run = client.post(f"/api/v1/replay/{sim_id}/run").json()
    assert run["cycles"] >= 15
    assert run["mode"] == "SIMULATION"

    fcs = client.get(f"/api/v1/runs/{run['run_id']}/forecasts").json()
    assert len(fcs) == run["cycles"]
    fid = fcs[len(fcs) // 2]["id"]

    # probability field renders
    png = client.get(f"/api/v1/forecasts/{fid}/field.png?lead=60")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert png.headers["content-type"] == "image/png" and len(png.content) > 500

    # raw grid available
    npz = client.get(f"/api/v1/forecasts/{fid}/field.npz?lead=60")
    assert npz.status_code == 200

    # cells geojson with properties
    cells = client.get(f"/api/v1/forecasts/{fid}/cells.geojson?lead=60").json()
    assert cells["type"] == "FeatureCollection"

    # observation render
    obs = client.get(f"/api/v1/forecasts/{fid}/obs.png")
    assert obs.status_code == 200 and obs.headers["content-type"] == "image/png"

    # event flashes with mode labels
    fl = client.get(f"/api/v1/events/{sim_id}/flashes.geojson").json()
    assert fl["type"] == "FeatureCollection"
    assert all(ft["properties"]["mode"] == "SIMULATION" for ft in fl["features"])

    # alerts
    alerts = client.get(f"/api/v1/alerts?run_id={run['run_id']}").json()
    assert isinstance(alerts, list)
    for a in alerts:
        assert a["mode"] == "SIMULATION"
        assert a["reason"] and a["recommended_action"]

    # run detail carries verification
    detail = client.get(f"/api/v1/runs/{run['run_id']}").json()
    assert "verification" in detail
    assert detail["metrics"].get("metrics", {}).keys() >= {"30", "60"}


def test_model_health_reports_state(client):
    r = client.get("/api/v1/model-health")
    assert r.status_code == 200
    assert "active_model" in r.json()


def test_config_omits_basemap_key_when_unset(settings):
    from fastapi.testclient import TestClient

    from vajra.api.app import create_app

    settings.basemaps.carto_key = ""  # explicit: .env on a dev machine may set it
    c = TestClient(create_app(settings))
    r = c.get("/api/v1/config")
    assert r.status_code == 200
    assert r.json()["carto_basemap_key"] is None


def test_config_serves_basemap_key_when_set(settings):
    from fastapi.testclient import TestClient

    from vajra.api.app import create_app

    settings.basemaps.carto_key = "placeholder-not-a-real-credential"
    c = TestClient(create_app(settings))
    r = c.get("/api/v1/config")
    assert r.status_code == 200
    assert r.json()["carto_basemap_key"] == "placeholder-not-a-real-credential"


def test_unknown_forecast_is_404(client):
    assert client.get("/api/v1/forecasts/nonexistent").status_code == 404


def test_unknown_radar_station_404(client):
    assert client.get("/api/v1/observations/radar/atlantis.gif").status_code == 404


def test_admin_districts_endpoint(client):
    r = client.get("/api/v1/admin/districts")
    assert r.status_code == 200
    fc = r.json()
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) > 0
    props = fc["features"][0]["properties"]
    assert "district" in props
    assert "state" in props
    assert "population" in props


def test_admin_blocks_endpoint(client):
    r = client.get("/api/v1/admin/blocks")
    assert r.status_code == 200
    fc = r.json()
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) > 0

    # Test filtering by district
    r_filtered = client.get("/api/v1/admin/blocks?district=Patna")
    assert r_filtered.status_code == 200
    fc_filtered = r_filtered.json()
    assert len(fc_filtered["features"]) > 0
    for feat in fc_filtered["features"]:
        assert feat["properties"]["district"].lower() == "patna"
