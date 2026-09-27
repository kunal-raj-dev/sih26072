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

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import Settings, load_settings
from ..logsetup import get_logger
from ..providers import (
    GfsNcepProvider,
    ImradarGifProvider,
    ImergProvider,
    SevirCatalog,
    SevirReplayEvent,
    SyntheticProvider,
    default_bihar_event,
)
from ..providers.sevir import SevirLightningProvider, SevirRadarProvider, SevirSatelliteProvider
from ..schemas import DataHealth, DataMode, Event, Modality
from ..store import Store

logger = get_logger("vajra.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="Project Vajra API", version="0.1.0",
                  description="Thunderstorm & lightning nowcasting decision support (SIH 2026 PS 26072)")
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.api.cors_origins,
        allow_methods=["*"], allow_headers=["*"])

    store = Store(settings)
    state = {"settings": settings, "store": store, "pipeline_holder": None}

    radar_gif = ImradarGifProvider(settings)
    nwp = GfsNcepProvider()
    imerg = ImergProvider(settings)

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
        items = [radar_gif.health(), nwp.health(), imerg.health()]
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
        return {"run_id": run.id, "event_id": event.id, "mode": event.mode.value,
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
                              "geo_note": f.grid.geolocation if f.grid else "unknown",
                          }})
        return {"type": "FeatureCollection", "features": feats}

    @app.get("/api/v1/forecasts/{fid}/obs.png")
    def forecast_obs_png(fid: str) -> FileResponse:
        p = store.artifacts / fid / "obs.png"
        if not p.exists():
            raise HTTPException(404, "observation render not available for this forecast")
        return FileResponse(p, media_type="image/png")

    @app.get("/api/v1/events/{event_id}/flashes.geojson")
    def event_flashes(event_id: str) -> dict:
        """All flashes of a replay/simulation event (client filters by time window).
        Mode is carried per-feature so the map can never mislabel them."""
        ev = store.get_event(event_id)
        if not ev:
            raise HTTPException(404, "event not found")
        feats = []
        if event_id.startswith("SEVIR_"):
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
    """Register the synthetic demo event + every prepared SEVIR event (local cache
    only — never triggers implicit network fetches)."""
    if store.get_event("SIM_BIHAR_001") is None:
        _synthetic_event(settings, store)
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

    if event_id.startswith("SIM_"):
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
                               model_version=fusion.version if fusion else "baselines-v1")
    pipeline.attach_store(store)
    state["pipeline_holder"] = {"pipeline": pipeline, "sources": sources,
                                "event": event, "mode": mode}
    return pipeline, event, sources


app = create_app()
