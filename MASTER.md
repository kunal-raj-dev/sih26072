# MASTER.md — Project Source of Truth

**SIH 2026 · Problem Statement 26072 · MoES / IMD**
**AIML-based Nowcasting of Thunderstorm and Lightning using atmospheric observation (multiple radars, satellite, lightning, model data)**
**Working name:** Project Vajra (temporary)

**Current phase:** Phase 0 (research) ✅ complete — deliverables D1–D12 in `docs/research/`.
**Next:** Phase 1 — Data Foundation (D7); file access requests B-1 (MOSDAC privileged) and B-2 (IITM ILLN) on day 1.

This is the single source of truth. Any agent or teammate should be able to read this
file and learn WHAT we are building, WHY, HOW it works, WHAT evidence supports it,
and WHAT remains uncertain. Research deliverables live in `docs/research/` (D1–D12);
this file states the conclusions and the labels behind them.

Rules: (1) every load-bearing statement carries exactly one label; (2) a label is
upgraded only with a recorded source (URL + date) or a logged decision (§13);
(3) updated at every meaningful milestone.

**Label legend:** `[VERIFIED]` page fetched (research date 2026-09-27) · `[RESEARCH]`
literature/reputable multi-source · `[DECISION]` team decision (see §13) · `[PROPOSED]`
· `[EXPERIMENTAL]` · `[BLOCKED]` · `[UNKNOWN]`.

## 1. Problem Statement

`[VERIFIED]` (team-provided PS)
> "AIML based Nowcasting of thunderstorm and lightning using atmospheric observation including multiple radars, satellite, lightning and model data."
MoES · IMD · Software · Disaster Management. Full decode: D1 §1.

## 2. Scientific Definition

- **Primary target [DECISION]:** calibrated probability of ≥1 lightning flash within a 0.1° cell in the next 30/60 min (`P(flash, cell, lead)`), plus tracked storm-cell polygons with motion vectors.
- **Horizons [DECISION]:** 0–60 min primary; 0–3 h secondary. **Update cycle:** 30 min. **Grid:** 0.1° (~10 km), rendered to block/district.
- **Precedent [RESEARCH]:** LightningCast (NOAA, operational) predicts GLM flash probability 0–60 min from ABI — our architectural template. Time-to-first-flash is a later target (D5 U6).

## 3. Verified Facts

1. **IMD serves radar as GIF/PNG images, not data** — no public numeric/historical radar channel; numeric access = paid DSP procurement. `[VERIFIED]`
2. **MOSDAC tiers:** anonymous = NRT metadata/images + Open Data; registered general = limited datasets at **3-day latency**; privileged = all data NRT; criteria for privileged unpublished. Python API `mdapi.py` (auth, bbox, 5,000 files/day). INSAT-3D/3DR/3DS: 1–8 km channels, 25-min full-disc, HDF5. `[VERIFIED]`
3. **No public Indian ground flash-level lightning dataset exists** (IITM ILLN 83–134 sensors, NRSC 46, ENTLN — all closed; feeds only Damini/state systems). `[RESEARCH]`
4. **Open NWP is genuinely usable:** GFS 0.25° GRIB2 via NOMADS (no registration); **ECMWF Open Data CC-BY-4.0** (25 km free now; 9 km, 2-h latency in 2026); ERA5/ERA5-Land CC-BY. `[VERIFIED]`
5. **IMD-GFS GRIB fields are not public** (login wall; literature: "not available in open domain"). `[VERIFIED]/[RESEARCH]`
6. **SEVIR** (`s3://sevir`, no sign-request, "no restrictions on use"): the only open, aligned satellite+**lightning**+radar+NWP nowcasting benchmark → our method sandbox. `[VERIFIED]`
7. **NASA ISS LIS** (flash-level, 2017→, free via Earthdata) + LIS/OTD 0.1° climatology = the open lightning labels over India (weak but real). `[RESEARCH]`
8. **IMD nowcast = 3-hourly district/station text+GIS (next 3 h)**; Mausamgram (12 km GP-level) has **no lightning variable**; Damini = detection-proximity alerts (20/40 km), not a forecast. `[VERIFIED]`
9. **Lightning toll:** ~1,269–1,374 deaths/yr (CROPC ALR 2023-24/2024-25), 4.15 crore flashes 2023-24; victims overwhelmingly rural outdoor workers. `[RESEARCH]`
10. **ProbSevere (operational 2017→) and its ablations prove multimodal fusion gains**; object-based ML → calibrated probabilities is the dominant operational ML pattern. `[RESEARCH]`
11. DGMR/MetNet/NowcastNet are Google/TPU-scale; **Earthformer is the best open, single-GPU SOTA reference** (official code + SEVIR checkpoints). `[VERIFIED]/[RESEARCH]`

