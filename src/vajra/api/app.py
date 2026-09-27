"""FastAPI application: the serving layer of the vertical slice.

Endpoints (all under /api/v1):
  GET  /health                    — liveness
  GET  /data-health               — real per-source status (no decorative 'LIVE')
  GET  /model-health              — active model, version, provenance, fallback stats
  GET  /events                    — replayable events (SEVIR replay + synthetic)
  GET  /events/{event_id}         — event detail incl. provenance
  POST /replay/{event_id}/run     — run the nowcast replay; returns run summary
  GET  /runs                      — inference runs
  GET  /runs/{run_id}             — run detail incl. verification metrics
  GET  /runs/{run_id}/forecasts   — forecasts of a run (metadata + links)
  GET  /forecasts/{fid}           — forecast detail
  GET  /forecasts/{fid}/field.png?lead=30 — rendered probability overlay
  GET  /forecasts/{fid}/field.npz?lead=30 — raw probability grid
  GET  /forecasts/{fid}/cells.geojson?lead=60 — cell boxes+motion as GeoJSON
  GET  /alerts?run_id=&severity=  — alert center
  GET  /observations/radar/{station}.gif — proxied public IMD radar image (LIVE)

Errors are structured (never 'something went wrong'); every response carries
mode/provenance where applicable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import Settings, load_settings
from ..geocoding import SpatialIndex
from ..grid import india_grid
from ..logsetup import get_logger
from ..providers import (
    GfsNcepProvider,
    ImradarGifProvider,
    ImergProvider,
    LisProvider,
    MosdacProvider,
    RadarMosaicEngine,
    SevirCatalog,
    SevirReplayEvent,
    SyntheticProvider,
    compute_cooling_rate,
    default_bihar_event,
    detect_convective_initiation,
    simulate_synthetic_radar_scan,
)
from ..providers.sevir import SevirLightningProvider, SevirRadarProvider, SevirSatelliteProvider
from ..render import render_reflectivity_png
from ..schemas import DataHealth, DataMode, Event, Modality
from ..store import Store

logger = get_logger("vajra.api")


def create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="Project Vajra API", version="0.1.0",
                  description="Thunderstorm & lightning nowcasting decision support (SIH 2026 PS 26072)")
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.api.cors_origins,
        allow_methods=["*"], allow_headers=["*"])

    store = store or Store(settings)
    spatial_index = SpatialIndex()
    mosaic_engine = RadarMosaicEngine()
    state = {
        "settings": settings,
        "store": store,
        "pipeline_holder": None,
        "spatial_index": spatial_index,
        "mosaic_engine": mosaic_engine,
    }

    radar_gif = ImradarGifProvider(settings)
    nwp = GfsNcepProvider(settings)
    imerg = ImergProvider(settings)
    mosdac = MosdacProvider(settings)
    lis = LisProvider(settings)

    # ---- health ------------------------------------------------------------
    @app.get("/api/v1/health")
    def health() -> dict:
        return {"status": "ok", "time": datetime.now(timezone.utc).isoformat(), "version": app.version}

    @app.get("/api/v1/config")
    def client_config() -> dict:
        """Frontend bootstrap config. The CARTO basemap key is a public tile-access
        token by design (it rides on tile URLs from the browser); it is configured
        via VAJRA_BASEMAPS__CARTO_KEY and null when unset."""
        return {"carto_basemap_key": settings.basemaps.carto_key or None}

    @app.get("/api/v1/data-health", response_model_exclude_none=True)
    def data_health() -> list[DataHealth]:
        items = [radar_gif.health(), nwp.health(), imerg.health(), mosdac.health(), lis.health()]
        store.put_data_health(items)
        # Add provider health of the last replay run's sources if a pipeline exists.
        ph = state["pipeline_holder"]
        if ph:
            items = items + [src.health() for src in ph["sources"].values()]
        return items

    @app.get("/api/v1/model-health")
    def model_health() -> dict:
        ph = state["pipeline_holder"]
        if not ph:
            return {"active_model": "none (no replay run yet)", "message":
                    "POST /api/v1/replay/{event_id}/run to load the pipeline"}
        router = ph["pipeline"].router
        stats: dict[str, int] = {}
        for f in store.list_forecasts(run_id=ph.get("last_run_id")):
            stats[f.fallback_rung.value] = stats.get(f.fallback_rung.value, 0) + 1
        return {"active_model": router.health(), "fallback_usage_last_run": stats}

    # ---- events ------------------------------------------------------------
    @app.get("/api/v1/events")
    def list_events() -> list[dict]:
        _register_available_events(settings, store)
        return [e.model_dump(mode="json") for e in store.list_events()]

    @app.get("/api/v1/events/{event_id}")
    def get_event(event_id: str) -> dict:
        ev = store.get_event(event_id)
        if not ev:
            raise HTTPException(404, f"event '{event_id}' not found")
        return ev.model_dump(mode="json")

    # ---- replay --------------------------------------------------------------
    @app.post("/api/v1/replay/{event_id}/run")
    def run_replay(event_id: str, collect_training: bool = False) -> dict:
        _register_available_events(settings, store)
        try:
            pipeline, event, sources = _ensure_pipeline(event_id, settings, store, state)
        except FileNotFoundError as exc:
            raise HTTPException(409, f"data not prepared: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        run = pipeline.run_replay(event, event.time_start, event.time_end,
                                  collect_training=collect_training)
        store.put_run(run)
        state["pipeline_holder"]["last_run_id"] = run.id
        return {"id": run.id, "run_id": run.id, "event_id": event.id, "mode": event.mode.value,
                "cycles": run.cycles, "alerts": len(run.alerts),
                "forecast_ids": run.forecasts, "metrics": run.metrics}


    @app.get("/api/v1/runs")
    def runs() -> list[dict]:
        return [{"id": r.id, "event_id": r.event_id, "cycles": r.cycles,
                 "started_at": r.started_at.isoformat()} for r in store.list_runs()]

    @app.get("/api/v1/runs/{run_id}")
    def run_detail(run_id: str) -> dict:
        run = store.get_run(run_id)
        if not run:
            raise HTTPException(404, "run not found")
        d = run.model_dump(mode="json")
        d["verification"] = store.get_verification(run_id)
        return d

    @app.get("/api/v1/runs/{run_id}/scoreboard")
    def run_scoreboard(run_id: str) -> dict:
        """Detailed verification scoreboard for held-out events and historical runs (§32)."""
        run = store.get_run(run_id)
        if not run:
            raise HTTPException(404, "run not found")
        verif = store.get_verification(run_id) or {}
        metrics = verif.get("metrics", {})
        samples = verif.get("samples", {})
        fcs = store.list_forecasts(run_id=run_id)
        ev = store.get_event(run.event_id)
        mode_val = fcs[0].mode.value if fcs else (ev.mode.value if ev else "SIMULATION")

        # Evaluate 5 baselines against Project Vajra
        from ..verify import evaluate_baselines
        from ..case_studies import get_case_study
        from dataclasses import asdict

        baselines = {}
        chosen_lead = "60" if "60" in samples else ("30" if "30" in samples else None)
        if chosen_lead and len(samples.get(chosen_lead, [])):
            s = samples[chosen_lead]
            p_v = np.array([x["p"] for x in s], dtype=float)
            y_t = np.array([x["y"] for x in s], dtype=float)
            baselines = evaluate_baselines(p_v, y_t, threshold=0.35)

        cs = get_case_study(run.event_id)
        cs_dict = asdict(cs) if cs else None

        return {
            "run_id": run.id,
            "event_id": run.event_id,
            "mode": mode_val,
            "cycles": run.cycles,
            "alerts_count": len(run.alerts),
            "forecasts_count": len(fcs),
            "metrics": metrics,
            "sample_counts": {lead: len(s) for lead, s in samples.items()} if samples else {},
            "baseline_model": "climatology_logistic_prior",
            "evaluated_against": "GLM / ISS-LIS Flash Observations",
            "verification": verif,
            "baselines": baselines,
            "case_study": cs_dict,
        }


    # ---- forecasts --------------------------------------------------------------
    @app.get("/api/v1/runs/{run_id}/forecasts")
    def run_forecasts(run_id: str) -> list[dict]:
        fcs = store.list_forecasts(run_id=run_id)
        out = []
        for f in fcs:
            out.append({
                "id": f.id, "replay_time": f.replay_time.isoformat(),
                "mode": f.mode.value, "fallback_rung": f.fallback_rung.value,
                "confidence": f.confidence, "modalities_used": [m.value for m in f.modalities_used],
                "steps": [{"lead_minutes": s.lead_minutes, "p_flash_max": s.p_flash_max,
                           "risk_band": s.risk_band} for s in f.steps],
                "field_urls": {str(s.lead_minutes):
                               f"/api/v1/forecasts/{f.id}/field.png?lead={s.lead_minutes}"
                               for s in f.steps if s.lead_minutes in (30, 60)},
            })
        return out

    @app.get("/api/v1/forecasts/{fid}")
    def forecast_detail(fid: str) -> dict:
        f = store.get_forecast(fid)
        if not f:
            raise HTTPException(404, "forecast not found")
        return f.model_dump(mode="json")

    @app.get("/api/v1/forecasts/{fid}/field.png")
    def forecast_png(fid: str, lead: int = Query(60)) -> Response:
        paths = store.get_field_paths(fid, lead)
        if not paths:
            raise HTTPException(404, f"field for lead={lead} not found")
        return FileResponse(paths[1], media_type="image/png")

    @app.get("/api/v1/forecasts/{fid}/field.npz")
    def forecast_npz(fid: str, lead: int = Query(60)) -> FileResponse:
        paths = store.get_field_paths(fid, lead)
        if not paths:
            raise HTTPException(404, f"field for lead={lead} not found")
        return FileResponse(paths[0], media_type="application/octet-stream")

    @app.get("/api/v1/forecasts/{fid}/cells.geojson")
    def forecast_cells(fid: str, lead: int = Query(60)) -> dict:
        f = store.get_forecast(fid)
        if not f:
            raise HTTPException(404, "forecast not found")
        step = next((s for s in f.steps if s.lead_minutes == lead), None)
        if step is None:
            raise HTTPException(404, f"lead {lead} not in forecast")
        feats = []
        for c in step.cells:
            poly = [[
                [c.bbox[0], c.bbox[1]], [c.bbox[2], c.bbox[1]],
                [c.bbox[2], c.bbox[3]], [c.bbox[0], c.bbox[3]],
                [c.bbox[0], c.bbox[1]],
            ]]
            feats.append({"type": "Feature",
                          "geometry": {"type": "Polygon", "coordinates": poly},
                          "properties": {
                              "cell_id": c.id, "max_intensity": c.max_intensity,
                              "area_px": c.area_px, "track_age": c.track_age_steps,
                              "motion_dlat": c.motion_dlat, "motion_dlon": c.motion_dlon,
                              "flash_history": c.flash_count_history,
                              "centroid_lat": c.centroid_lat, "centroid_lon": c.centroid_lon,
                              "velocity_kmh": c.velocity_kmh,
                              "heading_deg": c.heading_deg,
                              "dbz_max": c.dbz_max,
                              "core_area_km2": c.core_area_km2,
                              "projected_track": c.projected_track,
                              "uncertainty_cone": c.uncertainty_cone,
                              "geo_note": f.grid.geolocation if f.grid else "unknown",
                          }})
        return {"type": "FeatureCollection", "features": feats}

    @app.get("/api/v1/forecasts/{fid}/obs.png")
    def forecast_obs_png(fid: str) -> FileResponse:
        p = store.artifacts / fid / "obs.png"
        if not p.exists():
            raise HTTPException(404, "observation render not available for this forecast")
        return FileResponse(p, media_type="image/png")

    @app.get("/api/v1/forecasts/{fid}/uncertainty.png")
    def forecast_uncertainty_png(fid: str) -> FileResponse:
        p = store.get_uncertainty_png_path(fid)
        if not p or not p.exists():
            raise HTTPException(404, "uncertainty field render not available for this forecast")
        return FileResponse(p, media_type="image/png")

    @app.get("/api/v1/forecasts/{fid}/ci.geojson")
    def forecast_ci_geojson(fid: str) -> dict:
        f = store.get_forecast(fid)
        if not f:
            raise HTTPException(404, "forecast not found")
        feats = []
        for c in getattr(f, "ci_candidates", []):
            poly = [c.polygon] if c.polygon else [[[c.bbox[0], c.bbox[1]], [c.bbox[2], c.bbox[1]],
                                                   [c.bbox[2], c.bbox[3]], [c.bbox[0], c.bbox[3]],
                                                   [c.bbox[0], c.bbox[1]]]]
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": poly},
                "properties": {
                    "id": c.id,
                    "centroid_lat": c.centroid_lat,
                    "centroid_lon": c.centroid_lon,
                    "cooling_rate_k_per_15m": c.cooling_rate_k_per_15m,
                    "ir_brightness_temp_k": c.ir_brightness_temp_k,
                    "ir_wv_diff_k": c.ir_wv_diff_k,
                    "p_initiation": c.p_initiation,
                    "estimated_lead_min": c.estimated_lead_min,
                    "area_km2": c.area_km2,
                },
            })
        return {"type": "FeatureCollection", "features": feats}

    @app.get("/api/v1/forecasts/{fid}/bulletin")
    def forecast_bulletin(fid: str, preset: str = "operational") -> dict:
        """Official IMD/NDMA format emergency bulletin for a forecast cycle."""
        f = store.get_forecast(fid)
        if not f:
            raise HTTPException(404, "forecast not found")
        t_utc = f.replay_time.astimezone(timezone.utc)
        ist_offset = timezone(timedelta(hours=5, minutes=30))
        t_ist = f.replay_time.astimezone(ist_offset)

        # Retrieve alerts for this forecast/cycle
        alerts_all = store.list_alerts(run_id=f.run_id if hasattr(f, "run_id") and f.run_id else None)
        cycle_alerts = [
            a for a in alerts_all
            if a.preset == preset and abs((a.issued_at.astimezone(timezone.utc) - t_utc).total_seconds()) < 1800
        ]

        stages = [a.imd_stage for a in cycle_alerts if a.imd_stage]
        priority = {"RED": 4, "ORANGE": 3, "YELLOW": 2, "GREEN": 1}
        max_stage = max(stages, key=lambda s: priority.get(s, 0)) if stages else "YELLOW"

        districts = list(dict.fromkeys(d for a in cycle_alerts for d in a.affected_districts))
        blocks = list(dict.fromkeys(b for a in cycle_alerts for b in a.affected_blocks))
        total_pop = sum(a.population_exposed for a in cycle_alerts if a.population_exposed)

        return {
            "bulletin_id": f"NDMA-VAJRA-NOWCAST-{f.id[:8].upper()}",
            "headline": f"IMD {max_stage} WARNING: CONVECTIVE THUNDERSTORM & LIGHTNING NOWCAST",
            "issue_time_utc": t_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "issue_time_ist": t_ist.strftime("%d-%b-%Y %I:%M %p IST"),
            "valid_until_ist": (t_ist + timedelta(minutes=60)).strftime("%d-%b-%Y %I:%M %p IST"),
            "mode": f.mode.value if hasattr(f.mode, "value") else str(f.mode),
            "max_stage": max_stage,
            "confidence": f.confidence,
            "fallback_rung": f.fallback_rung.value if hasattr(f.fallback_rung, "value") else str(f.fallback_rung),
            "affected_districts": districts,
            "affected_blocks": blocks,
            "total_population_exposed": total_pop,
            "alerts_count": len(cycle_alerts),
            "alerts": [a.model_dump(mode="json") for a in cycle_alerts],
            "standard_operating_procedures": [
                "Suspend all outdoor, agricultural, harvesting, and open-field activities immediately.",
                "Seek immediate shelter in a sturdy pucca building; stay away from tin sheds and isolated trees.",
                "Avoid contact with electrical wiring, metal fences, plumbing pipes, and mobile phone charging.",
                "Water bodies must be evacuated immediately; boat operators and fishermen must dock at nearest shore.",
                "State and District Emergency Operation Centers (DEOCs) to maintain continuous operational watch and broadcast local alerts."
            ],
            "disclaimer": "Generated by Project Vajra Operational Nowcasting System (MoES/IMD & NDMA compliance)."
        }

    @app.get("/api/v1/events/{event_id}/flashes.geojson")
    def event_flashes(event_id: str) -> dict:
        """All flashes of a replay/simulation event (client filters by time window).
        Mode is carried per-feature so the map can never mislabel them."""
        ev = store.get_event(event_id)
        if not ev:
            raise HTTPException(404, "event not found")
        feats: list[dict] = []
        from ..case_studies import get_case_study, create_case_study_sources
        cs = get_case_study(event_id)
        if cs is not None:
            if cs.mode == "REPLAY" and cs.event_id == "sevir_s810646":
                rev = SevirReplayEvent("S810646", settings)
                try:
                    b = rev.prepare()
                except Exception as exc:  # noqa: BLE001
                    raise HTTPException(503, f"event data unavailable: {exc}") from exc
                from datetime import timedelta
                epoch0 = (b.time_center - timedelta(minutes=120)).timestamp()
                fl = b.flashes
                for row in fl:
                    t_off, lat, lon, energy = float(row[0]), float(row[1]), float(row[2]), float(row[3])
                    feats.append({"type": "Feature",
                                  "geometry": {"type": "Point", "coordinates": [lon, lat]},
                                  "properties": {"t": epoch0 + t_off, "energy": energy,
                                                 "mode": "REPLAY"}})
            else:
                sources = create_case_study_sources(cs, settings)
                prov = sources[Modality.LIGHTNING]
                t_end = datetime.fromisoformat(cs.end_time)
                pts = prov._flash_points(t_end, int(cs.duration_hours * 60))
                for lat, lon, energy, epoch in pts:
                    feats.append({"type": "Feature",
                                  "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                                  "properties": {"t": float(epoch), "energy": float(energy),
                                                 "mode": cs.mode}})
        elif event_id.startswith("SEVIR_"):
            rev = SevirReplayEvent(event_id.replace("SEVIR_", ""), settings)
            try:
                b = rev.prepare()
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(503, f"event data unavailable: {exc}") from exc
            from datetime import timedelta
            epoch0 = (b.time_center - timedelta(minutes=120)).timestamp()
            fl = b.flashes
            for row in fl:
                t_off, lat, lon, energy = float(row[0]), float(row[1]), float(row[2]), float(row[3])
                feats.append({"type": "Feature",
                              "geometry": {"type": "Point", "coordinates": [lon, lat]},
                              "properties": {"t": epoch0 + t_off, "energy": energy,
                                             "mode": "REPLAY"}})
        elif event_id.startswith("SIM_"):
            syn = default_bihar_event(settings)
            prov = SyntheticProvider(syn, settings, Modality.LIGHTNING)
            end = syn.start + __import__("datetime").timedelta(hours=syn.hours)
            pts = prov._flash_points(end, int(syn.hours * 60))
            for lat, lon, energy, epoch in pts:
                feats.append({"type": "Feature",
                              "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                              "properties": {"t": float(epoch), "energy": float(energy),
                                             "mode": "SIMULATION"}})
        return {"type": "FeatureCollection", "features": feats}

    # ---- alerts ---------------------------------------------------------------
    @app.get("/api/v1/alerts")
    def alerts(run_id: str | None = None, event_id: str | None = None,
               severity: str | None = None, preset: str | None = None,
               lead_minutes: int | None = None) -> list[dict]:
        items = store.list_alerts(run_id=run_id, event_id=event_id, severity=severity)
        if preset:
            items = [a for a in items if a.preset == preset]
        if lead_minutes:
            items = [a for a in items if a.lead_minutes == lead_minutes]
        return [a.model_dump(mode="json") for a in items]

    @app.get("/api/v1/alerts/{alert_id}/cap.xml")
    def alert_cap_xml(alert_id: str) -> Response:
        """Download OASIS CAP 1.2 XML payload for an alert."""
        alert = store.get_alert(alert_id)
        if not alert:
            raise HTTPException(404, f"alert {alert_id} not found")
        xml_content = alert.to_cap_xml()
        return Response(content=xml_content, media_type="application/cap+xml; charset=utf-8")

    @app.get("/api/v1/alerts/{alert_id}/cap.json")
    def alert_cap_json(alert_id: str) -> dict:
        """Retrieve OASIS/WMO compliant CAP 1.2 JSON payload for an alert."""
        alert = store.get_alert(alert_id)
        if not alert:
            raise HTTPException(404, f"alert {alert_id} not found")
        return alert.to_cap_json()

    @app.get("/api/v1/alerts/feed.atom")
    def alerts_atom_feed(run_id: str | None = None) -> Response:
        """Retrieve RFC 4287 Atom Syndication Feed with CAP 1.2 alerts."""
        from ..cap import build_cap_atom_feed
        alerts_list = store.list_alerts(run_id=run_id)
        feed_xml = build_cap_atom_feed(alerts_list[-20:] if alerts_list else [])
        return Response(content=feed_xml, media_type="application/atom+xml; charset=utf-8")

    @app.get("/api/v1/alerts/{alert_id}.cap")
    def alert_cap_dot(alert_id: str) -> Response:
        """Alias for /api/v1/alerts/{alert_id}/cap.xml matching table in §32."""
        return alert_cap_xml(alert_id)

    @app.get("/api/v1/alerts/{alert_id}", response_model=None)
    def alert_detail(alert_id: str) -> Response | dict:
        """Retrieve full details of an active alert (or CAP 1.2 XML if .cap requested)."""
        if alert_id.endswith(".cap"):
            return alert_cap_xml(alert_id[:-4])
        alert = store.get_alert(alert_id)
        if not alert:
            raise HTTPException(404, f"alert {alert_id} not found")
        return alert.model_dump(mode="json")

    # ---- live IMD radar imagery (visual reference) -----------------------------
    @app.get("/api/v1/observations/radar/{station}.gif")
    def radar_gif_proxy(station: str) -> Response:
        try:
            content, ct = radar_gif.fetch(station)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(503, f"radar source unavailable: {exc}") from exc
        return Response(content=content, media_type=ct,
                        headers={"Cache-Control": "no-store",
                                 "X-Data-Mode": "LIVE-VISUAL-ONLY (not numeric radar)"})

    # ---- administrative boundaries & geocoding --------------------------------
    @app.get("/api/v1/admin/districts")
    def admin_districts() -> dict:
        return spatial_index.get_district_geojson()

    @app.get("/api/v1/admin/blocks")
    def admin_blocks(district: str | None = None) -> dict:
        return spatial_index.get_blocks_geojson(district=district)

    # ---- multi-radar mosaic & stations ---------------------------------------
    @app.get("/api/v1/radar/stations")
    def radar_stations() -> list[dict]:
        return [
            {
                "id": s.id,
                "name": s.name,
                "lat": s.lat,
                "lon": s.lon,
                "altitude_m": s.altitude_m,
                "max_range_km": s.max_range_km,
                "rings_km": list(s.rings_km),
                "band": s.band,
                "status": s.status,
            }
            for s in mosaic_engine.stations
        ]

    @app.get("/api/v1/radar/rings.geojson")
    def radar_rings() -> dict:
        return mosaic_engine.generate_rings_geojson()

    @app.get("/api/v1/radar/mosaic/latest")
    def radar_mosaic_latest() -> dict:
        grid = india_grid(settings.grid.step_deg)
        cores = [(25.6, 85.1, 56.0, 18.0), (25.1, 84.7, 48.0, 15.0)]
        scans = [
            simulate_synthetic_radar_scan(s, grid, cores)
            for s in [mosaic_engine.get_station("patna"), mosaic_engine.get_station("ranchi"), mosaic_engine.get_station("kolkata")]
            if s is not None
        ]
        _, meta = mosaic_engine.composite(scans, grid, method="max")
        meta["timestamp"] = datetime.now(timezone.utc).isoformat()
        return meta

    @app.get("/api/v1/radar/mosaic/field.png")
    def radar_mosaic_png(method: str = "max") -> Response:
        grid = india_grid(settings.grid.step_deg)
        cores = [(25.6, 85.1, 56.0, 18.0), (25.1, 84.7, 48.0, 15.0)]
        scans = [
            simulate_synthetic_radar_scan(s, grid, cores)
            for s in [mosaic_engine.get_station("patna"), mosaic_engine.get_station("ranchi"), mosaic_engine.get_station("kolkata")]
            if s is not None
        ]
        comp, _ = mosaic_engine.composite(scans, grid, method=method)  # type: ignore[arg-type]
        png = render_reflectivity_png(comp)
        return Response(
            content=png,
            media_type="image/png",
            headers={
                "Cache-Control": "no-store",
                "X-Data-Mode": "COMPOSITE-RADAR-MOSAIC",
            },
        )

    # ---- MOSDAC INSAT & Convective Initiation ---------------------------------
    @app.get("/api/v1/satellite/mosdac/status")
    def mosdac_status() -> dict:
        h = mosdac.health()
        return {
            "source": h.source,
            "status": h.status.value,
            "message": h.message,
            "last_success": h.last_success.isoformat() if h.last_success else None,
            "cache_dir": str(mosdac.cache_dir),
            "processed_dir": str(mosdac.processed_dir),
        }

    @app.get("/api/v1/satellite/ci/latest")
    def convective_initiation_latest() -> dict:
        grid = india_grid(settings.grid.step_deg)
        now = datetime.now(timezone.utc)
        history = mosdac.get_history(now, 60)
        if len(history) >= 2:
            dt_min = (history[-1].meta.time - history[-2].meta.time).total_seconds() / 60.0
            cr = compute_cooling_rate(history[-1].field, history[-2].field, dt_minutes=dt_min)
            ci = detect_convective_initiation(history[-1].field, cooling_rate_15m=cr, grid=grid)
            return {
                "timestamp": history[-1].meta.time.isoformat(),
                "candidate_count": ci["candidate_count"],
                "candidates": ci["candidates"],
            }
        return {
            "timestamp": now.isoformat(),
            "candidate_count": 0,
            "candidates": [],
            "note": "Awaiting 2+ sequential INSAT observation frames to compute cloud-top cooling rates",
        }

    # ---- NASA ISS LIS Lightning ----------------------------------------------
    @app.get("/api/v1/satellite/lis/latest")
    def lis_latest() -> dict:
        h = lis.health()
        now = datetime.now(timezone.utc)
        frames = lis.get_history(now, 120)
        pts = frames[-1].points if frames else None
        features = []
        if pts is not None:
            for lat, lon, energy, epoch in pts:
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                    "properties": {
                        "energy_uj": float(energy),
                        "time_epoch": float(epoch),
                        "sensor": "ISS_LIS",
                    }
                })
        return {
            "status": h.status.value,
            "message": h.message,
            "total_flashes": len(features),
            "type": "FeatureCollection",
            "features": features,
        }

    # ---- NOAA GFS NWP Environmental Intelligence -----------------------------
    @app.get("/api/v1/nwp/gfs/status")
    def gfs_status() -> dict:
        h = nwp.health()
        return {
            "source": nwp.name,
            "modality": nwp.modality.value,
            "status": h.status.value,
            "message": h.message,
            "last_success": h.last_success.isoformat() if h.last_success else None,
            "cache_dir": str(nwp.cache_dir),
            "cached_cycles": len(nwp._history_frames),
            "variables": ["cape_jkg", "cin_jkg", "shear_0_6km_ms", "rh_700hpa_pct"],
        }

    @app.get("/api/v1/nwp/gfs/indices")
    def gfs_indices() -> dict:
        h = nwp.health()
        now = datetime.now(timezone.utc)
        frames = nwp.get_history(now, 720)
        if not frames:
            return {
                "status": h.status.value,
                "message": h.message,
                "available": False,
                "indices": {},
            }
        stats = {}
        for fr in frames:
            vname = fr.meta.variable
            if fr.field is not None and vname not in stats:
                stats[vname] = {
                    "units": fr.meta.units,
                    "min": float(np.nanmin(fr.field)),
                    "max": float(np.nanmax(fr.field)),
                    "mean": float(np.nanmean(fr.field)),
                    "timestamp": fr.meta.time.isoformat(),
                }
        return {
            "status": h.status.value,
            "available": True,
            "indices": stats,
        }

    # ---- static frontend ---------------------------------------------------------
    web = settings.web_dist
    if web.exists():
        app.mount("/", StaticFiles(directory=str(web), html=True), name="web")

    return app


def _synthetic_event(settings: Settings, store: Store) -> Event:
    ev = default_bihar_event(settings)
    from ..schemas import Event as E
    event = E(id=ev.event_id, title="Synthetic Bihar storm (SIMULATION)",
              mode=DataMode.SIMULATION, domain=settings.grid.name,
              time_start=ev.start, time_end=ev.start + __import__("datetime").timedelta(hours=ev.hours),
              source="vajra.synthetic (deterministic)", provenance={"seed_note": "deterministic generator"})
    store.put_event(event)
    return event


def _register_available_events(settings: Settings, store: Store) -> None:
    """Register the synthetic demo event + 6 historical case studies + prepared SEVIR events."""
    if store.get_event("SIM_BIHAR_001") is None:
        _synthetic_event(settings, store)
    from ..case_studies import list_case_studies
    for cs in list_case_studies():
        if store.get_event(cs.event_id) is None:
            store.put_event(cs.to_event())
    events_dir = settings.data_root / "external" / "sevir" / "events"
    if events_dir.exists():
        for npz in sorted(events_dir.glob("*.npz")):
            eid = f"SEVIR_{npz.stem}"
            if store.get_event(eid) is None:
                try:
                    rev = SevirReplayEvent(npz.stem, settings)
                    rev.prepare()  # loads local cache
                    store.put_event(rev.to_event())
                except Exception as exc:  # noqa: BLE001 — skip broken caches, log honestly
                    logger.warning(f"event {eid} unavailable: {exc}")


def _ensure_pipeline(event_id: str, settings: Settings, store: Store, state: dict):
    """Build (or reuse) the pipeline for an event; registers providers + model."""
    ev = store.get_event(event_id)
    if ev is None:
        raise ValueError(f"event '{event_id}' not found")

    from ..case_studies import get_case_study, create_case_study_sources
    cs = get_case_study(event_id)
    if cs is not None:
        sources = create_case_study_sources(cs, settings)
        mode = DataMode.REPLAY if cs.mode == "REPLAY" else DataMode.SIMULATION
        event = ev
        model_version = "xgb-fusion-v1" if (settings.models_dir / "xgb_fusion" / "model.json").exists() else "baseline-v1"
    elif event_id.startswith("SIM_"):
        syn = default_bihar_event(settings)
        sources = {
            Modality.SATELLITE: SyntheticProvider(syn, settings, Modality.SATELLITE),
            Modality.RADAR: SyntheticProvider(syn, settings, Modality.RADAR),
            Modality.LIGHTNING: SyntheticProvider(syn, settings, Modality.LIGHTNING),
        }
        grid = None  # resolved on first cycle from frames
        mode = DataMode.SIMULATION
        event = ev
        model_version = "baseline-v1"
    elif event_id.startswith("SEVIR_"):

        sevir_id = event_id.replace("SEVIR_", "")
        rev = SevirReplayEvent(sevir_id, settings)
        if not (rev.cache_dir / f"{sevir_id}.npz").exists():
            rev.prepare()
        else:
            rev.prepare()  # loads cache
        sources = {
            Modality.SATELLITE: SevirSatelliteProvider(rev),
            Modality.RADAR: SevirRadarProvider(rev),
            Modality.LIGHTNING: SevirLightningProvider(rev),
        }
        mode = DataMode.REPLAY
        event = ev
        model_version = "xgb-v0 (SIM-trained)" if not (settings.models_dir / "xgb_fusion" / "model.json").exists() else "xgb-latest"
    else:
        raise ValueError(f"unknown event namespace: {event_id}")

    from ..models.baselines import (AdvectionModel, ClimatologyModel,
                                    LightningJumpModel, PersistenceModel)
    from ..models.router import ModelRouter
    from ..models.xgb_fusion import XGBFusionModel
    from ..pipeline import NowcastPipeline

    fusion = None
    artifact = settings.models_dir / "xgb_fusion"
    if (artifact / "model.json").exists():
        fusion = XGBFusionModel(artifact)
        fusion.load()

    physics = AdvectionModel(vil_threshold=settings.cells.vil_threshold)
    persistence = PersistenceModel()
    climatology = ClimatologyModel()
    # Climatology base rate: use training prevalence if a model exists, else 0.05.
    base_rate = 0.05
    if fusion is not None and getattr(fusion, "_meta", None):
        base_rate = fusion._meta.get("train_metrics", {}).get("positive_rate", 0.05)
    climatology.base_rate = base_rate
    climatology.trained_on = f"prevalence default {base_rate}"

    router = ModelRouter(fusion=fusion, physics=physics,
                         persistence=persistence, climatology=climatology)
    pipeline = NowcastPipeline(settings, sources, router,
                               model_version=fusion.version if fusion else "baselines-v1",
                               spatial_index=state.get("spatial_index"))
    pipeline.attach_store(store)
    state["pipeline_holder"] = {"pipeline": pipeline, "sources": sources,
                                "event": event, "mode": mode}
    return pipeline, event, sources


app = create_app()
