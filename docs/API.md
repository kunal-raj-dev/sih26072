# Project Vajra — API Reference

Base URL: `http://localhost:8000/api/v1` · Interactive docs: `/docs` (OpenAPI)

All responses are typed JSON. Every forecast/alert carries honesty metadata:
`mode` (LIVE | REPLAY | SIMULATION), `fallback_rung`, `model_version`,
`data_quality`, and (for forecasts) `grid` with a `geolocation` flag.

## Health

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness + version |
| GET | `/data-health` | Real per-source status (LIVE/REPLAY/SIMULATION/UNAVAILABLE) — never decorative |
| GET | `/model-health` | Active model, provenance, fallback-usage counts of the last run |

## Client config

| Method | Path | Description |
|---|---|---|
| GET | `/config` | Frontend bootstrap config. `carto_basemap_key` is the CARTO Basemaps token for the raster basemap, set via `VAJRA_BASEMAPS__CARTO_KEY` (env or git-ignored `.env`); `null` when unset — the map still loads, only the keyless watermark may appear |

## Events & replay

| Method | Path | Description |
|---|---|---|
| GET | `/events` | Replayable events: SEVIR (REPLAY, real data) + synthetic (SIMULATION) |
| GET | `/events/{id}` | Event detail incl. full provenance (source, license, access time, files) |
| GET | `/events/{id}/flashes.geojson` | All GLM/synthetic flashes of the event as GeoJSON (client filters by time) |
| POST | `/replay/{id}/run?collect_training=` | Run the full nowcast replay; returns run summary |
| GET | `/runs` · `/runs/{id}` | Run list/detail; detail includes verification metrics |

## Forecasts

| Method | Path | Description |
|---|---|---|
| GET | `/runs/{id}/forecasts` | Per-cycle forecast list (rung, confidence, leads, field URLs) |
| GET | `/forecasts/{fid}` | Full forecast: steps, cells, modalities, quality |
| GET | `/forecasts/{fid}/field.png?lead=30\|60` | Probability overlay PNG (risk-band palette = UI legend) |
| GET | `/forecasts/{fid}/field.npz?lead=30\|60` | Raw probability grid (numpy) |
| GET | `/forecasts/{fid}/cells.geojson?lead=60` | Storm-cell polygons + motion + intensity |
| GET | `/forecasts/{fid}/obs.png` | Grayscale observation field at issue time |

## Alerts

| Method | Path | Description |
|---|---|---|
| GET | `/alerts?run_id=&event_id=&severity=&preset=&lead_minutes=` | Alert center feed. Every alert: severity, region, probability, confidence, reason, contributing signals, recommended action |

## Live observation (visual reference)

| Method | Path | Description |
|---|---|---|
| GET | `/observations/radar/{station}.gif` | Proxied public IMD DWR image. Header `X-Data-Mode: LIVE-VISUAL-ONLY`. This is NEVER model input — numeric radar remains BLOCKED (MASTER.md §5) |

## Error model

404 = unknown resource · 409 = data not prepared (run `scripts/prepare_sevir_events.py`) ·
503 = upstream source failed (message quotes the provider error). No silent failures.
