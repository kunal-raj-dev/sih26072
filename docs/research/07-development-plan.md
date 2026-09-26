# Deliverable 7 — Phased Development Plan

Dependency-aware phases (restructured from the brief's sketch: alert engine and real-time inference moved earlier because replay-mode demo value does not depend on privileged access; hardening merged into each phase). Each phase: objective → work → deliverable → DoD.

## Phase 0 — Research & Data Validation ✅ (this report)
- **Done:** data-access verification (Deliverable 2), systems/gap analysis (3), model/strategy selection (4), architecture design (9).
- **DoD:** all [UNKNOWN]s either resolved or converted to backlog actions with owners (Deliverable 12).

## Phase 1 — Data Foundation (week 1)
- **Objective:** every MVP input flowing into a versioned local store.
- **Work:** SEVIR bulk download + index; MOSDAC account + `mdapi.py` wrapper (archive pull INSAT L1B/CTT); **privileged-tier request filed day 1** (backlog B-1); NOMADS GFS fetcher (grib filter, India window); ERA5 CDS pulls; IMERG Early/Final; LIS flashes + climatology; IMD gridded rainfall via `imdlib`; DWR GIF scraper; xarray/Zarr store + data dictionary.
- **Deliverable:** `data/` with 1 year SEVIR + India sample months; ingestion tests in CI.
- **DoD:** one command re-downloads any dataset day; schema documented.

## Phase 2 — Baseline Engine + Evaluation Harness (week 1–2)
- **Objective:** the scoreboard exists before any ML.
- **Work:** persistence, climatology (LIS/OTD + IMERG), lightning-jump, PySTEPS LK/STEPS(+NWP blend), IR-threshold rule; metrics module (BSS, reliability, POD/FAR/CSI, FSS, SAL-lite, displacement, lead-time curves); day-blocked leave-year-out split machinery.
- **Deliverable:** baseline scoreboard on SEVIR test events.
- **DoD:** one CLI regenerates all baseline scores; numbers stored with config hash.

## Phase 3 — First ML Model (week 2–3)
- **Objective:** beat the scoreboard.
- **Work:** cell segmentation/tracking (tobac or tintX) on IMERG/VIL; feature extraction (cell stats, IR cooling, flash trends, NWP gating); XGBoost + isotonic calibration; ablation per modality.
- **Deliverable:** calibrated 30/60-min flash probabilities on SEVIR; ablation table.
- **DoD:** BSS(60 min) > 0 vs climatology and ≥ persistence on held-out events; reliability monotone-ish.

## Phase 4 — Deep Model (week 3–4)
- **Objective:** the U-Net path + open-SOTA reference.
- **Work:** LightningCast-style U-Net on SEVIR channels (focal/weighted loss); reproduce Earthformer checkpoint as reference; compare under identical harness.
- **Deliverable:** model comparison table (baseline vs XGBoost vs U-Net vs Earthformer-ref).
- **DoD:** identical splits/metrics for all models; per-lead-time curves plotted.

## Phase 5 — India Adaptation [EXPERIMENTAL] (week 4–6)
- **Objective:** the same stack on Indian data, honestly labelled.
- **Work:** INSAT channel mapping + retraining/finetuning; ERA5/GFS features for India grid; LIS-label training + label-caveat documentation; calibration to Indian flash climatology; GIF→grid radar experiment (optional); pre-monsoon vs monsoon evaluation.
- **Deliverable:** India-mode nowcast with EXPERIMENTAL badge + caveat sheet.
- **DoD:** scores reported with label limitations; no claim beyond labels' meaning.

## Phase 6 — Real-Time Inference + Alert Engine (week 5–6, parallel with 5)
- **Objective:** live operation on open feeds.
- **Work:** scheduler (30-min cycle: GFS/IMERG/INSAT-if-privileged ingest → features → model → grid → block rollup); CAP-style JSON alert emitter; forecast+score archive; fallback router (multimodal → reduced → physics → persistence → climatology) with modality-health detection.
- **Deliverable:** live API + alert stream on open data; fault-injection tests.
- **DoD:** kill any feed → system degrades and *labels* the degraded rung; alert latency within budget (Deliverable 9).

## Phase 7 — Decision-Support Dashboard (week 6–7)
- **Objective:** the operational view.
- **Work:** MapLibre map (probability layers, cells+motion, timeline scrub), block panel, reliability/spread panel, data-health strip, replay selector (SEVIR cases + India events), LIVE/REPLAY/SIMULATION badges.
- **Deliverable:** web dashboard consuming the API.
- **DoD:** every number on screen traceable to stored forecast; mode badge un-hideable.

## Phase 8 — Verification Month + SIH Packaging (week 7–8)
- **Objective:** evidence and the story.
- **Work:** run live/replay continuously; verify vs LIS/IMERG; failure analysis; presentation pack (Deliverable 10); repo cleanup, repro docs; risk-register review.
- **Deliverable:** verification report + demo script + 3-min video fallback.
- **DoD:** judges can rerun the demo; scoreboard public; all claims traced.

## First 7 days (uncertainty-reduction, zero frontend polish)

| Day | Build | Why | End-of-day output | Verify |
|---|---|---|---|---|
| 1 | SEVIR download + schema; **MOSDAC signup + privileged request**; repo scaffold | biggest dataset + longest approval lead time | `sevir/` indexed; request filed | open one event, plot 6 channels + GLM |
| 2 | GFS/ERA5/IMERG/LIS fetchers + Zarr store | all remaining inputs | India-window Zarr samples | xarray loads, coords sane |
| 3 | Split machinery + persistence & climatology baselines | the yardstick | first scoreboard rows | BSS numbers stable under re-run |
| 4 | PySTEPS LK/STEPS + lightning-jump on SEVIR/IMERG | physics baselines | baseline curves vs lead time | curves match literature shape (decay) |
| 5 | Cell tracking + feature extraction + XGBoost v0 | first learner | calibrated probabilities | beats persistence on 30-min CSI |
| 6 | Calibration + ablation + U-Net v0 start | honesty + deep path | reliability diagram + ablation table | reliability monotone-ish; ablation sensible |
| 7 | FastAPI + minimal MapLibre + one replay case | vertical slice | end-to-end demo of one severe event | `docker compose up` on clean machine |

## Parallel workstreams (5–6 person team)

| Stream | Owner profile | Weeks 1–2 | Weeks 3–4 | Weeks 5–8 |
|---|---|---|---|---|
| DATA | 1 | fetchers, store, QC (P1) | India archive pull, LIS labels (P5) | live ingest health (P6) |
| ML | 1–2 | baselines support (P2) | XGBoost+U-Net (P3–4) | India adaptation, calibration (P5) |
| BACKEND | 1 | eval harness CLI (P2) | inference service (P6) | alerts, fallback router, API |
| GIS/FRONTEND | 1 | grid/block geometries, COG tiles | map layers prototype (P7) | dashboard polish, replay UX |
| RESEARCH/PM | 1 | verification design, IMD/IITM outreach, backlog B-items | documentation | verification month, demo, pitch |

Blocked-by: ML blocked by P1–P2; dashboard blocked by API contract (fix end of week 2); India adaptation blocked by MOSDAC archive (T-3 d OK) — privileged tier only gates LIVE INSAT, not the demo.
