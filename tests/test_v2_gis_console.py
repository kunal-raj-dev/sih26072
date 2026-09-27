"""Unit and integration test suite for Phase V2-9: Dual-Mode WebGL GIS Forecaster & DDMA Console.

Verifies:
1. TASK-V2-9.1: Dual-Persona Operational Toggle
   - Persona switcher buttons: #persona-imd and #persona-ddma in web/index.html.
   - JavaScript implementation of setPersona(persona) in web/app.js.
   - Persistent storage key 'vajra_ui_persona' in localStorage.
   - CSS display rules for .persona-imd-only and .persona-ddma-only in web/style.css.
   - Web Audio synthesizer chime function playAlertChime and toggle #chk-audio-chime.
   - One-click CAP 1.2 broadcast trigger #btn-dispatch-cap and overview card #ddma-summary-card.
2. TASK-V2-9.2: 60 FPS MapLibre GL Convective Plume & Advection Layers
   - GPU-accelerated raster layers with linear resampling and fast fade durations.
   - Projected vector tracks and expanding uncertainty cones (15, 30, 45, 60 min lead waypoints).
   - Anisotropic plume visualization and administrative block choropleths.
3. TASK-V2-9.3: Interactive Temporal Nowcast Scrubber & Verification Slider
   - Timeline looping toggle (#loop-btn) and loop logic in startPlayback.
   - Split-screen verification slider (#compare-slider, #compare-val) for nowcast vs observed field crossfade.
"""

from __future__ import annotations

from pathlib import Path
import pytest


@pytest.fixture(scope="module")
def web_assets():
    web_dir = Path("web")
    html = (web_dir / "index.html").read_text(encoding="utf-8")
    css = (web_dir / "style.css").read_text(encoding="utf-8")
    js = (web_dir / "app.js").read_text(encoding="utf-8")
    return {"html": html, "css": css, "js": js}


def test_dual_persona_toggle_elements(web_assets):
    """Verify HTML and CSS elements for the dual-persona operational toggle."""
    html = web_assets["html"]
    css = web_assets["css"]
    js = web_assets["js"]

    # 1. HTML buttons in topbar
    assert 'id="persona-imd"' in html
    assert 'id="persona-ddma"' in html
    assert 'class="persona-switcher"' in html

    # 2. CSS persona rules
    assert ".persona-switcher" in css
    assert ".persona-btn" in css
    assert "body.persona-ddma" in css
    assert "body.persona-imd" in css

    # 3. JavaScript logic
    assert "function setPersona" in js or "setPersona(" in js
    assert "vajra_ui_persona" in js
    assert "playAlertChime" in js


def test_ddma_disaster_management_portal_features(web_assets):
    """Verify DDMA civil protection features: 1-click CAP dispatch, audio chime, and overview card."""
    html = web_assets["html"]
    js = web_assets["js"]

    # 1. 1-click broadcast button and audio chime
    assert 'id="btn-dispatch-cap"' in html
    assert 'id="chk-audio-chime"' in html
    assert 'id="ddma-summary-card"' in html
    assert 'id="ddma-impact-stats"' in html

    # 2. JS dispatch and audio chime synthesis
    assert "btn-dispatch-cap" in js
    assert "AudioContext" in js
    assert "createOscillator" in js
    assert "playAlertChime" in js


def test_convective_plume_and_advection_layers(web_assets):
    """Verify MapLibre GL layer configuration for 60 FPS smooth rendering."""
    js = web_assets["js"]

    # 1. Raster resampling & fade duration for 60 FPS smoothness
    assert '"raster-resampling": "linear"' in js
    assert '"raster-fade-duration"' in js

    # 2. Cones, tracks, and CI layers
    assert 'map.addSource("cones"' in js
    assert 'map.addSource("tracks"' in js
    assert 'map.addSource("cells"' in js
    assert 'map.addSource("ci-candidates"' in js


def test_temporal_scrubber_loop_and_split_verification_slider(web_assets):
    """Verify timeline loop control and split-screen verification slider."""
    html = web_assets["html"]
    js = web_assets["js"]

    # 1. Loop playback control
    assert 'id="loop-btn"' in html
    assert "loop-btn" in js
    assert "state.loop" in js

    # 2. Split-screen verification slider
    assert 'id="compare-slider"' in html
    assert 'id="compare-val"' in html
    assert "compare-slider" in js


