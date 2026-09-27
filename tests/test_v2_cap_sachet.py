"""Unit and integration test suite for Phase V2-8: Automated OASIS CAP 1.2 Alert Engine & SACHET Dissemination.

Verifies:
1. TASK-V2-8.1: OASIS CAP 1.2 XML & JSON Serialization with Bilingual SACHET Feeds
   - Fully compliant OASIS CAP 1.2 XML output with official namespace.
   - Dual <info> blocks: English ('en-IN') and Hindi ('hi-IN').
   - Authoritative NDMA Hindi directives ("तत्काल पक्के आश्रय में जाएं, पेड़ों के नीचे न खड़े हों").
   - WMO/NDMA compliant CAP 1.2 JSON structure with both bilingual info blocks.
2. TASK-V2-8.2: 45-Minute Spatial Suppression Cache with 2-Sigma Instant Bypass
   - In-memory suppression suppresses duplicate alerts for the same administrative block within 45 min.
   - Spatial selectivity: different administrative blocks receive their own alerts.
   - Instant 2-sigma jump bypass: automated 2-sigma lightning jump surge overrides suppression
     even within the 45-minute window and emits an escalated UPDATE alert with supersedes_id reference.
3. TASK-V2-8.3: Atom 1.0 Alert Syndication Feed
   - Valid RFC 4287 Atom feed with application/cap+xml alternate links.
   - FastAPI endpoint /api/v1/alerts/feed.atom responds with application/atom+xml.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET
import pytest
from fastapi.testclient import TestClient

from vajra.config import Settings
from vajra.schemas import Alert, Cell, DataMode, FallbackRung, Forecast, ForecastStep
from vajra.alerts import AlertEngine
from vajra.cap import (
    CAP_NAMESPACE,
    build_cap_12_xml,
    build_cap_12_json,
    build_cap_atom_feed,
    validate_cap_12_xml,
    get_hindi_directives,
    get_hindi_headline,
    get_hindi_description,
)
from vajra.store import Store
from vajra.api.app import create_app


@pytest.fixture
def alert_settings():
    s = Settings()
    s.alerts.suppression_minutes = 45
    return s


@pytest.fixture
def test_cells():
    t0 = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
    c1 = Cell(
        id="CELL_RANCHI_01",
        time=t0,
        centroid_lat=23.36,
        centroid_lon=85.33,
        bbox=[85.25, 23.30, 85.40, 23.42],
        area_px=64,
        max_intensity=55.0,
        mean_intensity=42.0,
        flash_count_history=18,
    )
    c2 = Cell(
        id="CELL_DHANBAD_01",
        time=t0,
        centroid_lat=23.80,
        centroid_lon=86.43,
        bbox=[86.36, 23.75, 86.50, 23.86],
        area_px=50,
        max_intensity=48.0,
        mean_intensity=36.0,
        flash_count_history=8,
    )
    return c1, c2


@pytest.fixture
def test_forecast(test_cells):
    c1, _ = test_cells
    t0 = c1.time
    return Forecast(
        id="fc_jharkhand_01",
        event_id="jharkhand_norwester_2026",
        replay_time=t0,
        mode=DataMode.LIVE,
        fallback_rung=FallbackRung.FULL_FUSION,
        model_version="vajra-v2.0",
        confidence=0.88,
        modalities_used=[],
        steps=[
            ForecastStep(valid_time=t0 + timedelta(minutes=30), lead_minutes=30, p_flash_max=0.82, risk_band="HIGH"),
        ],
    )


# =========================================================================
# TASK-V2-8.1: OASIS CAP 1.2 XML & JSON Serialization with Bilingual SACHET Feeds
# =========================================================================

def test_bilingual_sachet_cap_12_xml(test_cells, test_forecast, alert_settings):
    """Verify generated CAP 1.2 XML contains valid en-IN and hi-IN info blocks with NDMA directives."""
    c1, _ = test_cells
    engine = AlertEngine(alert_settings)
    alerts = engine.generate(test_forecast, [c1], lead_minutes=30, p_cell={c1.id: 0.85})
    assert len(alerts) >= 1
    alert = alerts[0]

    xml_str = alert.to_cap_xml()
    is_valid, errors = validate_cap_12_xml(xml_str)
    assert is_valid, f"CAP XML validation failed: {errors}"

    root = ET.fromstring(xml_str)
    assert root.tag == f"{{{CAP_NAMESPACE}}}alert"
    assert root.find(f"{{{CAP_NAMESPACE}}}identifier").text == alert.id
    assert root.find(f"{{{CAP_NAMESPACE}}}status").text == "Actual"  # DataMode.LIVE -> Actual

    info_blocks = root.findall(f"{{{CAP_NAMESPACE}}}info")
    assert len(info_blocks) == 2, f"Expected 2 bilingual info blocks, got {len(info_blocks)}"

    # 1. English info block
    info_en = info_blocks[0]
    assert info_en.find(f"{{{CAP_NAMESPACE}}}language").text == "en-IN"
    assert info_en.find(f"{{{CAP_NAMESPACE}}}category").text == "Met"
    assert info_en.find(f"{{{CAP_NAMESPACE}}}urgency").text in ("Immediate", "Expected")
    assert info_en.find(f"{{{CAP_NAMESPACE}}}severity").text in ("Extreme", "Severe", "Moderate")
    assert info_en.find(f"{{{CAP_NAMESPACE}}}instruction").text == alert.recommended_action

    # 2. Hindi info block (NDMA SACHET compliance)
    info_hi = info_blocks[1]
    assert info_hi.find(f"{{{CAP_NAMESPACE}}}language").text == "hi-IN"
    assert info_hi.find(f"{{{CAP_NAMESPACE}}}category").text == "Met"
    assert info_hi.find(f"{{{CAP_NAMESPACE}}}event").text == "वज्रपात चेतावनी"
    assert info_hi.find(f"{{{CAP_NAMESPACE}}}urgency").text == info_en.find(f"{{{CAP_NAMESPACE}}}urgency").text
    assert info_hi.find(f"{{{CAP_NAMESPACE}}}severity").text == info_en.find(f"{{{CAP_NAMESPACE}}}severity").text

    # Verify NDMA directive keywords in Hindi instruction
    instruction_hi = info_hi.find(f"{{{CAP_NAMESPACE}}}instruction").text
    assert "तत्काल पक्के आश्रय में जाएं" in instruction_hi or "सुरक्षित" in instruction_hi
    assert "पेड़ों के नीचे न खड़े हों" in instruction_hi or "पेड़ों के नीचे" in instruction_hi

    # Verify area polygon closed in both info blocks
    area_en = info_en.find(f"{{{CAP_NAMESPACE}}}area")
    area_hi = info_hi.find(f"{{{CAP_NAMESPACE}}}area")
    assert area_en.find(f"{{{CAP_NAMESPACE}}}polygon").text == area_hi.find(f"{{{CAP_NAMESPACE}}}polygon").text


def test_bilingual_sachet_cap_12_json(test_cells, test_forecast, alert_settings):
    """Verify CAP 1.2 JSON structure contains dual info blocks matching WMO/NDMA schema."""
    c1, _ = test_cells
    engine = AlertEngine(alert_settings)
    alerts = engine.generate(test_forecast, [c1], lead_minutes=30, p_cell={c1.id: 0.72})
    alert = alerts[0]

    cap_json = alert.to_cap_json()
    assert cap_json["identifier"] == alert.id
    assert cap_json["sender"] == "vajra.nowcast.imd.gov.in"
    assert len(cap_json["info"]) == 2

    en_info = cap_json["info"][0]
    hi_info = cap_json["info"][1]
    assert en_info["language"] == "en-IN"
    assert hi_info["language"] == "hi-IN"
    assert "तत्काल" in hi_info["instruction"] or "सुरक्षित" in hi_info["instruction"]
    assert hi_info["event"] == "वज्रपात चेतावनी"


def test_hindi_helpers():
    """Verify standalone Hindi translation helpers."""
    w_dir = get_hindi_directives("WARNING")
    assert "तत्काल पक्के आश्रय में जाएं" in w_dir
    assert "पेड़ों के नीचे न खड़े हों" in w_dir

    watch_dir = get_hindi_directives("WATCH")
    assert "सुरक्षित पक्के भवनों" in watch_dir

    adv_dir = get_hindi_directives("ADVISORY")
    assert "मौसम की स्थिति पर नजर रखें" in adv_dir


# =========================================================================
# TASK-V2-8.2: 45-Minute Spatial Suppression Cache with 2-Sigma Bypass
# =========================================================================

def test_suppression_and_instant_2sigma_jump_bypass(test_cells, test_forecast, alert_settings):
    """Verify 45-minute duplicate suppression and instant bypass upon 2-sigma lightning jump."""
    c1, _ = test_cells
    engine = AlertEngine(alert_settings)
    t0 = test_forecast.replay_time

    # Cycle 1 (T=0): Cell P=0.75 (WARNING, has_jump=False)
    alerts_c1 = engine.generate(test_forecast, [c1], lead_minutes=30, p_cell={c1.id: 0.75})
    a1 = next(a for a in alerts_c1 if a.preset == "operational")
    assert a1.severity == "WARNING"
    assert not a1.is_update

    # Cycle 2 (T=15 min): Same severity P=0.78 (still WARNING, no jump)
    fc_c2 = test_forecast.model_copy(update={"replay_time": t0 + timedelta(minutes=15)})
    alerts_c2 = engine.generate(fc_c2, [c1], lead_minutes=30, p_cell={c1.id: 0.78})
    oper_c2 = [a for a in alerts_c2 if a.preset == "operational"]
    # Must be suppressed: within 45 min and severity has not changed
    assert len(oper_c2) == 0

    # Cycle 3 (T=25 min): Severe 2-sigma lightning jump detected!
    fc_c3 = test_forecast.model_copy(update={"replay_time": t0 + timedelta(minutes=25)})
    alerts_c3 = engine.generate(
        fc_c3,
        [c1],
        lead_minutes=30,
        p_cell={c1.id: 0.78},
        jump_cells={c1.id},  # 2-sigma lightning jump rate surge
    )
    oper_c3 = [a for a in alerts_c3 if a.preset == "operational"]
    # Instant Bypass: must NOT be suppressed, must issue an UPDATE alert referencing prior alert ID
    assert len(oper_c3) == 1
    a3 = oper_c3[0]
    assert a3.is_update is True
    assert a3.supersedes_id == a1.id
    assert "SEVERE LIGHTNING JUMP RATE SURGE" in a3.headline

    # Verify CAP XML reflects msgType='Update' and <references> element
    xml_c3 = a3.to_cap_xml()
    assert "<msgType>Update</msgType>" in xml_c3
    assert f"<references>vajra.nowcast.imd.gov.in,{a1.id}," in xml_c3


def test_spatial_selectivity_across_different_blocks(test_cells, test_forecast, alert_settings):
    """Verify that suppression is spatially selective and does not suppress distinct storm cells/blocks."""
    c1, c2 = test_cells
    engine = AlertEngine(alert_settings)

    # Issue alert for Ranchi (c1)
    alerts_ranchi = engine.generate(test_forecast, [c1], lead_minutes=30, p_cell={c1.id: 0.70})
    assert any(a.preset == "operational" for a in alerts_ranchi)

    # 5 minutes later, issue alert for Dhanbad (c2)
    fc_5m = test_forecast.model_copy(update={"replay_time": test_forecast.replay_time + timedelta(minutes=5)})
    alerts_dhanbad = engine.generate(fc_5m, [c2], lead_minutes=30, p_cell={c2.id: 0.70})
    oper_dhanbad = [a for a in alerts_dhanbad if a.preset == "operational"]
    # Dhanbad must NOT be suppressed by prior Ranchi alert!
    assert len(oper_dhanbad) == 1
    assert "Dhanbad" in oper_dhanbad[0].region_name


# =========================================================================
# TASK-V2-8.3: Atom 1.0 Alert Syndication Feed
# =========================================================================

def test_atom_syndication_feed_and_endpoint(tmp_path, test_cells, test_forecast, alert_settings):
    """Verify Atom 1.0 syndication feed generation and FastAPI /api/v1/alerts/feed.atom endpoint."""
    settings = Settings()
    settings.paths.artifacts = tmp_path / "artifacts"
    settings.paths.database = tmp_path / "vajra.db"
    store = Store(settings)

    c1, _ = test_cells
    engine = AlertEngine(alert_settings)
    alerts = engine.generate(test_forecast, [c1], lead_minutes=30, p_cell={c1.id: 0.80})
    assert len(alerts) >= 1
    store.put_alerts(alerts)

    # 1. Direct feed XML generation
    feed_xml = build_cap_atom_feed(alerts, feed_title="NDMA SACHET - Project Vajra Feed")
    assert "<feed xmlns=\"http://www.w3.org/2005/Atom\"" in feed_xml
    assert "<title>NDMA SACHET - Project Vajra Feed</title>" in feed_xml
    assert f"<id>urn:uuid:{alerts[0].id}</id>" in feed_xml
    assert f'href="/api/v1/alerts/{alerts[0].id}/cap.xml"' in feed_xml

    # 2. FastAPI endpoint
    app = create_app(settings, store)
    client = TestClient(app)

    resp = client.get("/api/v1/alerts/feed.atom")
    assert resp.status_code == 200
    assert "application/atom+xml" in resp.headers["content-type"]
    assert f"<id>urn:uuid:{alerts[0].id}</id>" in resp.text
