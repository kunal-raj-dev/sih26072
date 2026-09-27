"""OASIS Common Alerting Protocol (CAP 1.2) Engine (Phase 8).

Strictly compliant with OASIS CAP v1.2 / ITU-T X.1303 and NDMA SACHET standards:
- CAP 1.2 XML serialization (xmlns="urn:oasis:names:tc:emergency:cap:1.2")
- CAP 1.2 JSON serialization (WMO/NDMA compliant format)
- CAP Atom Feed generator (RFC 4287 + CAP 1.2 profile for national alert aggregation)
- Schema and structural validator for CAP 1.2 payloads.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from .schemas import Alert, DataMode

logger = logging.getLogger(__name__)

CAP_NAMESPACE = "urn:oasis:names:tc:emergency:cap:1.2"
SENDER_ID = "vajra.nowcast.imd.gov.in"
SENDER_NAME = "Project Vajra Lightning Nowcasting Decision Support System (MoES/IMD)"


def _format_iso(dt: datetime) -> str:
    """Format datetime as strict ISO-8601 with timezone (e.g. 2026-09-27T08:00:00+00:00)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _format_polygon(bbox: list[float]) -> str:
    """Convert bounding box [min_lon, min_lat, max_lon, max_lat] to CAP 1.2 polygon.

    CAP 1.2 polygon format: space-delimited latitude,longitude pairs, closed.
    Example: 'lat1,lon1 lat2,lon2 lat3,lon3 lat4,lon4 lat1,lon1'
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    coords = [
        (min_lat, min_lon),
        (min_lat, max_lon),
        (max_lat, max_lon),
        (max_lat, min_lon),
        (min_lat, min_lon),  # close the ring
    ]
    return " ".join(f"{round(lat, 5)},{round(lon, 5)}" for lat, lon in coords)


def get_hindi_directives(severity: str) -> str:
    """Return actionable Hindi directive conforming to NDMA / SACHET standards."""
    if severity == "WARNING":
        return (
            "तत्काल पक्के आश्रय में जाएं, पेड़ों के नीचे न खड़े हों। खुले खेतों, जल स्रोतों "
            "और धातु की बाड़ों से तुरंत दूर रहें। सभी कृषि व बाहरी कार्य तत्काल रोक दें।"
        )
    elif severity == "WATCH":
        return (
            "सुरक्षित पक्के भवनों के निकट रहें और सतर्क रहें। बच्चों एवं पशुओं को खुले "
            "स्थानों से तुरंत सुरक्षित स्थान पर ले जाएं। पेड़ों के नीचे शरण न लें।"
        )
    return (
        "मौसम की स्थिति पर नजर रखें। आंधी या बिजली चमकने पर खुले मैदानों में न रहें "
        "और निकटतम सुरक्षित आश्रय की पहचान रखें।"
    )


def get_hindi_headline(alert: Alert) -> str:
    """Return official bilingual Hindi headline for CAP 1.2 alert."""
    if alert.severity == "WARNING":
        return f"[आईएमडी {alert.imd_stage} {alert.severity}] {alert.region_name} में {alert.lead_minutes} मिनट के भीतर आकाशीय बिजली / वज्रपात की तीव्र चेतावनी"
    elif alert.severity == "WATCH":
        return f"[आईएमडी {alert.imd_stage} {alert.severity}] {alert.region_name} में {alert.lead_minutes} मिनट के भीतर बिजली गिरने की प्रबल संभावना"
    return f"[आईएमडी {alert.imd_stage} {alert.severity}] {alert.region_name} के लिए वज्रपात चेतावनी"


def get_hindi_description(alert: Alert) -> str:
    """Return official bilingual Hindi description for CAP 1.2 alert."""
    jump_str = " (अत्यधिक तीव्र 2-सिग्मा बिजली दर वृद्धि दर्ज)" if "JUMP" in alert.headline or "jump" in alert.reason.lower() else ""
    return (
        f"आगामी {alert.lead_minutes} मिनट में वज्रपात की संभावना {alert.probability:.0%} है। "
        f"प्रभावित क्षेत्र: {alert.region_name}। संभावित प्रभावित जनसंख्या: {alert.population_exposed}।{jump_str}"
    )


def build_cap_12_xml(alert: Alert) -> str:
    """Generate an official OASIS CAP 1.2 XML document for an Alert with bilingual info blocks (en-IN, hi-IN)."""
    root = ET.Element("alert", xmlns=CAP_NAMESPACE)

    # Required top-level header elements
    ET.SubElement(root, "identifier").text = alert.id
    ET.SubElement(root, "sender").text = SENDER_ID
    ET.SubElement(root, "sent").text = _format_iso(alert.issued_at)

    # Status: Actual for LIVE, Test for REPLAY/SIMULATION (honesty principle)
    status_val = "Actual" if alert.mode == DataMode.LIVE else "Test"
    ET.SubElement(root, "status").text = status_val

    # MsgType: Alert or Update
    msg_type = "Update" if alert.is_update else "Alert"
    ET.SubElement(root, "msgType").text = msg_type
    ET.SubElement(root, "scope").text = "Public"

    # References if this is an update
    if alert.is_update and alert.supersedes_id:
        ref_sent = _format_iso(alert.valid_from)
        ET.SubElement(root, "references").text = f"{SENDER_ID},{alert.supersedes_id},{ref_sent}"

    resp_type = "Shelter" if alert.severity == "WARNING" else ("Prepare" if alert.severity == "WATCH" else "Monitor")
    params = [
        ("P_FLASH", f"{alert.probability:.3f}"),
        ("LEAD_MINUTES", str(alert.lead_minutes)),
        ("PRESET", alert.preset),
        ("CONFIDENCE", f"{alert.confidence:.2f}"),
        ("MODEL_VERSION", alert.model_version),
        ("DATA_MODE", alert.mode.value),
        ("POPULATION_EXPOSED", str(alert.population_exposed)),
    ]

    # --- 1. Primary English <info> block (en-IN) ---
    info_en = ET.SubElement(root, "info")
    ET.SubElement(info_en, "language").text = "en-IN"
    ET.SubElement(info_en, "category").text = "Met"
    ET.SubElement(info_en, "event").text = f"{alert.hazard.capitalize()} Hazard Nowcast"
    ET.SubElement(info_en, "responseType").text = resp_type
    ET.SubElement(info_en, "urgency").text = alert.urgency
    ET.SubElement(info_en, "severity").text = alert.cap_severity
    ET.SubElement(info_en, "certainty").text = alert.certainty

    event_code_en = ET.SubElement(info_en, "eventCode")
    ET.SubElement(event_code_en, "valueName").text = "IMD_COLOR_CODE"
    ET.SubElement(event_code_en, "value").text = alert.imd_stage

    ET.SubElement(info_en, "effective").text = _format_iso(alert.valid_from)
    ET.SubElement(info_en, "onset").text = _format_iso(alert.valid_from)
    ET.SubElement(info_en, "expires").text = _format_iso(alert.valid_until)
    ET.SubElement(info_en, "senderName").text = SENDER_NAME

    headline_en = (
        alert.headline
        or f"[IMD {alert.imd_stage} {alert.severity}] Lightning hazard expected in {alert.region_name} within {alert.lead_minutes} min (P={alert.probability:.2f})"
    )
    ET.SubElement(info_en, "headline").text = headline_en
    ET.SubElement(info_en, "description").text = alert.reason
    ET.SubElement(info_en, "instruction").text = alert.recommended_action
    ET.SubElement(info_en, "web").text = f"https://vajra.nowcast.imd.gov.in/alerts/{alert.id}"

    for p_name, p_val in params:
        param_elem = ET.SubElement(info_en, "parameter")
        ET.SubElement(param_elem, "valueName").text = p_name
        ET.SubElement(param_elem, "value").text = p_val

    for sig_name, sig_val in alert.contributing_signals.items():
        param_elem = ET.SubElement(info_en, "parameter")
        ET.SubElement(param_elem, "valueName").text = f"SIGNAL_{sig_name.upper()}"
        ET.SubElement(param_elem, "value").text = str(sig_val)

    area_en = ET.SubElement(info_en, "area")
    ET.SubElement(area_en, "areaDesc").text = alert.region_name
    ET.SubElement(area_en, "polygon").text = _format_polygon(alert.bbox)
    for dist in alert.affected_districts:
        gc = ET.SubElement(area_en, "geocode")
        ET.SubElement(gc, "valueName").text = "DISTRICT"
        ET.SubElement(gc, "value").text = dist
    for blk in alert.affected_blocks:
        gc = ET.SubElement(area_en, "geocode")
        ET.SubElement(gc, "valueName").text = "BLOCK"
        ET.SubElement(gc, "value").text = blk

    # --- 2. Bilingual Hindi <info> block (hi-IN) for SACHET / NDMA compliance ---
    info_hi = ET.SubElement(root, "info")
    ET.SubElement(info_hi, "language").text = "hi-IN"
    ET.SubElement(info_hi, "category").text = "Met"
    ET.SubElement(info_hi, "event").text = "वज्रपात चेतावनी"
    ET.SubElement(info_hi, "responseType").text = resp_type
    ET.SubElement(info_hi, "urgency").text = alert.urgency
    ET.SubElement(info_hi, "severity").text = alert.cap_severity
    ET.SubElement(info_hi, "certainty").text = alert.certainty

    event_code_hi = ET.SubElement(info_hi, "eventCode")
    ET.SubElement(event_code_hi, "valueName").text = "IMD_COLOR_CODE"
    ET.SubElement(event_code_hi, "value").text = alert.imd_stage

    ET.SubElement(info_hi, "effective").text = _format_iso(alert.valid_from)
    ET.SubElement(info_hi, "onset").text = _format_iso(alert.valid_from)
    ET.SubElement(info_hi, "expires").text = _format_iso(alert.valid_until)
    ET.SubElement(info_hi, "senderName").text = "परियोजना वज्र (पृथ्वी विज्ञान मंत्रालय / भारत मौसम विज्ञान विभाग)"

    ET.SubElement(info_hi, "headline").text = get_hindi_headline(alert)
    ET.SubElement(info_hi, "description").text = get_hindi_description(alert)
    ET.SubElement(info_hi, "instruction").text = get_hindi_directives(alert.severity)
    ET.SubElement(info_hi, "web").text = f"https://vajra.nowcast.imd.gov.in/alerts/{alert.id}"

    for p_name, p_val in params:
        param_elem = ET.SubElement(info_hi, "parameter")
        ET.SubElement(param_elem, "valueName").text = p_name
        ET.SubElement(param_elem, "value").text = p_val

    for sig_name, sig_val in alert.contributing_signals.items():
        param_elem = ET.SubElement(info_hi, "parameter")
        ET.SubElement(param_elem, "valueName").text = f"SIGNAL_{sig_name.upper()}"
        ET.SubElement(param_elem, "value").text = str(sig_val)

    area_hi = ET.SubElement(info_hi, "area")
    ET.SubElement(area_hi, "areaDesc").text = alert.region_name
    ET.SubElement(area_hi, "polygon").text = _format_polygon(alert.bbox)
    for dist in alert.affected_districts:
        gc = ET.SubElement(area_hi, "geocode")
        ET.SubElement(gc, "valueName").text = "DISTRICT"
        ET.SubElement(gc, "value").text = dist
    for blk in alert.affected_blocks:
        gc = ET.SubElement(area_hi, "geocode")
        ET.SubElement(gc, "valueName").text = "BLOCK"
        ET.SubElement(gc, "value").text = blk

    # Indentation & XML Declaration
    ET.indent(root, space="  ")
    xml_str = ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
    return xml_str


def build_cap_12_json(alert: Alert) -> dict[str, Any]:
    """Generate an official OASIS/WMO compliant CAP 1.2 JSON object for an Alert with bilingual info."""
    status_val = "Actual" if alert.mode == DataMode.LIVE else "Test"
    msg_type = "Update" if alert.is_update else "Alert"
    resp_type = "Shelter" if alert.severity == "WARNING" else ("Prepare" if alert.severity == "WATCH" else "Monitor")
    headline_text = (
        alert.headline
        or f"[IMD {alert.imd_stage} {alert.severity}] Lightning hazard expected in {alert.region_name} within {alert.lead_minutes} min (P={alert.probability:.2f})"
    )

    common_params = [
        {"valueName": "P_FLASH", "value": f"{alert.probability:.3f}"},
        {"valueName": "LEAD_MINUTES", "value": str(alert.lead_minutes)},
        {"valueName": "PRESET", "value": alert.preset},
        {"valueName": "CONFIDENCE", "value": f"{alert.confidence:.2f}"},
        {"valueName": "MODEL_VERSION", "value": alert.model_version},
        {"valueName": "DATA_MODE", "value": alert.mode.value},
        {"valueName": "POPULATION_EXPOSED", "value": str(alert.population_exposed)},
    ]

    common_area = [
        {
            "areaDesc": alert.region_name,
            "polygon": [_format_polygon(alert.bbox)],
            "geocode": [
                *[{"valueName": "DISTRICT", "value": d} for d in alert.affected_districts],
                *[{"valueName": "BLOCK", "value": b} for b in alert.affected_blocks],
            ],
        }
    ]

    info_en = {
        "language": "en-IN",
        "category": ["Met"],
        "event": f"{alert.hazard.capitalize()} Hazard Nowcast",
        "responseType": [resp_type],
        "urgency": alert.urgency,
        "severity": alert.cap_severity,
        "certainty": alert.certainty,
        "eventCode": [{"valueName": "IMD_COLOR_CODE", "value": alert.imd_stage}],
        "effective": _format_iso(alert.valid_from),
        "onset": _format_iso(alert.valid_from),
        "expires": _format_iso(alert.valid_until),
        "senderName": SENDER_NAME,
        "headline": headline_text,
        "description": alert.reason,
        "instruction": alert.recommended_action,
        "web": f"https://vajra.nowcast.imd.gov.in/alerts/{alert.id}",
        "parameter": common_params,
        "area": common_area,
    }

    info_hi = {
        "language": "hi-IN",
        "category": ["Met"],
        "event": "वज्रपात चेतावनी",
        "responseType": [resp_type],
        "urgency": alert.urgency,
        "severity": alert.cap_severity,
        "certainty": alert.certainty,
        "eventCode": [{"valueName": "IMD_COLOR_CODE", "value": alert.imd_stage}],
        "effective": _format_iso(alert.valid_from),
        "onset": _format_iso(alert.valid_from),
        "expires": _format_iso(alert.valid_until),
        "senderName": "परियोजना वज्र (पृथ्वी विज्ञान मंत्रालय / भारत मौसम विज्ञान विभाग)",
        "headline": get_hindi_headline(alert),
        "description": get_hindi_description(alert),
        "instruction": get_hindi_directives(alert.severity),
        "web": f"https://vajra.nowcast.imd.gov.in/alerts/{alert.id}",
        "parameter": common_params,
        "area": common_area,
    }

    cap_json: dict[str, Any] = {
        "identifier": alert.id,
        "sender": SENDER_ID,
        "sent": _format_iso(alert.issued_at),
        "status": status_val,
        "msgType": msg_type,
        "scope": "Public",
        "info": [info_en, info_hi],
    }

    if alert.is_update and alert.supersedes_id:
        ref_sent = _format_iso(alert.valid_from)
        cap_json["references"] = f"{SENDER_ID},{alert.supersedes_id},{ref_sent}"

    return cap_json


def build_cap_atom_feed(alerts: list[Alert], feed_title: str = "Project Vajra - Lightning Alert Feed") -> str:
    """Generate an RFC 4287 Atom Syndication Feed containing CAP 1.2 alerts.

    Used by disaster management aggregation hubs (NDMA, State EOCs).
    """
    feed = ET.Element("feed", xmlns="http://www.w3.org/2005/Atom")
    ET.SubElement(feed, "title").text = feed_title
    ET.SubElement(feed, "id").text = "https://vajra.nowcast.imd.gov.in/alerts/feed.atom"
    ET.SubElement(feed, "updated").text = _format_iso(datetime.now(timezone.utc))

    author = ET.SubElement(feed, "author")
    ET.SubElement(author, "name").text = SENDER_NAME

    for alert in alerts:
        entry = ET.SubElement(feed, "entry")
        ET.SubElement(entry, "title").text = f"[IMD {alert.imd_stage}] {alert.region_name} - {alert.severity}"
        ET.SubElement(entry, "id").text = f"urn:uuid:{alert.id}"
        ET.SubElement(entry, "updated").text = _format_iso(alert.issued_at)
        ET.SubElement(entry, "summary").text = alert.reason

        link = ET.SubElement(entry, "link", rel="alternate", type="application/cap+xml")
        link.attrib["href"] = f"/api/v1/alerts/{alert.id}/cap.xml"

    ET.indent(feed, space="  ")
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True).decode("utf-8")


def validate_cap_12_xml(xml_string: str) -> tuple[bool, list[str]]:
    """Validate a CAP 1.2 XML string against OASIS CAP 1.2 schema invariants.

    Returns:
        (is_valid, list_of_errors)
    """
    errors: list[str] = []
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError as exc:
        return False, [f"XML parsing failed: {exc}"]

    # 1. Namespace validation
    if not root.tag.endswith("alert"):
        errors.append(f"Root element must be 'alert', got '{root.tag}'")
    ns = ""
    if "}" in root.tag:
        ns = root.tag.split("}")[0].strip("{")
    if ns != CAP_NAMESPACE:
        errors.append(f"Namespace must be '{CAP_NAMESPACE}', got '{ns}'")

    # 2. Required alert elements
    required_alert_tags = ["identifier", "sender", "sent", "status", "msgType", "scope"]
    for tag in required_alert_tags:
        elem = root.find(f"{{{ns}}}{tag}") if ns else root.find(tag)
        if elem is None or not elem.text:
            errors.append(f"Missing required alert element: <{tag}>")

    # 3. Status enumeration
    valid_statuses = {"Actual", "Exercise", "System", "Test", "Draft"}
    status_elem = root.find(f"{{{ns}}}status") if ns else root.find("status")
    if status_elem is not None and status_elem.text not in valid_statuses:
        errors.append(f"Invalid status '{status_elem.text}', must be one of {valid_statuses}")

    # 4. MsgType enumeration
    valid_msg_types = {"Alert", "Update", "Cancel", "Ack", "Error"}
    msg_elem = root.find(f"{{{ns}}}msgType") if ns else root.find("msgType")
    if msg_elem is not None and msg_elem.text not in valid_msg_types:
        errors.append(f"Invalid msgType '{msg_elem.text}', must be one of {valid_msg_types}")

    # 5. Info block validation
    info_elems = root.findall(f"{{{ns}}}info") if ns else root.findall("info")
    if not info_elems:
        errors.append("Alert must contain at least one <info> block")
    else:
        for info in info_elems:
            # Required info elements
            for tag in ["category", "event", "urgency", "severity", "certainty"]:
                elem = info.find(f"{{{ns}}}{tag}") if ns else info.find(tag)
                if elem is None or not elem.text:
                    errors.append(f"Missing required info element: <{tag}>")

            # Severity enumeration
            valid_severities = {"Extreme", "Severe", "Moderate", "Minor", "Unknown"}
            sev_elem = info.find(f"{{{ns}}}severity") if ns else info.find("severity")
            if sev_elem is not None and sev_elem.text not in valid_severities:
                errors.append(f"Invalid severity '{sev_elem.text}', must be one of {valid_severities}")

            # Urgency enumeration
            valid_urgencies = {"Immediate", "Expected", "Future", "Past", "Unknown"}
            urg_elem = info.find(f"{{{ns}}}urgency") if ns else info.find("urgency")
            if urg_elem is not None and urg_elem.text not in valid_urgencies:
                errors.append(f"Invalid urgency '{urg_elem.text}', must be one of {valid_urgencies}")

            # Certainty enumeration
            valid_certainties = {"Observed", "Likely", "Possible", "Unlikely", "Unknown"}
            cert_elem = info.find(f"{{{ns}}}certainty") if ns else info.find("certainty")
            if cert_elem is not None and cert_elem.text not in valid_certainties:
                errors.append(f"Invalid certainty '{cert_elem.text}', must be one of {valid_certainties}")

            # Area block validation
            area_elems = info.findall(f"{{{ns}}}area") if ns else info.findall("area")
            for area in area_elems:
                poly_elem = area.find(f"{{{ns}}}polygon") if ns else area.find("polygon")
                if poly_elem is not None and poly_elem.text:
                    coords = poly_elem.text.strip().split()
                    if len(coords) < 4:
                        errors.append(f"Polygon must have at least 4 coordinate pairs, got {len(coords)}")
                    if coords and coords[0] != coords[-1]:
                        errors.append("Polygon must be closed (first and last coordinate pairs must match)")

    return len(errors) == 0, errors
