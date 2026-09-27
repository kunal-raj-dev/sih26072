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

  // Convective Initiation (precursor) candidates
  map.addSource("ci-candidates", { type: "geojson", data: emptyFC() });
  map.addLayer({
    id: "ci-fill", type: "fill", source: "ci-candidates",
    paint: { "fill-color": "#00e5ff", "fill-opacity": 0.28 },
  });
  map.addLayer({
    id: "ci-layer", type: "line", source: "ci-candidates",
    paint: { "line-color": "#00e5ff", "line-width": 2.2, "line-dasharray": [3, 2] },
  });
  map.on("mouseenter", "ci-fill", () => map.getCanvas().style.cursor = "pointer");
  map.on("mouseleave", "ci-fill", () => map.getCanvas().style.cursor = "");
  map.on("click", "ci-fill", (e) => {
    if (!e.features || !e.features[0]) return;
    const p = e.features[0].properties;
    new maplibregl.Popup()
      .setLngLat(e.lngLat)
      .setHTML(`<strong>⚡ Convective Initiation (CI Precursor)</strong><br/>
                Cooling Rate: <strong>${p.cooling_rate_k_per_15m} K / 15m</strong><br/>
                Min Cloud-Top IR: <strong>${p.ir_brightness_temp_k} K</strong><br/>
                P(Initiation): <strong>${(p.p_initiation * 100).toFixed(0)}%</strong><br/>
                Est. Lead to First Flash: <strong>${p.estimated_lead_min} min</strong><br/>
                Area: <strong>${p.area_km2} km²</strong>`)
      .addTo(map);
  });

  // Uncertainty Overlay
  map.addSource("uncertainty-overlay", { type: "image", url: PLACEHOLDER_PNG, coordinates: DEFAULT_BOX });
  map.addLayer({
    id: "uncertainty-layer", type: "raster", source: "uncertainty-overlay",
    paint: { "raster-opacity": 0.65 },
    layout: { visibility: "none" },
  });

  map.on("mouseenter", "cells-fill", () => map.getCanvas().style.cursor = "pointer");
  map.on("mouseleave", "cells-fill", () => map.getCanvas().style.cursor = "");
  map.on("click", "cells-fill", cellPopup);

  // Administrative boundaries (Districts & Blocks)
  map.addSource("admin-districts", { type: "geojson", data: `${API}/admin/districts` });
  map.addSource("admin-blocks", { type: "geojson", data: `${API}/admin/blocks`, generateId: true });

  map.addLayer({
    id: "admin-blocks-fill", type: "fill", source: "admin-blocks",
    paint: {
      "fill-color": "#0284c7",
      "fill-opacity": ["case", ["boolean", ["feature-state", "hover"], false], 0.22, 0.0]
    },
  });
  map.addLayer({
    id: "admin-blocks-line", type: "line", source: "admin-blocks",
    paint: {
      "line-color": "#475569",
      "line-width": 0.9,
      "line-opacity": 0.45,
      "line-dasharray": [2, 2]
    },
  });
  map.addLayer({
    id: "admin-districts-line", type: "line", source: "admin-districts",
    paint: {
      "line-color": "#38bdf8",
      "line-width": 1.6,
      "line-opacity": 0.75
    },
  });

  let hoveredBlockId = null;
  const adminPopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });

  map.on("mousemove", "admin-blocks-fill", (e) => {
    if (e.features && e.features.length > 0) {
      if (hoveredBlockId !== null) {
        map.setFeatureState({ source: "admin-blocks", id: hoveredBlockId }, { hover: false });
      }
      hoveredBlockId = e.features[0].id;
      map.setFeatureState({ source: "admin-blocks", id: hoveredBlockId }, { hover: true });
      map.getCanvas().style.cursor = "pointer";

      const p = e.features[0].properties;
      const popStr = p.population ? Number(p.population).toLocaleString() : "—";
      adminPopup
        .setLngLat(e.lngLat)
        .setHTML(`<strong>${p.block || p.name} Block</strong><br>` +
                 `<span class="small muted">${p.district} District, ${p.state}</span><br>` +
                 `Pop: <strong>${popStr}</strong> · Area: ${p.area_sqkm || "—"} km²`)
        .addTo(map);
    }
  });

  map.on("mouseleave", "admin-blocks-fill", () => {
    if (hoveredBlockId !== null) {
      map.setFeatureState({ source: "admin-blocks", id: hoveredBlockId }, { hover: false });
    }
    hoveredBlockId = null;
    map.getCanvas().style.cursor = "";
    adminPopup.remove();
  });

  // 60-min Projected Storm Tracks and Uncertainty Cones
  map.addSource("cones", { type: "geojson", data: emptyFC() });
  map.addLayer({
    id: "cones-fill", type: "fill", source: "cones",
    paint: { "fill-color": "#f97316", "fill-opacity": 0.15 },
  });
  map.addLayer({
    id: "cones-line", type: "line", source: "cones",
    paint: { "line-color": "#f97316", "line-width": 1.2, "line-dasharray": [2, 1] },
  });

  map.addSource("tracks", { type: "geojson", data: emptyFC() });
  map.addLayer({
    id: "tracks-line", type: "line", source: "tracks",
    paint: { "line-color": "#fbbf24", "line-width": 2, "line-dasharray": [2, 2] },
  });

  // Multi-Radar Composite Layer
  map.addSource("radar-mosaic", { type: "image", url: `${API}/radar/mosaic/field.png`, coordinates: DEFAULT_BOX });
  map.addLayer({
    id: "radar-mosaic-layer", type: "raster", source: "radar-mosaic",
    paint: { "raster-opacity": 0.82 },
    layout: { visibility: "none" },
  });

  // Radar Range Rings (100 km & 250 km) & Stations
  map.addSource("radar-rings", { type: "geojson", data: `${API}/radar/rings.geojson` });
  map.addLayer({
    id: "radar-rings-line", type: "line", source: "radar-rings",
    filter: ["==", ["get", "type"], "range_ring"],
    paint: {
      "line-color": "#f59e0b",
      "line-width": 1.2,
      "line-opacity": 0.65,
      "line-dasharray": [3, 2],
    },
  });
  map.addLayer({
    id: "radar-stations-point", type: "circle", source: "radar-rings",
    filter: ["==", ["get", "type"], "station"],
    paint: {
      "circle-radius": 5,
      "circle-color": "#f59e0b",
      "circle-stroke-width": 2,
      "circle-stroke-color": "#ffffff",
    },
  });

  map.on("click", "radar-stations-point", (e) => {
    const p = e.features[0].properties;
    new maplibregl.Popup()
      .setLngLat(e.lngLat)
      .setHTML(`<strong>📡 ${p.name}</strong><br>` +
               `Band: ${p.band} · Alt: ${p.altitude_m} m<br>` +
               `Surveillance Range: <strong>250 km</strong> (Quantitative: 100 km)<br>` +
               `<span style="color:#22c55e;font-weight:600;">Status: ${p.status}</span>`)
      .addTo(map);
  });
  map.on("mouseenter", "radar-stations-point", () => map.getCanvas().style.cursor = "pointer");
  map.on("mouseleave", "radar-stations-point", () => map.getCanvas().style.cursor = "");
});

