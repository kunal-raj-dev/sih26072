# IMPLEMENTATION STATUS

**Last updated:** 2026-09-27 (build session) · **Source of truth:** `MASTER.md`

## 1. Repository audit (pre-build)

| Area | State | Notes |
|---|---|---|
| Documentation | **WORKING** | README, MASTER.md (filled, decisions D1–D10), research brief, 12 deliverables. No contradictions with MASTER.md found. |
| Source code | **MISSING → BUILT** | No code existed before this session (docs-only by Decision D1). Implemented below. |
| Data | **MISSING → PARTIAL** | SEVIR catalog + March-2019 GLM + replay events cached under `data/external/sevir/` (git-ignored). |
| Tests / Docker / API / frontend | **MISSING → BUILT** | pytest suite (35 tests), FastAPI app, MapLibre UI, Dockerfile + compose. |

**Environment findings (verbatim, load-bearing):**
- Python 3.13.14 (venv), Node 25/npm 11. Network: PyPI ✅, NOMADS ✅, mausam.imd.gov.in ✅, `s3://sevir` ✅.
- **Windows Application Control blocks scipy's compiled extensions** on this machine → the codebase deliberately carries **no scipy/sklearn dependency**; connected components / smoothing / dilation (`vajra/ndx.py`) and isotonic calibration (PAVA) are pure numpy. XGBoost, h5py, s3fs, fastapi, pydantic, PIL all import cleanly.
- SEVIR facts established empirically: layout `CATALOG.csv` + `data/<type>/<year>/…`; catalog `id` column = event key; per-event lat/lon corners + laea projection in catalog; h5 image slabs are (H, W, T) with row 0 = north; VIL 384² @2 km, IR107 192², single-event slab ≈ 14 MB over HTTP range reads (~10 s), full grid files (12–17 GB) never downloaded.

## 2. What was built (this session)

### Foundation
`pyproject.toml` · `configs/default.yaml` (all thresholds configurable) · `src/vajra/config.py` (YAML + `VAJRA_*` env overrides, no secrets) · `logsetup.py` (structured JSON logs) · `schemas.py` (typed models; honesty fields mandatory: mode, quality, rung, provenance) · `grid.py` (GridSpec, India 0.1°, SEVIR per-event grids, regrid weights).

### Data layer
`providers/base.py` (`AtmosphericDataProvider` contract) · `providers/synthetic.py` (deterministic SIMULATION events) · `providers/sevir.py` (REAL historical REPLAY: catalog, range-read event preparation with local cache, per-modality frames, flash epoch-time contract) · `providers/imd_radar.py` (LIVE visual-only GIFs; allowlist-only SSRF-hardened fetch) · `providers/nwp.py` (GFS/IMERG interfaces with honest UNAVAILABLE) · `qc.py` (range/staleness/coordinate/missing validation; verdicts attached, never silent).

### Processing & models
`ndx.py` (pure-numpy label/dilate/smooth) · `cells.py` (threshold detection + greedy tracker with speed gate + predicted path) · `features.py` (12-feature contract `FEATURE_NAMES`; env features pluggable-NaN) · `models/`: persistence, climatology (BSS reference), 2σ lightning-jump, advection (motion-only, documented), **XGBoost late fusion + isotonic calibration** (MVP model, D5), **fallback router** (FULL_FUSION → REDUCED_MODALITY → PHYSICS_BASELINE → PERSISTENCE → CLIMATOLOGY, D9) · `verify.py` (POD/FAR/CSI, Brier/BSS, reliability bins, FSS).

### Products & serving
`render.py` (risk-band palette = UI legend, observation renders) · `risk.py` (documented bands, stored factors) · `alerts.py` (presets protective/operational, suppression window, reason + contributing signals) · `store.py` (SQLite + npz/PNG artifacts; events/runs/forecasts/alerts/health/verification) · `pipeline.py` (cycle orchestration; **outcome settlement**: forecasts labelled against actual flashes strictly after issue time; training-sample collection) · `api/app.py` (all endpoints in `docs/API.md`) · `web/` (MapLibre UI, vendored for offline demo).

### Tests & ops
`tests/` — 35 tests: ndx, QC (incl. future/stale/invalid-coord failure paths), cells/tracking, baselines math, calibration monotonicity, verification hand-checks, E2E vertical slice on the synthetic event (cycles, alerts, settlement, storage round-trip, honesty labels), full API flow over HTTP incl. 404/UNAVAILABLE honesty · `Dockerfile` + `docker-compose.yml` · `scripts/prepare_sevir_events.py`, `scripts/train_model.py` (leave-events-out split + calibration), `scripts/run_demo.py`.

## 3. Honest capability matrix

| Capability | Status | Evidence |
|---|---|---|
| Deterministic pipeline (ingest→QC→cells→features→model→forecast→alert) | **IMPLEMENTED** | E2E test + API flow test |
| Real historical event replay (SEVIR, 3 modalities) | **IMPLEMENTED** | events cached via range reads; provider tests run on real cached slabs |
| Baseline nowcasts + scoreboard | **IMPLEMENTED** | `verify.py` + run verification metrics |
| ML late-fusion model (XGBoost, calibrated) | **IMPLEMENTED (training on real events in progress)** | artifact stores provenance; SIM/REAL flagged in model_version |
| Fallback ladder with visible rung | **IMPLEMENTED** | router + `fallback_rung` on every forecast + UI badge |
| Outcome verification vs actual flashes | **IMPLEMENTED** | settlement in pipeline; scoreboard in UI |
| Live IMD radar imagery (visual only) | **IMPLEMENTED** | proxy endpoint + honest header; numeric radar stays BLOCKED |
| Live NWP ingestion | **BLOCKED (env)** | cfgrib blocked by OS policy; interface + UNAVAILABLE health in place |
| India-domain real events | **BLOCKED (access)** | per research (MASTER.md §5); SEVIR covers method validation |

## 4. Phase log

| Phase | Status | Notes |
|---|---|---|
| Audit + plan | ✅ | this file |
| Foundation | ✅ | |
| Data layer | ✅ | SEVIR replay (6 real events cached) + synthetic + live-visual radar |
| Processing | ✅ | pure-numpy image ops (OS policy constraint) |
| Nowcast engine | ✅ | baselines + XGB fusion + router + calibration |
| Products (risk/alerts/store) | ✅ | |
| API | ✅ | docs/API.md |
| UI | ✅ | map-first, mode badges, timeline, alert center, scoreboard — browser-verified, 0 console errors on the real-event replay |
| Tests | ✅ | 35 passing (unit + E2E + API) |
| Docker/docs | ✅ | Dockerfile, compose, DATA.md, API.md |
| Real-data model training | ✅ | 4 train / 1 cal / 1 held-out test; **test event: BSS +0.50, POD 0.52, FAR 0.08**; baselines on same event: BSS −0.23/−0.55 (negative) — comparison evidenced in MASTER.md §17 |
| SIH demo rehearsal | ⬜ | scripts/run_demo.py + UI ready; demo script in docs/research/10-sih-demo-plan.md |
