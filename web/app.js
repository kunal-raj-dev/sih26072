/* Project Vajra — operational decision-support map (vertical slice). */
"use strict";

const API = "/api/v1";
const $ = (id) => document.getElementById(id);

const state = {
  events: [], eventId: null, runId: null,
  forecasts: [], index: 0, lead: 60,
  playing: false, timer: null, flashes: null,
  gridBounds: null,
};

// ---------- map ----------
// CARTO Basemaps key is served by the API config endpoint (env-backed via
// VAJRA_BASEMAPS__CARTO_KEY); it is never hardcoded here. Without it the
// keyless URL is used and the map still renders.
const cartoTiles = (style) =>
  `https://basemaps.cartocdn.com/${style}/{z}/{x}/{y}@2x.png`;
const basemapKeyPromise = fetch(`${API}/config`)
  .then((r) => (r.ok ? r.json() : null))
  .then((cfg) => cfg && cfg.carto_basemap_key)
  .catch(() => null);

const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    sources: {
      basemap: {
        type: "raster",
        tiles: [cartoTiles("dark_all")],
        tileSize: 256, attribution: "© OpenStreetMap contributors, © CARTO",
      },
    },
    layers: [{ id: "basemap", type: "raster", source: "basemap" }],
  },
  center: [85.2, 25.6], zoom: 5.4,
  attributionControl: { compact: true },
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
map.once("load", async () => {
  const key = await basemapKeyPromise;
  if (key) {
    map.getSource("basemap").setTiles(
      [`${cartoTiles("dark_all")}?key=${encodeURIComponent(key)}`]);
  }
});

const PLACEHOLDER_PNG =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";
// Non-degenerate default box: MapLibre divides by coordinate spread at source creation.
const DEFAULT_BOX = [[65, 5], [99, 5], [99, 39], [65, 39]];

map.on("load", () => {
  map.addSource("prob-overlay", { type: "image", url: PLACEHOLDER_PNG, coordinates: DEFAULT_BOX });
  map.addLayer({ id: "prob-layer", type: "raster", source: "prob-overlay", paint: { "raster-opacity": 0.92 } });
  map.addSource("obs-overlay", { type: "image", url: PLACEHOLDER_PNG, coordinates: DEFAULT_BOX });
  map.addLayer({ id: "obs-layer", type: "raster", source: "obs-overlay", paint: { "raster-opacity": 0.55 } });
  map.addSource("live-radar", { type: "image", url: PLACEHOLDER_PNG, coordinates: DEFAULT_BOX });
  map.addLayer({ id: "live-radar-layer", type: "raster", source: "live-radar", paint: { "raster-opacity": 0.8 },
                 layout: { visibility: "none" } });
  map.addSource("cells", { type: "geojson", data: emptyFC() });
  map.addLayer({
    id: "cells-layer", type: "line", source: "cells",
    paint: { "line-color": "#ffd166", "line-width": 2 },
  });
  map.addLayer({
    id: "cells-fill", type: "fill", source: "cells",
    paint: { "fill-color": "#ffd166", "fill-opacity": ["case", ["boolean", ["feature-state", "hover"], false], 0.18, 0.06] },
  });
  map.addSource("flashes", { type: "geojson", data: emptyFC() });
  map.addLayer({
    id: "flashes-layer", type: "circle", source: "flashes",
    paint: { "circle-radius": 3.2, "circle-color": "#ffffff", "circle-stroke-color": "#93c5fd", "circle-stroke-width": 1 },
  });
  map.on("mouseenter", "cells-fill", () => map.getCanvas().style.cursor = "pointer");
  map.on("mouseleave", "cells-fill", () => map.getCanvas().style.cursor = "");
  map.on("click", "cells-fill", cellPopup);
});

function emptyFC() { return { type: "FeatureCollection", features: [] }; }

function gridToBounds(grid) {
  if (!grid) return [[68, 5], [98, 5], [98, 38], [68, 38]];
  const halfLat = Math.abs(grid.dlat) / 2, halfLon = grid.dlon / 2;
  const north = grid.lat0 + halfLat;
  const south = grid.lat0 + grid.dlat * (grid.nlat - 1) - halfLat;
  const west = grid.lon0 - halfLon;
  const east = grid.lon0 + grid.dlon * (grid.nlon - 1) + halfLon;
  return [[west, north], [east, north], [east, south], [west, south]];
}

