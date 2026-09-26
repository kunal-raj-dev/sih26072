# Deliverable 6 — MVP Specification

The smallest serious system that demonstrates OBSERVATION → PROCESSING → PREDICTION → MAP → WARNING, achievable without pretending to have unavailable capabilities. Status: [DECISION] unless labelled.

## 1. Exact input data

| Input | Source | Mode | Cadence | Role |
|---|---|---|---|---|
| GOES-16 ABI (C02/C07–C09/C13–C15) + **GLM lightning** + MRMS VIL | **SEVIR** (`s3://sevir`, no sign-request) | REPLAY (primary training/eval) | 5-min | full-fidelity sandbox with all labels |
| INSAT-3D/3DR/3DS IR1/WV/VIS (+CTT L2) | MOSDAC (`mdapi.py`, free account) | REPLAY (T-3 d) / LIVE (if privileged granted) | 30 min | India predictor |
| GFS 0.25° (CAPE, RH, u/v) | NOMADS GRIB filter | LIVE + archive | 6-h cycles | environmental gating |
| ERA5 (CAPE, RH, winds) | CDS | archive | hourly | training features + climatology |
| IMERG V07 (Early/Final) | Earthdata / GEE | LIVE + archive | 30 min | rain truth / cell segmentation field |
| ISS LIS flashes + LIS/OTD 0.1° climatology | Earthdata | archive | orbital | weak India labels + climatology baseline |
| IMD DWR GIFs (1–3 stations, e.g. Patna) | mausam.imd.gov.in (public images) | LIVE (visual) / REPLAY | 10 min | visual verification + optional GIF→grid experiment [EXPERIMENTAL] |

## 2. Exact prediction target

`P(≥1 lightning flash within 0.1° cell, next 30 min and next 60 min)` — calibrated probabilities on a 0.1° grid (SEVIR domain for the sandbox; India region 68–98°E, 6–38°N for India mode), plus storm-cell polygons with motion vectors segmented from the IMERG/rain-proxy field (tobac/tintX). **Secondary target (EXPERIMENTAL):** thunderstorm occurrence via IR cloud-top cooling rate + radar-proxy thresholds.

## 3. Baselines (all shipped, all scored)

Persistence · LIS/OTD climatology · lightning-jump rule (2σ) · PySTEPS LK deterministic + STEPS ensemble (on IMERG/rain proxy) · IR-threshold rule (TIR ≤ −50 °C).

## 4. MVP model

1. **XGBoost late fusion** (primary): per-cell + per-cell-track features — IR channel stats & 30/60-min cooling rates, WV depression, flash-rate trend (where labels exist), IMERG cell attributes (area, max rate, tracking age), GFS/ERA5 CAPE/shear/moisture gating → calibrated probability (isotonic).
2. **U-Net "LightningCast-India"** (secondary, SEVIR-trained): 6-channel ABI → 30/60-min GLM flash probability; INSAT-adapted variant flagged EXPERIMENTAL.

## 5. Output format

- Gridded: GeoTIFF/COG + JSON per timestep — `{valid_time, lead: 30|60, p_flash: [0..1]×grid, risk_band: 1–5, cell_polygons: [...], motion: [dx,dy], confidence: {...}, inputs_healthy: {satellite: bool, nwp: bool, rain: bool, radar_images: bool}, data_mode: LIVE|REPLAY|SIMULATION}`.
- Alerts: CAP-style JSON per affected block/district with P(flash), lead, preset (Protective/Operational), feature-importance "why" summary.

## 6. UI (decision support, not a weather app)

MapLibre GL map: probability heat layers (30/60 min), cell polygons + motion arrows, block/district rollup panel, forecast timeline scrubber (t−2 h → t+2 h), reliability/spread panel, data-health strip (feed ages, active fallback rung), event replay selector (SEVIR severe cases + India replay), data-mode badge always visible. No social features, no city-weather-search, no week-ahead forecast.

## 7. Evaluation (shipped inside MVP)

Held-out SEVIR test events (day-blocked): BSS vs climatology & persistence, reliability diagrams, POD/FAR/CSI at pre-registered thresholds, FSS (neighborhood 3/5/9 cells), lead-time-to-first-flash curve; India-mode: LIS-verified scores labelled EXPERIMENTAL with label-caveat note. Auto-generated scoreboard page.

## 8. Demo flow (4 min; full: Deliverable 10)

Pick Bihar case (replay) → observations animate → cells detected & tracked → nowcast runs → 30/60-min probability + motion → confidence + data-health → alert JSON for two blocks → "why" panel → scoreboard vs baselines → live-mode toggle (GFS+IMERG, labelled).

## 9. Explicitly out of MVP scope

Raw radar ingestion, ILLN real-time feed, hail/severity prediction,WoFS-style ensembles, public mobile app, week-ahead forecasting, multilingual SMS gateway (interfaces prepared, not built), LLM anything.

## 10. Success criteria

End-to-end `docker compose up` reproduces demo on a clean machine; BSS(60 min) > 0 vs climatology and ≥ persistence on SEVIR held-out events; reliability diagram monotone-ish across 5 bins; every claim on the scoreboard traceable to a stored forecast; zero unlabelled simulated data.