## 4. Data Sources

Full matrix: **D2** (Deliverable 2) with physical + access tables and verification ledger. Summary of roles:
- **Predictors:** INSAT-3D/3DR/3DS imagery (MOSDAC) · GFS/ECMWF/ERA5 fields · IMERG rain.
- **Labels/truth:** GLM via SEVIR (sandbox) · ISS LIS flashes (India, weak) · IMERG (rain proxy) · IMD gridded rainfall (climatology).
- **Auxiliary/verification:** IMD DWR GIFs (visual) · LIS/OTD climatology · CROPC reports (context).

## 5. Data-Access Status

`[VERIFIED]/[RESEARCH]` — YES: SEVIR, MRMS, GFS, ECMWF Open Data, ERA5, IMERG, LIS/OTD, IMD gridded rainfall, DWR images, WeatherBench2, Himawari-9 (AWS). CONDITIONAL: MOSDAC NRT (privileged, B-1), NCUM (B-4), IMDAA (B-6), IMD API (B-3), data.gov.in. NO/BLOCKED: raw Indian radar, ILLN/NRSC/ENTLN flashes, IMD-GFS GRIB, bulk AWS feed.
**Fallback ladder [DECISION]:** SEVIR sandbox + INSAT(T-3d)+GFS/ECMWF+LIS → satellite+NWP-only (Himawari fallback) → historical replay → labelled simulation.

## 6. Architecture

**[DECISION]** — full design D9 (Mermaid diagrams, latency budget, fallback ladder, stack). Skeleton: sources → ingest/QC (satpy, mdapi, xarray) → Zarr store → 0.1° alignment → cell tracking (tobac/tintX) → features → **model router** (multimodal → reduced → physics → persistence → climatology) → isotonic calibration → forecast archive → FastAPI → MapLibre dashboard + CAP-style alert engine + auto-verification. **Software-added latency budget ≤10 min/cycle.**

## 7. Model Strategy

**[DECISION]** — Baselines (persistence, LIS/OTD climatology, lightning-jump 2σ, PySTEPS LK/STEPS) → **MVP: XGBoost late fusion** over cell+environment features (ProbSevere pattern) → **LightningCast-style U-Net** on satellite channels → **Earthformer** as open-SOTA reference (not primary). DGMR/MetNet/NowcastNet = ceiling citations. Fusion **is** evidence-backed (ProbSevere ablations; v3 "Improved Exploitation of Data Fusion") `[RESEARCH]`; role split: radar→structure/motion, satellite→pre-radar CI precursors, lightning→electrification onset, NWP→environmental gating.

## 8. Validation Standards

**[DECISION]** — full protocol D8. Metrics per output: BSS vs climatology, reliability diagrams, POD/FAR/CSI (pre-registered thresholds), FSS, displacement error, lead-time curves. Splits: day/event-blocked, leave-year-out, held-out region, pre-monsoon vs monsoon reported separately. Two operating presets (Protective = high POD / Operational = balanced) with published POD/FAR. No "accuracy" claims.

## 9. UX / Product Definition

**[DECISION]** — Primary user: **district disaster management (DDMA/Collector)**; secondary: IMD forecaster (review/guidance); end beneficiary: rural outdoor workers via downstream SACHET-style channels. **Exact decision supported:** "issue/escalate/localize a 0–2 h warning for specific blocks." Smallest coherent product: probability map + cell layer + confidence + data-health + alert JSON + scoreboard. NOT a generic weather app (D11).

## 10. USP