function fitToGrid(grid) {
  const b = gridToBounds(grid);
  map.fitBounds([[b[3][0], b[2][1]], [b[1][0], b[0][1]]], { padding: 40, duration: 600 });
}

// ---------- api helpers ----------
async function api(path, opts) {
  const r = await fetch(API + path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* keep statusText */ }
    throw new Error(msg);
  }
  return r.json();
}

// ---------- events & run ----------
async function loadEvents() {
  state.events = await api("/events");
  const sel = $("event-select");
  sel.innerHTML = "";
  for (const e of state.events) {
    const opt = document.createElement("option");
    opt.value = e.id;
    opt.textContent = `${e.title} [${e.mode}]`;
    sel.appendChild(opt);
  }
  state.eventId = sel.value || null;
  setModeBadge(state.events.find(e => e.id === state.eventId)?.mode);
}

function setModeBadge(mode) {
  const el = $("mode-badge");
  el.textContent = mode || "—";
  el.dataset.mode = mode || "";
}

$("event-select").onchange = () => {
  state.eventId = $("event-select").value;
  setModeBadge(state.events.find(e => e.id === state.eventId)?.mode);
};

$("run-btn").onclick = async () => {
  $("run-btn").disabled = true;
  $("run-status").textContent = "Running replay…";
  try {
    const res = await api(`/replay/${encodeURIComponent(state.eventId)}/run`, { method: "POST" });
    state.runId = res.run_id;
    $("run-status").textContent = `Run ${res.run_id}: ${res.cycles} cycles, ${res.alerts} alerts.`;
    await loadRun();
  } catch (e) {
    $("run-status").textContent = `Failed: ${e.message}`;
  } finally {
    $("run-btn").disabled = false;
  }
};

async function loadRun() {
  state.forecasts = await api(`/runs/${state.runId}/forecasts`);
  state.index = Math.floor(state.forecasts.length / 3);
  $("timeline").max = Math.max(0, state.forecasts.length - 1);
  $("timeline").value = state.index;
  const run = await api(`/runs/${state.runId}`);
  renderVerification(run.verification);
  state.flashes = await api(`/events/${encodeURIComponent(state.eventId)}/flashes.geojson`);
  state._gridCache = {};
  // Recenter the map on this event's domain before rendering.
  const first = state.forecasts[0];
  if (first) {
    try {
      const detail = await api(`/forecasts/${first.id}`);
      fitToGrid(detail.grid);
    } catch (_) { /* keep current view */ }
  }
  renderStep();
}

// ---------- timeline ----------
$("timeline").oninput = () => { state.index = +$("timeline").value; renderStep(); };
$("prev-btn").onclick = () => stepBy(-1);
$("next-btn").onclick = () => stepBy(1);
$("play-btn").onclick = () => {
  state.playing = !state.playing;
  $("play-btn").textContent = state.playing ? "❚❚" : "▶";
  if (state.playing) state.timer = setInterval(() => stepBy(1), 900);
  else clearInterval(state.timer);
};
$("lead-select").onchange = () => { state.lead = +$("lead-select").value; renderStep(); };

function stepBy(d) {
  if (!state.forecasts.length) return;
  state.index = Math.min(state.forecasts.length - 1, Math.max(0, state.index + d));
  $("timeline").value = state.index;
  renderStep();
}

function currentForecast() { return state.forecasts[state.index]; }