def test_phase_0_to_5_implementation_integrity(web_assets):
    """Verify that all Phase 0 through 5 roadmap requirements are implemented."""
    html = web_assets["html"]
    css = web_assets["css"]
    js = web_assets["js"]

    # Phase 0: Demo-critical correctness
    assert "valid_from" in js and "valid_until" in js  # T0.1 filter
    assert "roc_auc || 0.86" not in js  # T0.3 fabricated fallback removed
    assert "bihar_squall_2026" in js  # T0.4 canonical event
    assert "prewarmBenchmark" in js  # T0.5 prewarm SEVIR benchmark

    # Phase 1: Timeline narrative instrument
    assert 'id="timeline-axis"' in html
    assert ".tl-seg-observed" in css
    assert ".tl-seg-forecast" in css
    assert 'id="tl-markers"' in html
    assert "tl-stage-" in js
    assert "tl-peak" in js
    assert "tl-verdict" in js
    assert "lead-30" in html and "lead-60" in html

    # Phase 2: Threat hero + linkage
    assert 'id="threat-hero"' in html
    assert "renderThreatHero" in js
    assert "hero-hazard" in css
    assert "hero-p" in css
    assert "hero-why" in css
    assert "dqChips" in js
    assert "locateAlert" in js
    assert "locateAlertById" in js

    # Phase 3: Presets & hierarchy
    assert 'id="preset-observe"' in html
    assert 'id="preset-nowcast"' in html
    assert 'id="preset-compare"' in html
    assert "MAP_PRESETS" in js
    assert "applyPreset" in js
    assert 'details class="expert-drawer"' in html
    assert "renderLegend" in js
    assert "updateCellLabels" in js

    # Phase 4: Projector legibility & design tokens
    assert "--fs-hero: 28px;" in css
    assert "--fs-body: 16px;" in css
    assert "--imd-red" in css
    assert "--imd-orange" in css
    assert "overflow-x: hidden" in css
    assert "Predicts lightning 30" in html

    # Phase 5: Verification moment
    assert "alertVerdict" in js
    assert "flashCountInWindow" in js
    assert 'id="verify-strip"' in html
    assert 'id="vs-numbers"' in html
    assert 'id="vs-reliability"' in html
    assert "renderReliabilitySpark" in js
    assert "openScoreboardModal" in js
    assert "BSS vs CLIMATOLOGY" in js


def test_phase_6_ddma_persona_completion(web_assets):
    """Verify Phase P6 DDMA Persona Completion: Overview recompute, block tinting, chime gating, shared verification."""
    html = web_assets["html"]
    css = web_assets["css"]
    js = web_assets["js"]

    # T6.1: Overview Recompute & Honest Reporting
    assert "ddma-impact-stats" in html
    assert "ddma-summary-card" in html
    assert "sopDirectives" in js or "SOP" in js
    assert "IMD ACTION" in js or "IMMEDIATE ACTION" in js
    assert "PREPAREDNESS" in js
    assert "No administrative blocks under warning" in js or "convective core tracking outside" in js
    assert "(+${blks.length - 4} more)" in js or "more)" in js

    # T6.2: Block Stage Tinting on Map
    assert 'map.addSource("alert-blocks-tint"' in js
    assert '"alert-blocks-tint-fill"' in js
    assert '"alert-blocks-tint-line"' in js
    assert "updateAlertBlocksTint(" in js
    assert "updateAlertBlocksTint(active)" in js
    assert "STAGE_COLOR" in js
    assert "#ef4444" in js and "#f97316" in js and "#eab308" in js
    assert "getAdminBlocksFC" in js
    assert "alert-blocks-tint-fill" in js

    # T6.3: Chime Escalation Gating
    assert "_lastChimeStage" in js
    assert "currentRank > lastRank" in js or "isEscalation" in js
    assert "escalate-pulse" in js
    assert ".ddma-summary-card.escalate-pulse" in css
    assert "ddmaEscalatePulse" in css

    # T6.4: Persona-Shared Verification
    assert "ddma-verify-badge" in js
    assert ".ddma-verify-badge" in css
    assert 'id="verify-strip"' in html
    # Ensure #verify-strip is NOT hidden in DDMA mode
    assert 'id="verify-strip" class="persona-imd-only"' not in html
    assert 'id="verify-strip" class="persona-ddma-only"' not in html

    # CSS Stage-Themed Border on DDMA card
    assert '.ddma-summary-card[data-stage="RED"]' in css
    assert '.ddma-summary-card[data-stage="ORANGE"]' in css
    assert '.ddma-summary-card[data-stage="YELLOW"]' in css
    assert '.ddma-summary-card[data-stage="GREEN"]' in css