function emptyFC() { return { type: "FeatureCollection", features: [] }; }

function gridToBounds(grid) {
  if (!grid) return [[68, 5], [98, 5], [98, 38], [68, 38]];
  const halfLat = Math.abs(grid.dlat) / 2;
  const halfLon = Math.abs(grid.dlon) / 2;
  const latTop = grid.dlat < 0 ? grid.lat0 + halfLat : grid.lat0 - halfLat;
  const latBottom = grid.lat0 + grid.dlat * (grid.nlat - 1) + (grid.dlat < 0 ? -halfLat : halfLat);
  const lonLeft = grid.lon0 - halfLon;
  const lonRight = grid.lon0 + (grid.dlon > 0 ? grid.dlon : Math.abs(grid.dlon)) * (grid.nlon - 1) + halfLon;
  return [[lonLeft, latTop], [lonRight, latTop], [lonRight, latBottom], [lonLeft, latBottom]];
}

function fitToGrid(grid) {
  const b = gridToBounds(grid);
  const minLon = Math.min(b[0][0], b[1][0], b[2][0], b[3][0]);
  const maxLon = Math.max(b[0][0], b[1][0], b[2][0], b[3][0]);
  const minLat = Math.min(b[0][1], b[1][1], b[2][1], b[3][1]);
  const maxLat = Math.max(b[0][1], b[1][1], b[2][1], b[3][1]);
  map.fitBounds([[minLon, minLat], [maxLon, maxLat]], { padding: 40, duration: 600 });
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

  // cells, projected tracks & uncertainty cones
  const detailP = api(`/forecasts/${f.id}/cells.geojson?lead=${state.lead}`);
  detailP.then((fc) => {
    map.getSource("cells").setData(fc);

    const showCones = $("lyr-cones") ? $("lyr-cones").checked : true;
    if (showCones) {
      const coneFeats = [];
      const trackFeats = [];
      for (const feat of fc.features) {
        const cone = feat.properties.uncertainty_cone;
        if (cone && cone.length >= 3) {
          coneFeats.push({
            type: "Feature",
            geometry: { type: "Polygon", coordinates: [cone] },
            properties: { cell_id: feat.properties.cell_id },
          });
        }
        const trk = feat.properties.projected_track;
        if (trk && trk.length >= 2) {
          trackFeats.push({
            type: "Feature",
            geometry: { type: "LineString", coordinates: trk },
            properties: { cell_id: feat.properties.cell_id },
          });
        }
      }
      map.getSource("cones").setData({ type: "FeatureCollection", features: coneFeats });
      map.getSource("tracks").setData({ type: "FeatureCollection", features: trackFeats });
    } else {
      map.getSource("cones").setData(emptyFC());
      map.getSource("tracks").setData(emptyFC());
    }
  }).catch(() => {
    map.getSource("cells").setData(emptyFC());
    map.getSource("cones").setData(emptyFC());
    map.getSource("tracks").setData(emptyFC());
  });

  // actual flashes in (t, t+lead]
  if (state.flashes && $("lyr-flashes").checked) {
    const t0 = t.getTime(), t1 = t0 + state.lead * 60000;
    const feats = state.flashes.features.filter(
      (ft) => ft.properties.t > t0 && ft.properties.t <= t1);
    map.getSource("flashes").setData({ type: "FeatureCollection", features: feats });
  } else {
    map.getSource("flashes").setData(emptyFC());
  }
  // Convective initiation candidates
  const ciOn = $("lyr-ci") ? $("lyr-ci").checked : true;
  if (ciOn) {
    api(`/forecasts/${f.id}/ci.geojson`).then((cifc) => {
      map.getSource("ci-candidates").setData(cifc);
      map.setLayoutProperty("ci-layer", "visibility", "visible");
      map.setLayoutProperty("ci-fill", "visibility", "visible");
    }).catch(() => {
      map.getSource("ci-candidates").setData(emptyFC());
    });
  } else {
    map.setLayoutProperty("ci-layer", "visibility", "none");
    map.setLayoutProperty("ci-fill", "visibility", "none");
  }

  // Uncertainty overlay
  const uncertOn = $("lyr-uncertainty") ? $("lyr-uncertainty").checked : false;
  if (uncertOn) {
    getGridBounds(f.id).then((coords) => {
      map.getSource("uncertainty-overlay").updateImage({
        url: `${API}/forecasts/${f.id}/uncertainty.png`,
        coordinates: coords,
      });
      map.setLayoutProperty("uncertainty-layer", "visibility", "visible");
    }).catch(() => {
      map.setLayoutProperty("uncertainty-layer", "visibility", "none");
    });
  } else {
    map.setLayoutProperty("uncertainty-layer", "visibility", "none");
  }

  renderAlerts(f);
  loadObsOverlay(f);
}