function renderStep() {
  const f = currentForecast();
  if (!f) return;
  const t = new Date(f.replay_time);
  $("clock").textContent = t.toISOString().slice(11, 16) + "Z";
  setModeBadge(f.mode);
  $("rung-badge").textContent = f.fallback_rung;
  $("conf-badge").textContent = `conf ${(f.confidence * 100).toFixed(0)}%`;
  $("cycle-note").textContent =
    `issued ${t.toISOString().slice(0, 16).replace("T", " ")}Z · modalities: ${f.modalities_used.join(", ") || "none"}` +
    (f.notes && f.notes.length ? ` · ${f.notes.join("; ")}` : "");

  // probability overlay
  const probOn = $("lyr-prob").checked && f.field_urls && f.field_urls[String(state.lead)];
  const probSrc = map.getSource("prob-overlay");
  if (probOn) {
    getGridBounds(f.id).then((coords) => {
      probSrc.updateImage({ url: probOn, coordinates: coords });
    }).catch(() => { /* forecast detail unavailable */ });
    map.setLayoutProperty("prob-layer", "visibility", "visible");
  } else {
    map.setLayoutProperty("prob-layer", "visibility", "none");
  }
  map.setLayoutProperty("obs-layer", "visibility",
    $("lyr-obs").checked ? "visible" : "none");

  // cells
  const detailP = api(`/forecasts/${f.id}/cells.geojson?lead=${state.lead}`);
  detailP.then((fc) => {
    map.getSource("cells").setData(fc);
  }).catch(() => map.getSource("cells").setData(emptyFC()));

  // actual flashes in (t, t+lead]
  if (state.flashes && $("lyr-flashes").checked) {
    const t0 = t.getTime(), t1 = t0 + state.lead * 60000;
    const feats = state.flashes.features.filter(
      (ft) => ft.properties.t > t0 && ft.properties.t <= t1);
    map.getSource("flashes").setData({ type: "FeatureCollection", features: feats });
  } else {
    map.getSource("flashes").setData(emptyFC());
  }
  renderAlerts(f);
  loadObsOverlay(f);
}

async function loadObsOverlay(f) {
  if (!$("lyr-obs").checked) return;
  try {
    const detail = await api(`/forecasts/${f.id}`);
    const coords = gridToBounds(detail.grid);
    map.getSource("obs-overlay").updateImage({
      url: `${API}/forecasts/${f.id}/obs.png`, coordinates: coords,
    });
  } catch (_) { /* obs render not available */ }
}

function getGridBounds(fid) {
  if (!state._gridCache) state._gridCache = {};
  if (!state._gridCache[fid]) {
    state._gridCache[fid] = api(`/forecasts/${fid}`).then((d) => gridToBounds(d.grid));
  }
  return state._gridCache[fid];
}

// ---------- alerts ----------
async function renderAlerts(f) {
  const preset = $("preset-select").value;
  const alerts = await api(`/alerts?run_id=${state.runId}&preset=${preset}&lead_minutes=${state.lead}`);
  const t = new Date(f.replay_time).getTime();
  const active = alerts.filter((a) => {
    const issued = new Date(a.issued_at).getTime();
    return Math.abs(issued - t) < 30 * 60000; // alerts relevant near this cycle
  });
  const list = $("alerts-list");
  if (!active.length) { list.innerHTML = '<div class="muted">no alerts in this window</div>'; return; }
  list.innerHTML = active.slice(-6).reverse().map((a) => `
    <div class="alert" data-severity="${a.severity}">
      <div class="head"><span>${a.severity} · ${a.hazard}</span><span class="sev">+${a.lead_minutes}min · P=${a.probability}</span></div>
      <div class="reason">${a.region_name} — ${a.reason}</div>
      <div class="factors">${Object.entries(a.contributing_signals).map(([k, v]) => `${k}=${v}`).join(" · ")}</div>
      <div class="action">▸ ${a.recommended_action}</div>
      <div class="muted small">model ${a.model_version} · mode ${a.mode} · confidence ${a.confidence}</div>
    </div>`).join("");
}
$("preset-select").onchange = () => renderStep();

// ---------- verification ----------
function renderVerification(v) {
  const tbody = $("verif-table").querySelector("tbody");
  if (!v || !v.samples) { tbody.innerHTML = '<tr><td colspan="6" class="muted">no samples</td></tr>'; return; }
  tbody.innerHTML = "";
  for (const [lead, s] of Object.entries(v.samples)) {
    const p = s.map((x) => x.p), y = s.map((x) => x.y);
    tbody.insertAdjacentHTML("beforeend",
      `<tr><td>+${lead}m</td><td>${s.length}</td>
       <td>${fmt(v.metrics?.[lead]?.pod)}</td><td>${fmt(v.metrics?.[lead]?.far)}</td>
       <td>${fmt(v.metrics?.[lead]?.csi)}</td><td>${fmt(v.metrics?.[lead]?.bss)}</td></tr>`);
  }
}
const fmt = (x) => (x == null || Number.isNaN(x) ? "—" : (+x).toFixed(2));