def test_phase_7_presentation_rail_and_rehearsal_hardening(web_assets):
    """Verify Phase P7: 8-moment presentation rail sequencer, keyboard map, and rehearsal hardening."""
    html = web_assets["html"]
    css = web_assets["css"]
    js = web_assets["js"]

    # T7.1: Demo Rail UI & 8 Step Sequencer
    assert 'id="demo-rail"' in html
    assert 'id="rail-caption"' in html
    assert 'id="rail-pill"' in html
    assert 'data-step="1"' in html and 'data-step="8"' in html
    assert "DEMO_STEPS" in js
    assert "runDemoStep" in js
    assert "stepDemoRail" in js
    assert "setRailVisible" in js
    assert ".demo-rail" in css
    assert ".rail-chip" in css
    assert ".rail-pill" in css
    assert ".map-wrap" in css

    # 8 Distinct Judge Moments in Sequencer
    for moment in ("ORIENT", "OBSERVE", "PREDICT", "CI", "WARN", "DEGRADE", "VERIFY", "AUDIT"):
        assert moment in js
        assert moment in html

    # T7.2: Keyboard Shortcuts & Cheat-Sheet Modal
    assert 'id="shortcuts-modal"' in html
    assert "toggleShortcutsModal" in js
    assert "openShortcutsModal" in js
    assert "closeModals" in js
    assert 'e.key >= "1" && e.key <= "8"' in js
    assert 'e.key === "["' in js or "stepDemoRail" in js
    assert 'e.key === "]"' in js or "stepDemoRail" in js
    assert 'e.key === "r"' in js or 'e.key === "R"' in js
    assert 'e.key === "?"' in js
    assert "<kbd>" in html

    # T7.3: Offline Basemap Resilience & Dark Canvas
    assert "background: #0b0f14" in css or "background-color: #0b0f14" in css or "#0b0f14" in css
    assert 'map.on("error"' in js
    assert "fitToEvent" in js

    # T7.4: Error Toasts & Handled Replays
    assert "loadEventReplay" in js
    assert "showToast" in js

    # T7.5: Pre-warmed Benchmark & Fallback Case Studies
    assert "prewarmBenchmark" in js
    assert "sevir_s810646" in js
    assert "himalayan_cloudburst_2026" in js


def test_phase_8_accessibility_performance_and_polish(web_assets):
    """Verify Phase P8: Accessibility, focus trap, reduced motion, in-memory fetch deduplication, and QA matrix."""
    html = web_assets["html"]
    css = web_assets["css"]
    js = web_assets["js"]

    # T8.1: A11y Pass & Keyboard Focus Trap
    assert 'class="skip-link"' in html
    assert ".skip-link" in css
    assert 'role="banner"' in html
    assert 'role="contentinfo"' in html
    assert 'aria-current="step"' in html
    assert 'aria-hidden="true"' in html
    assert "trapFocusInModal" in js
    assert "_lastFocusedElement" in js
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-label="Close dialog"' in html
    assert 'aria-label="Play or Pause replay (Space)"' in html
    assert 'aria-label="Previous demo moment ([)"' in html
    assert 'aria-label="Next demo moment (])"' in html
    assert 'aria-label="Reset to Zero State (R)"' in html
    assert 'aria-label="Restore Presentation Demo Rail (1–8)"' in html
    assert 'role="status" aria-live="polite"' in html

    # prefers-reduced-motion CSS & JS
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "animation-duration: 0.01ms !important" in css
    assert "getMotionDuration" in js
    assert "prefers-reduced-motion" in js

    # T8.2: In-Memory Fetch Dedupe & Render Budget Profiling
    assert "_inFlightGets" in js
    assert "_apiCache" in js
    assert "isCacheableGet" in js
    assert "clearApiCache" in js
    assert "getSharedAudioContext" in js
    assert "pulseStormCell" in js
    assert "_lastRenderMs" in js
    assert "tRenderStart" in js

    # T8.3: QA Matrix & Display Resolution Targets
    # 1366x768 Projector and 1920x1080 HD
    assert "@media (max-width: 1400px)" in css
    assert "@media (max-height: 800px)" in css
    assert "overflow-x: hidden" in css
    # 3 Events & 3 Presets
    for eid in ("bihar_squall_2026", "himalayan_cloudburst_2026", "sevir_s810646"):
        assert eid in js
    for preset in ("OBSERVE", "NOWCAST", "COMPARE"):
        assert preset in js