**[DECISION]** — Core (U1): **India's first open, flash-verified, probabilistic lightning-nowcast prototype** (the empty "Indian ProbSevere/LightningCast slot"). Secondary: U2 satellite-primary robustness for radar-poor regions; U3 calibrated uncertainty-aware decision support; U4 built-in verification/lead-time honesty; U5 graceful-degradation ladder. Full matrix: D5. Uniqueness claims limited to the *Indian, open, verified instantiation* — fusion itself is established science.

## 11. MVP

**[DECISION]** — full spec D6. SEVIR-replay vertical slice (all modalities + GLM labels) → XGBoost + U-Net with calibration → FastAPI → MapLibre (probability bands, cells+motion, timeline, data-health, mode badges) → scoreboard vs 5 baselines → CAP-style alert JSON. India-mode (INSAT+ERA5/GFS+LIS) shipped as clearly-badged EXPERIMENTAL. Success: BSS(60 min)>0 vs climatology and ≥ persistence on held-out SEVIR events; one-command reproducibility.

## 12. Development Phases

**[DECISION]** — full plan D7. P0 research ✅ → P1 data foundation → P2 baselines+eval harness → P3 XGBoost fusion → P4 U-Net/Earthformer → P5 India adaptation [EXPERIMENTAL] → P6 real-time inference+alerts → P7 dashboard → P8 verification month + SIH packaging. First-7-days plan and team workstreams in D7.

## 13. Decision Log

| # | Decision | Options | Evidence | Choice & why | Trade-off | Confidence | Revisit if |
|---|---|---|---|---|---|---|---|
| D1 | Docs-first repo, no premature stack | stack-first vs research-first | brief's operating mode | research-first | slower visible progress | High | — |
| D2 | Prediction target = P(flash, 0.1°, 30/60 min) + cell layer | density, time-to-first-flash, pixel rain, severity | LightningCast precedent; label availability; warning utility (D1 §3) | flash probability | TTFF deferred | High | ILLN access granted (B-2) → add TTFF |
| D3 | SEVIR as method sandbox, India-mode second | India-only from scratch | SEVIR = only open aligned multimodal labels [VERIFIED] | sandbox-first, transfer second | US→India domain shift work | High | strong LIS-label results arrive early |
| D4 | Satellite+NWP-first, radar optional | radar-centric | radar numeric BLOCKED [VERIFIED]; radar-poor India reality | satellite-primary | weaker storm structure signal | High | raw radar access obtained |
| D5 | MVP model = XGBoost late fusion | early fusion CNN first, DGMR-class | ProbSevere operational pedigree; student compute | late fusion first | less end-to-end "deep learning" shine | High | early fusion clearly wins in E3/E4 |
| D6 | NWP inputs = GFS NOMADS + ECMWF Open Data + ERA5 | IMD-GFS/NCUM primary | IMD-GFS closed [VERIFIED]; open sources verified | open NWP | coarser than IMD 12 km | High | NCUM registration succeeds (B-4) |
| D7 | Lightning labels = ISS LIS (+SEVIR GLM sandbox) | none/weak alternatives | no public Indian flashes [VERIFIED] | LIS + caveats | label weakness caps claims | Medium | B-2 ILLN access |
| D8 | Stack: Python/xarray/Zarr/PySTEPS/XGBoost/PyTorch/FastAPI/PostGIS/MapLibre/Docker Compose | heavier infra (K8s, Kafka) | D9 §6 justifications | lean stack | fewer resume-buzzwords | High | scale demands it |
| D9 | Late fusion now, early fusion later | single approach | degradation + ablation needs | staged | extra integration work | High | E3/E4 results |
| D10 | Pilot region: Bihar/Eastern UP (Patna DWR visual) | Kerala, Odisha, NE | CROPC hotspots + DWR presence [RESEARCH] | Bihar/E-UP | not yet ground-truthed | Medium | data quality check in P1 |
| D11 | Method validation on SEVIR (US) events; India-mode deferred until Indian labels/access | train on Indian data now | no public Indian flash data [VERIFIED] | SEVIR sandbox → held-out real event: BSS +0.50, FAR 0.08; baselines negative | US-domain evidence, India transfer unproven | High | ILLN/MOSDAC access granted (B-1/B-2) |