// ---------- live radar ----------
$("lyr-live").onchange = async () => {
  const on = $("lyr-live").checked;
  map.setLayoutProperty("live-radar-layer", "visibility", on ? "visible" : "none");
  if (!on) return;
  const station = $("station-select").value;
  try {
    // Probe through our proxy; on failure show an honest message.
    const r = await fetch(`${API}/observations/radar/${station}.gif`, { method: "HEAD" });
    if (!r.ok) throw new Error(await r.text());
    map.getSource("live-radar").updateImage({
      url: `${API}/observations/radar/${station}.gif`,
      coordinates: [[68, 5], [98, 5], [98, 38], [68, 38]],
    });
    note("IMD radar GIF displayed for visual reference only — not numeric input to the model (LIVE).");
  } catch (e) {
    note(`IMD radar unavailable: ${String(e.message).slice(0, 140)}`);
    map.setLayoutProperty("live-radar-layer", "visibility", "none");
    $("lyr-live").checked = false;
  }
};
$("station-select").onchange = () => { if ($("lyr-live").checked) { $("lyr-live").checked = false; $("lyr-live").onchange(); } };

function note(msg) { $("cycle-note").textContent = msg; }

["lyr-prob", "lyr-obs", "lyr-cells", "lyr-flashes"].forEach((id) => {
  $(id).onchange = () => {
    map.setLayoutProperty("prob-layer", "visibility", $("lyr-prob").checked ? "visible" : "none");
    map.setLayoutProperty("obs-layer", "visibility", $("lyr-obs").checked ? "visible" : "none");
    map.setLayoutProperty("cells-layer", "visibility", $("lyr-cells").checked ? "visible" : "none");
    map.setLayoutProperty("cells-fill", "visibility", $("lyr-cells").checked ? "visible" : "none");
    renderStep();
  };
});

function cellPopup(e) {
  const p = e.features[0].properties;
  new maplibregl.Popup()
    .setLngLat([p.centroid_lon ?? e.lngLat.lng, p.centroid_lat ?? e.lngLat.lat])
    .setHTML(`<strong>Cell ${p.cell_id}</strong><br>
       max intensity (raw): ${p.max_intensity}<br>
       area: ${p.area_px} px · age: ${p.track_age} steps<br>
       motion: ${(+p.motion_dlat).toFixed(3)}/${(+p.motion_dlon).toFixed(3)} °/cycle<br>
       flash history: ${p.flash_history}<br>
       <span class="muted">geolocation: ${p.geo_note}</span>`)
    .addTo(map);
}

// also draw centroid points for popup targets
map.on("sourcedata", () => { /* no-op: popups attach to fill layer */ });

// ---------- data health ----------
async function loadHealth() {
  try {
    const items = await api("/data-health");
    $("data-health").innerHTML = items.map((h) =>
      `<div class="row"><span class="src">${h.source}</span>
       <span class="status-${h.status}">${h.status}</span></div>`).join("");
  } catch (e) { /* server not up */ }
}
loadHealth();
setInterval(loadHealth, 60000);

// ---------- boot ----------
(async function boot() {
  try {
    await loadEvents();
    // Auto-run the first synthetic event so the page is never empty.
    const sim = state.events.find((e) => e.mode === "SIMULATION");
    if (sim) {
      state.eventId = sim.id;
      $("event-select").value = sim.id;
      setModeBadge(sim.mode);
      $("run-status").textContent = "Auto-running the labelled SIMULATION event for a first look…";
      try {
        const res = await api(`/replay/${sim.id}/run`, { method: "POST" });
        state.runId = res.run_id;
        $("run-status").textContent = `Run ${res.run_id}: ${res.cycles} cycles, ${res.alerts} alerts (SIMULATION).`;
        await loadRun();
      } catch (e) {
        $("run-status").textContent = `Auto-run failed: ${e.message}`;
      }
    }
  } catch (e) {
    $("run-status").textContent = `API unreachable: ${e.message}`;
  }
})();
