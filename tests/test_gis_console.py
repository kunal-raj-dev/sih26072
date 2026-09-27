"""Tests for Phase 9: High-Performance Decision-Support GIS Console.

Verifies:
1. Operational REST API endpoints:
   - /api/v1/runs/{run_id}/scoreboard
   - /api/v1/forecasts/{fid}/bulletin
   - /api/v1/alerts/{alert_id}
   - /api/v1/alerts/{alert_id}.cap
2. Static web console assets integrity (HTML, CSS, JS) and UI controls.
3. Print and CAP export capability contracts.
"""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(settings):
    from vajra.api.app import create_app

    app = create_app(settings)
    return TestClient(app)


@pytest.fixture()
def active_run_and_forecast(client):
    """Execute a simulation replay run to populate store with run, forecasts, and alerts."""
    evs = client.get("/api/v1/events").json()
    sim_id = next(e["id"] for e in evs if e["mode"] == "SIMULATION")
    run = client.post(f"/api/v1/replay/{sim_id}/run").json()
    run_id = run["run_id"]
    fcs = client.get(f"/api/v1/runs/{run_id}/forecasts").json()
    fid = fcs[len(fcs) // 2]["id"]
    alerts = client.get(f"/api/v1/alerts?run_id={run_id}").json()
    return run_id, fid, alerts


def test_scoreboard_endpoint_structure(client, active_run_and_forecast):
    """Verify /api/v1/runs/{id}/scoreboard returns complete verification audit payload."""
    run_id, _, _ = active_run_and_forecast
    res = client.get(f"/api/v1/runs/{run_id}/scoreboard")
    assert res.status_code == 200
    sb = res.json()

    assert sb["run_id"] == run_id
    assert sb["mode"] == "SIMULATION"
    assert sb["cycles"] >= 15
    assert "metrics" in sb
    assert "sample_counts" in sb
    assert sb["baseline_model"] == "climatology_logistic_prior"
    assert "GLM" in sb["evaluated_against"] or "LIS" in sb["evaluated_against"]

    import math

    for lead_str, m in sb["metrics"].items():
        assert "bss" in m
        assert "csi" in m
        assert "pod" in m
        assert "far" in m
        bss_val = m["bss"]
        assert bss_val is None or math.isnan(bss_val) or -1.0 <= bss_val <= 1.0


def test_scoreboard_404_for_unknown_run(client):
    res = client.get("/api/v1/runs/nonexistent_run_999/scoreboard")
    assert res.status_code == 404


def test_forecast_emergency_bulletin_endpoint(client, active_run_and_forecast):
    """Verify /api/v1/forecasts/{fid}/bulletin returns structured IMD/NDMA bulletin."""
    _, fid, alerts = active_run_and_forecast
    res = client.get(f"/api/v1/forecasts/{fid}/bulletin?preset=operational")
    assert res.status_code == 200
    b = res.json()

    assert b["bulletin_id"].startswith("NDMA-VAJRA-NOWCAST-")
    assert "IMD" in b["headline"]
    assert "UTC" in b["issue_time_utc"]
    assert "IST" in b["issue_time_ist"]
    assert "IST" in b["valid_until_ist"]
    assert b["max_stage"] in ("GREEN", "YELLOW", "ORANGE", "RED")
    assert isinstance(b["affected_districts"], list)
    assert isinstance(b["affected_blocks"], list)
    assert isinstance(b["standard_operating_procedures"], list)
    assert len(b["standard_operating_procedures"]) >= 4

    # SOP contains lightning shelter directives
    sop_text = " ".join(b["standard_operating_procedures"]).lower()
    assert "shelter" in sop_text
    assert "pucca" in sop_text or "trees" in sop_text


def test_forecast_bulletin_404_for_unknown_fid(client):
    res = client.get("/api/v1/forecasts/fake_forecast_xyz/bulletin")
    assert res.status_code == 404


def test_alert_detail_and_cap_dot_endpoints(client, active_run_and_forecast):
    """Verify /api/v1/alerts/{alert_id} and .cap alias match OASIS CAP specification."""
    _, _, alerts = active_run_and_forecast
    if not alerts:
        pytest.skip("No alerts generated in synthetic run")

    a0 = alerts[0]
    aid = a0["id"]

    # 1. JSON detail
    res_json = client.get(f"/api/v1/alerts/{aid}")
    assert res_json.status_code == 200
    data = res_json.json()
    assert data["id"] == aid
    assert data["severity"] == a0["severity"]
    assert "recommended_action" in data

    # 2. CAP .cap extension endpoint
    res_cap = client.get(f"/api/v1/alerts/{aid}.cap")
    assert res_cap.status_code == 200
    assert "application/cap+xml" in res_cap.headers["content-type"]
    assert b"urn:oasis:names:tc:emergency:cap:1.2" in res_cap.content
    assert b"<identifier>" in res_cap.content


def test_frontend_assets_and_ui_controls():
    """Verify that web console files exist and contain required Phase 9 UI controls."""
    web_dir = Path("web")
    html_file = web_dir / "index.html"
    css_file = web_dir / "style.css"
    js_file = web_dir / "app.js"

    assert html_file.exists(), "web/index.html missing"
    assert css_file.exists(), "web/style.css missing"
    assert js_file.exists(), "web/app.js missing"

    html = html_file.read_text(encoding="utf-8")
    css = css_file.read_text(encoding="utf-8")
    js = js_file.read_text(encoding="utf-8")

    # Timeline scrubber controls
    assert 'id="rewind-btn"' in html
    assert 'id="prev-btn"' in html
    assert 'id="play-btn"' in html
    assert 'id="next-btn"' in html
    assert 'id="t0-btn"' in html
    assert 'id="speed-select"' in html
    assert 'id="horizon-indicator"' in html

    # Dual clock
    assert 'class="clock-utc"' in html or 'id="clock"' in html
    assert 'id="clock-ist"' in html

    # Opacity and district quick jump
    assert 'id="lyr-prob-opacity"' in html
    assert 'id="district-select"' in html

    # Modals
    assert 'id="bulletin-modal"' in html
    assert 'id="scoreboard-modal"' in html
    assert 'id="toast"' in html

    # CSS print rules and modal styling
    assert "@media print" in css
    assert ".modal-backdrop" in css
    assert ".bulletin-sheet" in css
    assert ".stage-banner" in css

    # JavaScript logic
    assert "openBulletinModal" in js
    assert "openScoreboardModal" in js
    assert "updateHorizonIndicator" in js
    assert "DISTRICT_CENTERS" in js
    assert "raster-resampling" in js