## 14. Unresolved Questions

- B-1..B-6 access items in D12 (MOSDAC privileged, ILLN, IMD API, NCUM, GIF terms, IMDAA CAPE). `[OPEN]`
- C-1..C-8 scientific items in D12 (LIS detection efficiency over India; MOSDAC product latency; GIF→grid georeferencing; Himawari fallback quality; Earthformer table reproduction). `[OPEN]`
- What does IMD's NOVA platform become, and can we interoperate? `[UNKNOWN]`
- SACHET/CAP integration path for a student-built alert source. `[UNKNOWN]`

## 15. Known Limitations

- No real-time Indian government observation feed available to us today `[VERIFIED]`; live mode runs on open global feeds + (if granted) privileged INSAT.
- India-mode labels (ISS LIS) are satellite-optical with sampling gaps → India-mode scores carry a permanent caveat `[RESEARCH]`.
- 0.1° grid cannot promise strike localization — by design, never claimed.

## 16. Risks (top; full register D7/D1 §12)

| Risk | Likelihood | Impact | Early warning | Mitigation | Fallback |
|---|---|---|---|---|---|
| MOSDAC privileged delayed | High | Medium | no reply in 2 weeks | open-mode design; T-3d archive; Himawari-9 AWS | D3 ladder rung 3 |
| LIS labels too weak for India training | Medium | High | E6 scores ~ climatology | SEVIR sandbox carries quantitative claims; IITM request (B-2) | replay-mode demo only |
| Model barely beats climatology | Medium | Medium | E3/E4 BSS ≈ 0 | honesty policy; demo leans on pipeline+verification+UX | publish negative result cleanly |
| MOSDAC/portal outages (observed "restoration" banner) | Medium | Low | fetch failures | multi-source design, caching | Himawari/GEE/PC mirrors |
| Team capacity over Q3–Q4 crunch | Medium | Medium | phase slippage >1 wk | cut P4/U-Net first; keep baselines+MVP | replay-only demo |

## 17. Current Implementation State

- **2026-09-27 (implementation session):** The MVP system is BUILT and RUNNING.
  - **Implemented** `[IMPLEMENTED]`: full pipeline (ingest → QC → cell detection/tracking → features → models → calibrated forecasts → risk → alerts → SQLite/npz store → FastAPI → MapLibre UI with mode badges, timeline, alert center, verification scoreboard); SEVIR real-data replay provider (HTTP range reads, 6 events cached); synthetic SIMULATION provider; IMD radar GIF LIVE-visual proxy (SSRF-hardened); fallback router; verification (POD/FAR/CSI, BSS, reliability, FSS).
  - **Measured on real data** `[VERIFIED — this repo, scripts/train_model.py + run_replay]`: XGBoost late fusion trained on 4 SEVIR events (3,652 samples, 9.0 % positive), isotonic-calibrated on 1 event; **held-out real event S810646 (43,901 GLM flashes): POD 0.52, FAR 0.08, CSI 0.50, BSS +0.498 (30 min) / +0.489 (60 min)** vs climatology. Same event, baselines only (advection/persistence/climatology): POD 0.20–0.30, FAR 0.75–0.77, **BSS −0.23/−0.55**. The ML-vs-baseline claim the research demands is therefore evidenced, not asserted.
  - **Constraints discovered** `[VERIFIED]`: Windows Application Control blocks scipy/sklearn wheels → pure-numpy image ops + PAVA calibration (no loss of function); Carto basemap tiles now need an API key → OSM raster tiles used.
  - **Tests:** 35 pytest tests green (unit + E2E + API incl. failure paths). UI verified in browser: zero console errors; real-event replay displayed.
  - **Still blocked/unknown** (unchanged): numeric Indian radar, ILLN flashes, IMD-GFS GRIB, MOSDAC privileged NRT, NWP GRIB parsing (cfgrib blocked by OS policy — interface + honest UNAVAILABLE in place).
- **2026-09-27 (Phase 0 closeout):** research executed, deliverables D1–D12 committed (`1b1171f`).
- **2026-09-27 (early):** repository initialized; brief archived; MASTER skeleton created.