def test_public_and_web_asset_synchronization():
    """Verify that web/ (local FastAPI) and public/ (Vercel static) remain 100% synchronized."""
    for filename in ("app.js", "index.html", "style.css"):
        web_file = Path("web") / filename
        public_file = Path("public") / filename
        assert web_file.exists(), f"Missing {web_file}"
        assert public_file.exists(), f"Missing {public_file}"
        assert web_file.read_text(encoding="utf-8") == public_file.read_text(encoding="utf-8"), (
            f"Desynchronization detected between web/{filename} and public/{filename}"
        )


def test_phase_9_final_presentation_readiness_and_e2e_contracts(settings):
    """Verify Phase P9: Documentation sync, peak-cycle bulletin geocoding, CAP/Atom exports, and scoreboard contracts."""
    from fastapi.testclient import TestClient
    from vajra.api.app import create_app

    # T9.1 & T9.2: Documentation & Playbook Alignment
    demo_doc = Path("docs/DEMO.md").read_text(encoding="utf-8")
    plan_doc = Path("docs/FRONTEND_IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")
    master_doc = Path("MASTER.md").read_text(encoding="utf-8")

    for moment in ("① ORIENT", "② OBSERVE", "③ PREDICT", "④ CI", "⑤ WARN", "⑥ DEGRADE", "⑦ VERIFY", "⑧ AUDIT"):
        assert moment in demo_doc
    assert "44-district / 148-block" in demo_doc or "44 districts" in master_doc
    assert "+0.498" in demo_doc and "+0.374" in demo_doc
    assert "COMPLETE & VERIFIED" in plan_doc
    assert "COMPLETE & VERIFIED" in master_doc

    # T9.2 & T9.3: End-to-End API Contracts for Bihar Canonical Replay (Moments 1–5)
    client = TestClient(create_app(settings))
    run_res = client.post("/api/v1/replay/bihar_squall_2026/run")
    assert run_res.status_code == 200
    run_data = run_res.json()
    run_id = run_data["run_id"]

    fcs = client.get(f"/api/v1/runs/{run_id}/forecasts").json()
    assert len(fcs) > 0

    # Peak-threat cycle selection (same logic as app.js loadRun)
    peak_fc = max(
        fcs,
        key=lambda f: max((s.get("p_flash_max") or 0.0) for s in (f.get("steps") or [{}])),
    )
    peak_fid = peak_fc["id"]

    # Bulletin at peak cycle must include active cycle alerts, districts, blocks, and exposed population
    bul_res = client.get(f"/api/v1/forecasts/{peak_fid}/bulletin?preset=operational")
    assert bul_res.status_code == 200
    bul = bul_res.json()
    assert bul["alerts_count"] >= 1
    assert len(bul["affected_districts"]) >= 1
    assert len(bul["affected_blocks"]) >= 1
    assert bul["total_population_exposed"] > 0
    assert bul["max_stage"] in ("YELLOW", "ORANGE", "RED")

    # CAP 1.2 XML, JSON, and Atom 1.0 feed verification
    first_alert_id = bul["alerts"][0]["id"]
    cap_xml = client.get(f"/api/v1/alerts/{first_alert_id}/cap.xml")
    assert cap_xml.status_code == 200
    assert "urn:oasis:names:tc:emergency:cap:1.2" in cap_xml.text

    cap_json = client.get(f"/api/v1/alerts/{first_alert_id}/cap.json")
    assert cap_json.status_code == 200
    assert cap_json.json()["identifier"] == first_alert_id

    atom_feed = client.get(f"/api/v1/alerts/feed.atom?run_id={run_id}")
    assert atom_feed.status_code == 200
    assert "<feed" in atom_feed.text

    # Scoreboard alerts_count contract
    sb_res = client.get(f"/api/v1/runs/{run_id}/scoreboard")
    assert sb_res.status_code == 200
    sb = sb_res.json()
    assert sb["alerts_count"] >= 1
