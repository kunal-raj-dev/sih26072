"""Verification suite for Phase 8: Operational Risk, Dynamic Thresholding & CAP 1.2 Alert Engine.

Covers:
1. IMD 4-Stage Warning Color Mapping (Green, Yellow, Orange, Red).
2. Automatic escalation to Red Warning on 2-sigma lightning jump rate acceleration.
3. Dual operational presets: Protective (high POD) vs. Operational (balanced POD/FAR).
4. Spatiotemporal deduplication: suppression of duplicate alerts for 45 min.
5. Escalation bypass: immediate alert dispatch upon severity escalation (Yellow -> Orange -> Red),
   with is_update=True and supersedes_id reference.
6. OASIS CAP 1.2 XML generation, namespace validation, polygon formatting, and schema compliance.
7. OASIS/WMO CAP 1.2 JSON export.
8. RFC 4287 Atom Syndication Feed generation.
9. FastAPI endpoints: /alerts/{id}/cap.xml, /alerts/{id}/cap.json, /alerts/feed.atom.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET
import pytest
from fastapi.testclient import TestClient

from vajra.config import Settings
from vajra.schemas import Alert, Cell, DataMode, FallbackRung, Forecast, ForecastStep
from vajra.alerts import AlertEngine, classify_alert_stage
from vajra.cap import (
    build_cap_12_xml,
    build_cap_12_json,
    build_cap_atom_feed,
    validate_cap_12_xml,
    CAP_NAMESPACE,
)
from vajra.store import Store
from vajra.api.app import create_app


@pytest.fixture
def base_settings():
    s = Settings()
    s.alerts.suppression_minutes = 45
    return s


@pytest.fixture
def sample_cell():
    return Cell(
        id="cell_patna_01",
        time=datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc),
        centroid_lat=25.60,
        centroid_lon=85.14,
        bbox=[85.00, 25.45, 85.28, 25.75],
        area_px=48,
        max_intensity=52.0,
        mean_intensity=40.0,
        flash_count_history=14,
        velocity_kmh=42.0,
        heading_deg=65.0,
    )


@pytest.fixture
def sample_forecast():
    t = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
    return Forecast(
        id="fc_alert_test",
        event_id="bihar_monsoon_2026",
        replay_time=t,
        mode=DataMode.REPLAY,
        fallback_rung=FallbackRung.FULL_FUSION,
        model_version="vajra-fusion-v1.0",
        confidence=0.85,
        modalities_used=[],
        steps=[
            ForecastStep(valid_time=t + timedelta(minutes=30), lead_minutes=30, p_flash_max=0.75, risk_band="HIGH"),
        ],
    )


def test_classify_alert_stage_presets(base_settings):
    """Verify IMD 4-stage color classification for protective and operational presets."""
    prot_cfg = base_settings.alerts.presets["protective"]
    oper_cfg = base_settings.alerts.presets["operational"]

    # Green: below threshold
    assert classify_alert_stage(0.10, "protective", prot_cfg) is None
    assert classify_alert_stage(0.12, "operational", oper_cfg) is None

    # Yellow: Watch / Advisory
    res_prot_y = classify_alert_stage(0.25, "protective", prot_cfg)
    assert res_prot_y == ("YELLOW", "ADVISORY", "Moderate")

    res_oper_y = classify_alert_stage(0.30, "operational", oper_cfg)
    assert res_oper_y == ("YELLOW", "ADVISORY", "Moderate")

    # Orange: Alert / Be Prepared
    res_prot_o = classify_alert_stage(0.45, "protective", prot_cfg)
    assert res_prot_o == ("ORANGE", "WATCH", "Severe")

    res_oper_o = classify_alert_stage(0.55, "operational", oper_cfg)
    assert res_oper_o == ("ORANGE", "WATCH", "Severe")

    # Red: Warning / Take Action
    res_prot_r = classify_alert_stage(0.72, "protective", prot_cfg)
    assert res_prot_r == ("RED", "WARNING", "Extreme")

    res_oper_r = classify_alert_stage(0.78, "operational", oper_cfg)
    assert res_oper_r == ("RED", "WARNING", "Extreme")


def test_lightning_jump_escalates_to_red_warning(base_settings):
    """Verify that a 2-sigma lightning jump automatically escalates any probability to RED Warning."""
    oper_cfg = base_settings.alerts.presets["operational"]

    # Even at low probability P=0.22 (normally Yellow Advisory), jump triggers RED Warning!
    res = classify_alert_stage(0.22, "operational", oper_cfg, has_jump=True)
    assert res == ("RED", "WARNING", "Extreme")


def test_alert_suppression_and_escalation_bypass(base_settings, sample_cell, sample_forecast):
    """Verify 45-min suppression of duplicate alerts and immediate bypass on escalation."""
    engine = AlertEngine(base_settings)
    t0 = sample_forecast.replay_time

    # Cycle 1: P = 0.25 -> Yellow / Advisory
    alerts_c1 = engine.generate(sample_forecast, [sample_cell], lead_minutes=30, p_cell={"cell_patna_01": 0.25})
    assert len(alerts_c1) >= 1
    a1 = next(a for a in alerts_c1 if a.preset == "operational")
    assert a1.imd_stage == "YELLOW"
    assert a1.severity == "ADVISORY"
    assert not a1.is_update

    # Cycle 2 (10 min later): Same severity P = 0.28 (still Yellow)
    fc_c2 = sample_forecast.model_copy(update={"replay_time": t0 + timedelta(minutes=10)})
    alerts_c2 = engine.generate(fc_c2, [sample_cell], lead_minutes=30, p_cell={"cell_patna_01": 0.28})
    # Must be suppressed (no duplicate alert spam)
    oper_c2 = [a for a in alerts_c2 if a.preset == "operational"]
    assert len(oper_c2) == 0

    # Cycle 3 (20 min later): Severe escalation! P = 0.78 -> Red / Warning
    fc_c3 = sample_forecast.model_copy(update={"replay_time": t0 + timedelta(minutes=20)})
    alerts_c3 = engine.generate(fc_c3, [sample_cell], lead_minutes=30, p_cell={"cell_patna_01": 0.78})
    # Suppression must be BYPASSED due to severity escalation!
    oper_c3 = [a for a in alerts_c3 if a.preset == "operational"]
    assert len(oper_c3) == 1
    a3 = oper_c3[0]
    assert a3.imd_stage == "RED"
    assert a3.severity == "WARNING"
    assert a3.cap_severity == "Extreme"
    # Must be flagged as an Update referencing prior alert ID
    assert a3.is_update is True
    assert a3.supersedes_id == a1.id


def test_oasis_cap_12_xml_validation(sample_cell, sample_forecast, base_settings):
    """Verify generated XML complies with OASIS CAP 1.2 schema specifications."""
    engine = AlertEngine(base_settings)
    alerts = engine.generate(sample_forecast, [sample_cell], lead_minutes=30, p_cell={"cell_patna_01": 0.82})
    assert len(alerts) >= 1
    alert = alerts[0]

    xml_str = alert.to_cap_xml()
    assert isinstance(xml_str, str)
    assert xml_str.startswith("<?xml")

    # Validate with CAP 1.2 validator
    is_valid, errors = validate_cap_12_xml(xml_str)
    assert is_valid, f"CAP XML validation failed: {errors}"

    # Parse and inspect elements
    root = ET.fromstring(xml_str)
    assert root.tag == f"{{{CAP_NAMESPACE}}}alert"

    info = root.find(f"{{{CAP_NAMESPACE}}}info")
    assert info is not None
    assert info.find(f"{{{CAP_NAMESPACE}}}category").text == "Met"
    assert info.find(f"{{{CAP_NAMESPACE}}}severity").text in ("Extreme", "Severe", "Moderate")

    # IMD color code
    event_code = info.find(f"{{{CAP_NAMESPACE}}}eventCode")
    assert event_code is not None
    assert event_code.find(f"{{{CAP_NAMESPACE}}}valueName").text == "IMD_COLOR_CODE"
    assert event_code.find(f"{{{CAP_NAMESPACE}}}value").text in ("RED", "ORANGE", "YELLOW")

    # Area polygon closed coordinates
    area = info.find(f"{{{CAP_NAMESPACE}}}area")
    assert area is not None
    poly = area.find(f"{{{CAP_NAMESPACE}}}polygon").text
    coords = poly.split()
    assert len(coords) >= 5
    assert coords[0] == coords[-1]  # closed ring


def test_oasis_cap_12_json_export(sample_cell, sample_forecast, base_settings):
    """Verify CAP 1.2 JSON generation matches WMO/NDMA standard schema."""
    engine = AlertEngine(base_settings)
    alerts = engine.generate(sample_forecast, [sample_cell], lead_minutes=30, p_cell={"cell_patna_01": 0.50})
    alert = alerts[0]

    cap_json = alert.to_cap_json()
    assert isinstance(cap_json, dict)
    assert cap_json["identifier"] == alert.id
    assert cap_json["sender"] == "vajra.nowcast.imd.gov.in"
    assert cap_json["scope"] == "Public"

    info = cap_json["info"][0]
    assert info["category"] == ["Met"]
    assert info["severity"] in ("Extreme", "Severe", "Moderate")
    assert any(ec["valueName"] == "IMD_COLOR_CODE" for ec in info["eventCode"])
    assert len(info["area"][0]["polygon"]) == 1


def test_cap_atom_feed_generation(sample_cell, sample_forecast, base_settings):
    """Verify RFC 4287 Atom Feed generation with CAP 1.2 alternate links."""
    engine = AlertEngine(base_settings)
    alerts = engine.generate(sample_forecast, [sample_cell], lead_minutes=30, p_cell={"cell_patna_01": 0.85})

    feed_xml = build_cap_atom_feed(alerts)
    assert feed_xml.startswith("<?xml")
    assert "<feed" in feed_xml
    assert "<entry" in feed_xml
    assert 'type="application/cap+xml"' in feed_xml


def test_api_cap_endpoints(tmp_path, sample_cell, sample_forecast, base_settings):
    """Verify HTTP endpoints /alerts/{id}/cap.xml, /alerts/{id}/cap.json, and /alerts/feed.atom."""
    settings = Settings()
    settings.paths.artifacts = tmp_path / "artifacts"
    settings.paths.database = tmp_path / "vajra.db"
    store = Store(settings)

    engine = AlertEngine(base_settings)
    alerts = engine.generate(sample_forecast, [sample_cell], lead_minutes=30, p_cell={"cell_patna_01": 0.75})
    assert len(alerts) >= 1
    store.put_alerts(alerts)

    target_alert = alerts[0]
    app = create_app(settings, store)
    client = TestClient(app)

    # 1. Test /alerts/{id}/cap.xml
    resp_xml = client.get(f"/api/v1/alerts/{target_alert.id}/cap.xml")
    assert resp_xml.status_code == 200
    assert "application/cap+xml" in resp_xml.headers["content-type"]
    assert f"<identifier>{target_alert.id}</identifier>" in resp_xml.text
    is_valid, _ = validate_cap_12_xml(resp_xml.text)
    assert is_valid

    # 2. Test /alerts/{id}/cap.json
    resp_json = client.get(f"/api/v1/alerts/{target_alert.id}/cap.json")
    assert resp_json.status_code == 200
    data = resp_json.json()
    assert data["identifier"] == target_alert.id
    assert data["info"][0]["eventCode"][0]["valueName"] == "IMD_COLOR_CODE"

    # 3. Test /alerts/feed.atom
    resp_feed = client.get("/api/v1/alerts/feed.atom")
    assert resp_feed.status_code == 200
    assert "application/atom+xml" in resp_feed.headers["content-type"]
    assert f"urn:uuid:{target_alert.id}" in resp_feed.text
