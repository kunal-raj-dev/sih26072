# Project Vajra — REST API & CAP 1.2 Specification
**Base URL:** `http://localhost:8000/api/v1` · **Interactive OpenAPI Documentation:** `/docs` (Swagger UI) / `/redoc`

Project Vajra exposes a strictly typed, production-grade REST API compliant with MoES/IMD guidelines, NDMA disaster management protocols, and WMO/ITU Common Alerting Protocol (CAP v1.2) standards.

---

## 1. System Health & Honest Provenance

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| `GET` | `/health` | Core service liveness probe and build version. |
| `GET` | `/data-health` | Real-time modality health and provenance audit (LIVE, REPLAY, SIMULATION, UNAVAILABLE). |
| `GET` | `/model-health` | Active model architecture status, training provenance, and fallback rung usage statistics. |
| `GET` | `/config` | Client bootstrap configuration including CARTO basemap keys and domain defaults. |

---

## 2. Replay & Historical Case Studies

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| `GET` | `/events` | Lists all 6 canonical historical case studies + prepared SEVIR and synthetic events. |
| `GET` | `/events/{event_id}` | Detailed case study metadata, synoptic narrative, bounding box, and IMD text advisory. |
| `GET` | `/events/{event_id}/flashes.geojson` | All observed lightning strike points (GLM / NASA ISS-LIS) as a GeoJSON FeatureCollection. |
| `POST` | `/replay/{event_id}/run` | Triggers deterministic nowcasting replay across the event window. Returns execution run summary. |
| `GET` | `/runs` | List of completed inference runs ordered by start time. |
| `GET` | `/runs/{run_id}` | Detailed run execution metadata, cycle counts, alerts, and verification metrics. |

---

## 3. Forecasts, Grids & Storm Cell Polygons

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| `GET` | `/runs/{run_id}/forecasts` | List of all forecasts issued during a run with lead steps, confidence, and field asset links. |
| `GET` | `/forecasts/{fid}` | Complete forecast payload: detected cells, fallback rung, modalities used, and step fields. |
| `GET` | `/forecasts/{fid}/field.png?lead=30\|60` | RGBA probability raster overlay painted using official 4-stage IMD risk band colors. |
| `GET` | `/forecasts/{fid}/field.npz?lead=30\|60` | Raw 2D float32 numpy array containing physical probabilities $P(\text{flash} \ge 1)$. |
| `GET` | `/forecasts/{fid}/cells.geojson?lead=60` | GeoJSON polygons for detected storm cells, track history, Kalman velocity, and cone of uncertainty. |
| `GET` | `/forecasts/{fid}/obs.png` | Grayscale satellite/radar composite observation field at issue time $T_0$. |
| `GET` | `/forecasts/{fid}/uncertainty.png` | Epistemic and aleatoric uncertainty standard deviation raster field. |

---

## 4. Emergency Bulletins & CAP 1.2 Alert Engine

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| `GET` | `/alerts` | Query active disaster alerts with filtering (`run_id`, `event_id`, `severity`, `preset`, `lead_minutes`). |
| `GET` | `/alerts/{alert_id}` | Complete alert detail with population exposed, affected blocks, and contributing physical signals. |
| `GET` | `/alerts/{alert_id}/cap.xml` | **OASIS / ITU-T Recommendation X.1303 CAP 1.2 XML** emergency alert payload. |
| `GET` | `/alerts/{alert_id}.cap` | Alias matching official WMO CAP alerting protocol file extension standards. |
| `GET` | `/alerts/{alert_id}/cap.json` | OASIS CAP 1.2 JSON equivalent for lightweight web and mobile client ingestion. |
| `GET` | `/alerts/feed.atom` | **RFC 4287 Atom Syndication Feed** embedding CAP 1.2 XML entries for national sirens. |
| `GET` | `/forecasts/{fid}/bulletin` | Formatted official NDMA/IMD Severe Weather Bulletin with print-ready emergency actions. |

---

## 5. Verification Scoreboard & Baseline Audit

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| `GET` | `/runs/{run_id}/scoreboard` | Comprehensive verification scorecard comparing Project Vajra against the 5 baselines: |

**Scoreboard Response Payload:**
```json
{
  "run_id": "1aa853c682a9",
  "event_id": "bihar_squall_2026",
  "mode": "SIMULATION",
  "cycles": 19,
  "metrics": {
    "30": { "n": 16, "pod": 0.88, "far": 0.12, "csi": 0.78, "brier_score": 0.114, "bss": 0.44, "roc_auc": 0.91, "is_monotone": true },
    "60": { "n": 16, "pod": 0.82, "far": 0.18, "csi": 0.70, "brier_score": 0.142, "bss": 0.38, "roc_auc": 0.87, "is_monotone": true }
  },
  "baselines": {
    "vajra": { "name": "Project Vajra (Dual-Track AI)", "pod": 0.82, "far": 0.18, "csi": 0.70, "bss": 0.38 },
    "climatology_persistence": { "name": "Climatology / Persistence Floor", "pod": 0.50, "far": 0.40, "csi": 0.38, "bss": -0.15 },
    "nwp_environmental_threshold": { "name": "NWP CAPE/Shear Gating", "pod": 0.88, "far": 0.68, "csi": 0.30, "bss": -0.32 },
    "lagrangian_advection": { "name": "Lagrangian Optical Flow", "pod": 0.52, "far": 0.35, "csi": 0.41, "bss": 0.08 },
    "uncalibrated_gbdt": { "name": "Raw Uncalibrated GBDT", "pod": 0.80, "far": 0.32, "csi": 0.58, "bss": 0.10 },
    "imd_text_bulletin": { "name": "Official IMD District Text Advisory", "pod": 0.90, "far": 0.72, "csi": 0.27, "bss": -0.45 }
  },
  "case_study": { "title": "Severe Bihar Lightning Tragedy — Pre-Monsoon Convective Squall Line" }
}
```

---

## 6. Multi-Radar Mosaic & Administrative Boundaries

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| `GET` | `/radar/stations` | Metadata for all 39 IMD Doppler Weather Radar stations (lat/lon, range, band, status). |
| `GET` | `/radar/rings.geojson` | GeoJSON range rings (100 km, 200 km, 250 km) for active radar stations. |
| `GET` | `/radar/mosaic/latest` | Metadata for latest distance-weighted Cressman composite radar mosaic. |
| `GET` | `/radar/mosaic/field.png` | Seamless multi-radar composite reflectivity PNG field (0–70 dBZ colormap). |
| `GET` | `/radar/station/{id}/scan.png` | Individual Cartesian scan for a specific Doppler radar station. |
| `GET` | `/admin/districts` | High-speed simplified Survey of India district boundaries GeoJSON. |
| `GET` | `/admin/blocks?district=` | Sub-district (Block) administrative boundaries filtered by district. |
| `GET` | `/satellite/indices` | INSAT-3D thermal infrared and cloud-top diagnostic statistics. |
| `GET` | `/observations/radar/{station}.gif` | Proxied visual reference radar imagery from IMD Mausam portal with strict SSRF validation. |
