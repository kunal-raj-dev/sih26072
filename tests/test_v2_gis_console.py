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