async function loadObsOverlay(f) {
  if ($("lyr-obs").checked) {
    try {
      const detail = await api(`/forecasts/${f.id}`);
      const coords = gridToBounds(detail.grid);
      map.getSource("obs-overlay").updateImage({
        url: `${API}/forecasts/${f.id}/obs.png`, coordinates: coords,
      });
    } catch (_) { /* obs render not available */ }
  }

  // Multi-Radar Composite Overlay
  const mosaicOn = $("lyr-radar-mosaic") && $("lyr-radar-mosaic").checked;
  if (mosaicOn) {
    try {
      const coords = await getGridBounds(f.id);
      map.getSource("radar-mosaic").updateImage({
        url: `${API}/radar/mosaic/field.png`,
        coordinates: coords,
      });
      map.setLayoutProperty("radar-mosaic-layer", "visibility", "visible");
    } catch (_) { /* grid bounds unavailable */ }
  } else {
    map.setLayoutProperty("radar-mosaic-layer", "visibility", "none");
  }
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
  list.innerHTML = active.slice(-6).reverse().map((a) => {
    const popBadge = a.population_exposed ? `<span class="badge" style="background:#0284c7;color:#fff;margin-left:6px;font-size:10px;padding:2px 6px;border-radius:4px;">👥 ${Number(a.population_exposed).toLocaleString()} exposed</span>` : "";
    const locHead = a.region_name ? `<div style="font-weight:600;color:#38bdf8;margin:3px 0;">📍 ${a.region_name}</div>` : "";
    return `
    <div class="alert" data-severity="${a.severity}">
      <div class="head"><span>${a.severity} · ${a.hazard}</span><span class="sev">+${a.lead_minutes}min · P=${a.probability}</span></div>
      ${locHead}
      <div class="reason">${a.reason} ${popBadge}</div>
      <div class="factors">${Object.entries(a.contributing_signals).map(([k, v]) => `${k}=${v}`).join(" · ")}</div>
      <div class="action">▸ ${a.recommended_action}</div>
      <div class="muted small">model ${a.model_version} · mode ${a.mode} · confidence ${a.confidence}</div>
    </div>`;
  }).join("");
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

if ($("lyr-admin")) {
  $("lyr-admin").onchange = () => {
    const vis = $("lyr-admin").checked ? "visible" : "none";
    if (map.getLayer("admin-districts-line")) map.setLayoutProperty("admin-districts-line", "visibility", vis);
    if (map.getLayer("admin-blocks-line")) map.setLayoutProperty("admin-blocks-line", "visibility", vis);
    if (map.getLayer("admin-blocks-fill")) map.setLayoutProperty("admin-blocks-fill", "visibility", vis);
  };
}

if ($("lyr-radar-rings")) {
  $("lyr-radar-rings").onchange = () => {
    const vis = $("lyr-radar-rings").checked ? "visible" : "none";
    if (map.getLayer("radar-rings-line")) map.setLayoutProperty("radar-rings-line", "visibility", vis);
    if (map.getLayer("radar-stations-point")) map.setLayoutProperty("radar-stations-point", "visibility", vis);
  };
}

if ($("lyr-radar-mosaic")) {
  $("lyr-radar-mosaic").onchange = () => renderStep();
}

if ($("lyr-cones")) {
  $("lyr-cones").onchange = () => {
    const vis = $("lyr-cones").checked ? "visible" : "none";
    if (map.getLayer("cones-fill")) map.setLayoutProperty("cones-fill", "visibility", vis);
    if (map.getLayer("cones-line")) map.setLayoutProperty("cones-line", "visibility", vis);
    if (map.getLayer("tracks-line")) map.setLayoutProperty("tracks-line", "visibility", vis);
  };
}

if ($("lyr-ci")) {
  $("lyr-ci").onchange = () => {
    const vis = $("lyr-ci").checked ? "visible" : "none";
    if (map.getLayer("ci-layer")) map.setLayoutProperty("ci-layer", "visibility", vis);
    if (map.getLayer("ci-fill")) map.setLayoutProperty("ci-fill", "visibility", vis);
  };
}

if ($("lyr-uncertainty")) {
  $("lyr-uncertainty").onchange = () => renderStep();
}

function cellPopup(e) {
  const p = e.features[0].properties;
  const speed = p.velocity_kmh ? `${p.velocity_kmh} km/h` : `${(+p.motion_dlat).toFixed(3)}/${(+p.motion_dlon).toFixed(3)} °/cycle`;
  const heading = p.heading_deg ? `${p.heading_deg}°` : "—";
  const dbz = p.dbz_max ? ` · Max dBZ: <strong>${p.dbz_max}</strong>` : "";
  const core = p.core_area_km2 ? `<br>Core (≥45 dBZ): <strong>${p.core_area_km2} km²</strong>` : "";
  new maplibregl.Popup()
    .setLngLat([p.centroid_lon ?? e.lngLat.lng, p.centroid_lat ?? e.lngLat.lat])
    .setHTML(`<strong>⚡ Storm Cell ${p.cell_id}</strong><br>
       Speed: <strong>${speed}</strong> · Heading: <strong>${heading}</strong>${dbz}<br>
       Area: ${p.area_px} px · Age: ${p.track_age} steps${core}<br>
       Flash history: ${p.flash_history} flashes<br>
       <span class="muted small">geolocation: ${p.geo_note}</span>`)
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
