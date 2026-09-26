# Deliverable 1 — Executive Research Report

**Project:** SIH 2026 PS 26072 — AIML-based Nowcasting of Thunderstorm & Lightning (MoES/IMD)
**Working name:** Project Vajra (वज्र, thunderbolt) — *temporary*
**Date:** 2026-09-27 · **Status labels:** [VERIFIED] (page fetched) · [RESEARCH] (literature/multi-source) · [DECISION] · [PROPOSED] · [UNKNOWN]

Evidence base: five parallel research tracks (Indian observation data; NWP/open datasets; Indian systems & users; global systems; academic SOTA & validation), ~270 tool calls with direct page fetches; fetch failures recorded as evidence. Full matrices: Deliverables 2–12 in this folder. Source ledger per section.

---

## 1. Problem Understanding

### 1.1 Decoding the problem statement [RESEARCH]

| Phrase | Scientific meaning | Operational implication for us |
|---|---|---|
| "AIML based" | ML must carry predictive weight, not decorate a rules engine | But operational systems fuse ML with physics (ProbSevere = ML over storm-object features; STEPS = physics advection). "AI-only" is not how the field works. |
| "Nowcasting" | 0–6 h forecasts, observation-driven, updated frequently; distinct from NWP short-range | Our horizon: 0–60 min primary (lightning), 0–3 h secondary (thunderstorm track). |
| "Thunderstorm" | Deep convection producing lightning, squalls, hail, downbursts | Detectable via radar reflectivity (≥35–40 dBZ), IR cloud-top cooling, lightning itself. |
| "Lightning" | Electrical discharge (IC+CG); flash-rate dynamics precede severe weather | The PS names lightning twice — it is the core hazard (India: ~1,269–1,374 deaths/yr, 4.15 crore flashes 2023-24). |
| "Atmospheric observation" | Multi-sensor observations, not model output alone | Fusion is explicitly requested. |
| "Multiple radars" | IMD DWR network (~39–47 radars; X/C/S band, 10-min products) | We cannot ingest raw multi-radar volumes as students; images + future MOSDAC products only. |
| "Satellite" | INSAT-3D/3DR/3DS imagers: 1–8 km, 15–30 min, VIS/SWIR/MWIR/WV/TIR | Our strongest *accessible* Indian observation. |
| "Model data" | NWP fields (CAPE, humidity, winds) as environmental context | GFS NOMADS (open GRIB2) and ECMWF Open Data (CC-BY-4.0) are usable; IMD-GFS GRIB is not public. |

### 1.2 The ten questions

1. **Actual problem:** ~1,300+ lightning deaths/yr, concentrated in rural Bihar/Jharkhand/MP/UP/NE; warnings exist but are district-scale, 3-hourly, text-based; last-mile users (farmers) can't use app-based alerts. [VERIFIED/RESEARCH]
2. **Who experiences it:** outdoor rural workers (96% of deaths rural, 68–70% tribal), schools, farmers. [VERIFIED — DTE/CROPC]
3. **Who consumes output:** district disaster management (DDMA/Collector), IMD forecasters, state SDMAs; end beneficiary: villagers.
4. **Decision improved:** *issue / escalate / localize a 0–2 h warning for specific blocks* — the go/no-go for field work, school closure, siren/SMS.
5. **Forecast horizon:** 0–60 min (lightning), 0–3 h (storm track). [DECISION]
6. **Spatial granularity:** ~0.1° (~10 km) grid, rendered to block/district. [DECISION]
7. **Temporal granularity:** updates every 30 min (INSAT cadence; GFS 6-hourly as context). [DECISION]
8. **What to predict:** probability of ≥1 lightning flash per cell in next 30/60 min + storm-cell presence/movement — probabilistic, calibrated. [DECISION]
9. **What NOT to claim:** exact strike location, guaranteed lead time, operational-grade accuracy, real-time government data access (see §17).
10. **Success:** a calibrated, baseline-beaten, honestly-labelled prototype + reproducible pipeline + verification dashboard — demonstrable end-to-end at SIH.

**Ambiguities in the PS:** (a) "multiple radars" implies raw radar integration students cannot legally/technically obtain today; (b) no accuracy/lead-time targets stated; (c) "system" could mean forecaster guidance or public alerting — we design for the forecaster/DDMA decision layer and render public-safe outputs.

## 2. Why This Is Scientifically Hard

- **Timescale compression:** convection evolves in minutes; NWP alone misses initiation; radar sees storms only at first echo; IR cloud-top cooling precedes first 35-dBZ echo by ~30 min (basis of GOES-R CI). [RESEARCH]
- **Nonlinearity:** growth/decay defeats pure advection — why STEPS blends extrapolation with NWP beyond ~1 h and why DGMR/NowcastNet exist. [RESEARCH]
- **Class imbalance:** lightning-affected pixels are rare; without focal/weighted losses, models predict "no lightning" everywhere. [RESEARCH]
- **India-specific:** sparse radar (~39–47 DWRs vs NEXRAD 160+; Himalaya/NE gaps), monsoon weakly-organized widespread convection vs US Great-Plains storms, orographic initiation (Chota Nagpur, Western Ghats, Himalaya) → US/EU-trained models transfer poorly. [RESEARCH]
- **Label scarcity:** no public Indian ground flash-level dataset (IITM ILLN, NRSC, ENTLN all closed); ISS LIS is the only open flash source (satellite, sampling gaps). [VERIFIED]
- **Verification traps:** pixel CSI punishes small displacements (use FSS); "accuracy" is meaningless under imbalance; blurry MSE forecasts score well but are operationally useless (the DGMR motivation). [RESEARCH]

## 3. The Actual Prediction Target

Candidate targets assessed (A–M in brief): occurrence, probability, density, frequency/intensity, cell detection, cell movement, CI, severity, hazard probability, time-to-event, spatial hazard field, probabilistic forecast.

**Selected target [DECISION]:** `P(flash ≥ 1 within 0.1° cell, next 30/60 min)` — a calibrated probabilistic grid — plus a **thunderstorm cell layer** (detected/tracked convective cells with movement vectors) as the secondary product.

- Precedent: LightningCast (NOAA, operational) predicts GLM flash probability next hour from ABI — the closest operational analogue and our architectural template. [RESEARCH]
- Labels: ISS LIS flashes (open, 2017→) + SEVIR GLM (method sandbox); ILLN if access is granted (backlog B-2). [VERIFIED/UNKNOWN]
- Time-to-first-flash and density: later phases (better match to warning use-case, harder to validate). [PROPOSED]
- Rejected for MVP: exact strike localization (physically indefensible at 10 km), severity/hail (no labels), pixel-intensity nowcasting as primary (radar data access blocked).

## 4. Data Landscape — Summary (full matrix: Deliverable 2)

| Class | Best accessible option | Access | Role |
|---|---|---|---|
| Satellite (India) | INSAT-3D/3DR/3DS L1B/L2 via MOSDAC (`mdapi.py`, HDF5) | Free reg.; NRT needs privileged tier [VERIFIED] | Primary India predictor (CI precursors, cloud-top cooling) |
| Radar (India) | IMD DWR station GIFs (10-min) on mausam.imd.gov.in | Public images [VERIFIED] | Visual ground truth, demo, future GIF→grid research; **no numeric data** |
| Lightning labels | NASA ISS LIS (flash-level, NRT) + LIS/OTD 0.1° climatology | Earthdata login, free [RESEARCH] | Training labels (weak) + climatology baseline |
| NWP | GFS 0.25° NOMADS GRIB2 (zero reg.) + ECMWF Open Data (CC-BY-4.0, 25 km now / 9 km 2026) + ERA5 (CC-BY) | Open [VERIFIED] | Environmental predictors (CAPE, RH, shear, winds) |
| Precip truth | IMERG V07 (Early ~4 h / Final ~3.5 mo, 0.1°, half-hourly) | Earthdata, free [VERIFIED] | Training labels / evaluation proxy |
| India reanalysis | IMDAA 12 km hourly (CEDA / rds.ncmrwf.gov.in) | Free reg. [RESEARCH] | India-specific training fields |
| Method sandbox | SEVIR (GOES-16 ABI + GLM + MRMS + HRRR, 2017–2019+, `s3://sevir`, no restrictions) | Fully open [VERIFIED] | Build & validate the whole model stack before India adaptation |
| India labels (rain) | IMD 0.25° gridded rainfall 1901→ (`imdlib`) | Free [RESEARCH] | Climatology, verification |

**The one-line reality:** every raw Indian government *observation stream* (radar numeric, ILLN flashes, AWS bulk, IMD-GFS GRIB) is closed to students today; every *global* input (GFS, ECMWF, ERA5, IMERG, LIS, SEVIR) is open; INSAT is open-with-friction. The architecture must be satellite+NWP-first, radar-optional.

## 5. Data-Access Reality Check (Part 5 answer)

**YES (usable today):** SEVIR (S3, no sign-request) · GFS NOMADS (GRIB filter) · ECMWF Open Data · ERA5/ERA5-Land (CDS) · IMERG (Earthdata) · ISS LIS + LIS/OTD climatology · IMD gridded rainfall/temp · IMD DWR *images* (web) · WeatherBench2 · MOSDAC archive after free signup (T-3 days).

**CONDITIONAL:** MOSDAC NRT (privileged tier — criteria unpublished; apply early, backlog B-1) · NCMRWF NCUM GRIB (registration; unverified portal) · IMDAA via CEDA/RDS (signup friction) · data.gov.in API (key; catalog flaky) · MOSDAC radar catalog (JS shell, undocumented) · IMD public API (IP whitelisting, manual approval).

**NO (blocked, with reason):** IMD DWR level-II/volumetric data (paid DSP procurement; no public channel) · IITM ILLN / NRSC / ENTLN flash feeds (closed; ENTLN proprietary, licensed to states) · real-time AWS bulk (JS app on plain HTTP, no API) · IMD-GFS GRIB fields (login wall; "not available in open domain" per literature) · Damini backend data (app UI only).

**Fallback ladder [DECISION]:**
1. Ideal: INSAT (NRT) + IMD radar + ILLN + GFS/NCUM
2. `SEVIR` sandbox + INSAT (T-3d) + GFS/ECMWF + LIS labels ← **MVP data reality**
3. Satellite+NWP only (GFS + Himawari-9 AWS over India + IMERG + LIS) — fully open, zero Indian approvals
4. Historical replay (SEVIR + MOSDAC archive) — always available
5. Simulation (synthetic cells) — demo garnish only, always labelled

**Minimum meaningful combination:** INSAT IR/WV sequences + ERA5/GFS environmental fields + LIS-derived flash labels → probabilistic lightning nowcast, verified against LIS and IMD rainfall. All open. [DECISION]

## 6. Existing Systems — What They Prove (full matrix: Deliverable 3)

**India:** IMD issues 3-hourly district/station nowcast text+GIS (next 3 h) [VERIFIED]; IBF color codes; aerodrome warnings; IITM STORM (WRF guidance); IITM ILLN (83–134 sensors, closed); Damini app (20/40 km detection-proximity alerts — not a forecast; user-reported miss) [VERIFIED]; Mausamgram (12 km gram-level, **no lightning variable**) [VERIFIED]; SACHET CAP dissemination; CROPC reports; state systems (Odisha/Bihar Earth Networks, Karnataka Sidilu) — fragmented, proprietary.

**Global:** MRMS (QC mosaic on AWS — "the data pipeline is the product"); **ProbSevere v2/v3** (object-based ML fusion of radar+satellite+lightning+NWP → calibrated probabilities, operational since 2017); **LightningCast** (satellite→1-h lightning probability, DL, operational path); WoFS (ensembles; out of student scope); Met Office/BoM STEPS (blend extrapolation+NWP); JMA HRPN (tiered resolution); NWC SAF CI (satellite-only CI probability); NCAR TITAN (object tracking, open); commercial (Earth Networks, Vaisala, Tomorrow.io) — sell speed+density, no India district product, opaque verification.

## 7. The Gap (evidence-backed)

1. **No Indian ProbSevere equivalent** — India has all ingredients, no published object-based ML fusion system. [RESEARCH]
2. **No gridded 0–2 h lightning *forecast* product** at block/village scale — IMD nowcast is 3-hourly district text; Damini/Sidilu alert *after* detection. [VERIFIED]
3. **No radar-poor-region-robust nowcasting** for Himalaya/NE — satellite-primary design is a documented national need. [RESEARCH]
4. **No flash-verified public nowcast evaluation** — ILLN exists but feeds no public verification loop; NOVA just beginning. [RESEARCH]
5. **No open India nowcasting benchmark/pipeline** — IMD disseminates images, not gridded open data. [VERIFIED]
6. **Fragmentation** — state proprietary systems sit outside national CAP flow. [RESEARCH]

## 8. Proposed Solution — Project Vajra

**Vision:** an open, evidence-first thunderstorm & lightning nowcasting prototype for India that fuses satellite, NWP, and (where available) radar/lightning observations into calibrated, block-scale probability maps with lead-time honesty — built to be verifiable, not to look magical.

- **USER:** district disaster-management (DDMA/Collector) first; IMD forecaster as reviewer; villager via SACHET-style downstream text.
- **INPUT:** INSAT-3D/3DR/3DS IR/WV(+VIS) sequences · GFS/ECMWF/ERA5 environmental fields (CAPE, RH, shear) · IMERG rain · LIS flashes · IMD DWR imagery (auxiliary/verification) · ILLN flashes (if granted).
- **INTELLIGENCE:** (1) storm-cell detection/tracking (tobac/TINT-lineage) over rain-proxy fields; (2) ProbSevere-style late fusion (XGBoost over cell+environment features) → flash-probability; (3) LightningCast-style CNN (satellite → flash probability) as the deep path; (4) PySTEPS advection ensemble as motion baseline; (5) calibration layer (isotonic/Platt) + reliability monitoring.
- **OUTPUT:** 0.1° grid, 30/60-min flash probability (5 risk bands) · cell polygons + motion vectors · per-block rollup · confidence + input-health flags · CAP-style JSON alert.
- **ACTION:** DDMA sees "Blocks X,Y: P(flash≤60 min)=0.7, rising cell from NW, confidence 0.8, data: satellite+NWP only" → issue/escalate siren/SMS.

**Three data modes, always labelled in the UI:** LIVE (open feeds) · REPLAY (historical events incl. SEVIR cases) · SIMULATION (synthetic, demo garnish).

## 9. Model Strategy (full: Deliverable 4) — Baseline → MVP → Improved → Advanced

1. **Baselines (mandatory):** persistence · LIS/IMERG climatology · lightning-jump rule (2σ, Schultz 2009) · PySTEPS LK/STEPS advection · threshold rules (Z≥40 dBZ proxy).
2. **MVP model:** ProbSevere-style **late fusion** — XGBoost/logistic over storm-cell + environment features (radar/IR stats, flash-rate trends, CAPE/shear) → calibrated flash probability. Cheap, debuggable, mirrors the one proven operational pattern.
3. **Improved:** LightningCast-style **U-Net on satellite channels** (SEVIR-trained, INSAT-adapted); early-fusion variant stacking all gridded channels.
4. **Advanced:** Earthformer/ConvLSTM spatiotemporal (open code, single-GPU scale); probabilistic ensembles; time-to-first-flash regression. DGMR/MetNet/NowcastNet = ceiling citations, not targets (Google/DeepMind-scale data+TPUs).

**Fusion verdict (Part 11):** multimodal fusion **is** worth it — ProbSevere ablations + ProbSevere-v3 ("Improved Exploitation of Data Fusion") and LightningCast's MRMS-addition study show measurable gains from satellite+lightning+NWP over radar alone [RESEARCH]. Role split verified in the literature: radar → structure/motion; satellite → pre-radar CI precursors; lightning → electrification onset (fastest signal); NWP → environmental gating (is the atmosphere primed?). **Late fusion first** (modular, debuggable, graceful degradation), early fusion second. [DECISION]

## 10. Validation & the False-Alarm Problem (full: Deliverable 8)

- **Metrics per output:** field/probability → Brier skill score vs climatology, reliability diagrams, POD/FAR/CSI at pre-registered thresholds, ROC-AUC; spatial fields → FSS (+SAL diagnostics); cells → displacement error; system → **lead-time curves** (skill vs lead; time-to-first-flash). No single "accuracy."
- **Splits (leakage-safe):** block by storm day/event; **leave-year-out** (DGMR/NowcastNet precedent); one **held-out radar station** (spatial); **pre-monsoon vs monsoon evaluated separately** (regimes not interchangeable). Never random pixel/frame splits.
- **FP/FN economics:** missed lightning kills; false alarms erode trust (cry-wolf). Strategy: calibrated probabilities + user-tunable threshold presets (Protective = high POD, Operational = balanced), report both; calibration is a first-class component, not an afterthought.

## 11. Feasibility Matrix (Part 30)

| Capability | Data? | Training? | Compute? | Real-time? | Validation? | SIH? | Operational future? |
|---|---|---|---|---|---|---|---|
| Satellite+NWP flash-probability (India, LIS labels) | YES | CONDITIONAL (label weakness) | YES (1 GPU) | CONDITIONAL (INSAT NRT needs privileged) | CONDITIONAL | **YES** | YES |
| Full stack on SEVIR sandbox (all modalities) | YES | YES | YES | YES (replay) | YES | **YES** | n/a (method proof) |
| Radar-echo DL on Indian radar | NO (numeric) | NO | — | — | NO | **NO** (blocked) | CONDITIONAL |
| ILLN-fused nowcast | NO (closed) | — | — | — | — | **NO** (blocked) | YES (institutional) |
| Cell tracking + motion nowcast (rain-proxy) | YES (IMERG) | n/a (physics) | YES | YES | YES | **YES** | YES |
| District/block alert decision support | YES | — | YES | YES | YES | **YES** | YES |
| WoFS-style convection-allowing ensemble | — | NO | NO (HPC) | NO | — | **NO** | YES (institutional) |

## 12. Risks (register: Deliverable 7 / MASTER §16)

Top three: (1) **MOSDAC privileged approval delays** → design works at T-3d + fallback Himawari-9 AWS; (2) **LIS labels too weak for India training** → SEVIR method-transfer + ERA5-climatology path + IITM data request; (3) **evaluated skill barely beats climatology** → that IS a publishable finding under our honesty rules; demo leans on pipeline+verification+UX, never on inflated claims.

## 13. Claims We Must NOT Make (Part 39)

Operational-grade prediction · superior accuracy vs IMD (no access to their internal verification) · real-time government data access (unless privileged granted) · exact strike locations · guaranteed lead times · universal India performance (season/region splits only) · "100% accurate"/"AI predicts lightning" headline claims. Required evidence for each: documented out-of-sample verification vs open truth, calibration curves, and named data-access grants. (Full list: Deliverable 11.)

## 14. Final 10-Section Summary

**1. The problem in one paragraph.** Lightning kills ~1,300 Indians a year, almost all rural outdoor workers, while IMD's nowcast warnings remain 3-hourly, district-scale text and existing apps (Damini, Sidilu) only alert *after* nearby flashes are detected. The missing piece is a gridded, probabilistic, 0–2 h lightning *forecast* — before the first flash — that a district officer can act on and that is honestly verified against observations.

**2. The solution in one paragraph.** Project Vajra: an open-source nowcasting prototype that fuses INSAT geostationary imagery, open NWP fields (GFS/ECMWF/ERA5), and IMERG/LIS observations to output calibrated 30/60-min flash-probability grids plus tracked storm cells at block scale — validated on the fully-open SEVIR benchmark first, adapted to India data second, served through a decision-support map with confidence, data-health, and lead-time verification built in.

**3. What we should actually build.** A four-layer system: (1) open data pipeline (SEVIR + MOSDAC + NOMADS/ECMWF + IMERG + LIS); (2) baseline engine (persistence, climatology, lightning-jump, PySTEPS) + ProbSevere-style late-fusion model + LightningCast-style CNN; (3) alert/decision layer (0.1° probability grid → block rollup → CAP-style JSON); (4) verification dashboard (BSS, reliability, POD/FAR/CSI, lead-time curves) with three labelled data modes.

**4. What data we can actually use.** Today, fully open: SEVIR, GFS (NOMADS), ECMWF Open Data, ERA5, IMERG, ISS LIS + climatology, IMD gridded rainfall, IMD radar *images*, WeatherBench2, PySTEPS data. With free registration: MOSDAC INSAT archive (T-3 days), IMDAA. Blocked today: raw Indian radar, ILLN/NRSC/ENTLN flashes, IMD-GFS GRIB, bulk AWS. Live INSAT requires MOSDAC privileged tier — apply in week 1.

**5. What model we should start with.** XGBoost late fusion over storm-cell and environmental features (the ProbSevere pattern) for 0–60-min flash probability, trained first on SEVIR; PySTEPS and lightning-jump as physics baselines; then a U-Net (LightningCast pattern) on satellite channels; Earthformer only if time and GPU allow.

**6. What existing systems already do.** IMD: 3-hourly district nowcasts, IBF color maps, aerodrome warnings; IITM: ILLN detection + STORM guidance + Damini app; states: proprietary Earth Networks/KSNDMC alerting. Globally: MRMS (QC mosaic), ProbSevere (ML fusion probabilities), LightningCast (satellite lightning nowcast), STEPS/JMA (blended extrapolation), WoFS (ensembles), commercial alerting (speed+density).

**7. Where the real gap is.** No Indian system produces a gridded, flash-probability nowcast at sub-district scale with published verification; no radar-poor-robust (satellite-primary) Indian nowcaster exists; no open India nowcasting benchmark or verification dashboard; fusion ML research (WRF-LPI, GAN studies) never reached operations.

**8. Our defensible differentiation.** (Core) First open, flash-verified, probabilistic lightning-nowcast *prototype* for India fusing satellite+NWP(+radar when granted) — the ProbSevere slot is empty in India. (Secondary) Satellite-primary robustness for radar-poor regions; block-scale decision support with calibrated confidence; graceful-degradation ladder. (Future) Time-to-first-flash targets, vernacular/low-bandwidth last mile, human-feedback loop. We claim a credible prototype slot, not uniqueness of idea.

**9. The first working vertical slice (day 7).** SEVIR replay: 4 frames of ABI+GLM history → XGBoost/U-Net → 30/60-min GLM flash-probability grid → FastAPI → MapLibre map with cell polygons, probability bands, and a "why" panel (feature importances) — evaluated against PySTEPS + climatology baselines with CSI/BSS on the held-out test year, one end-to-end `docker compose up`.

**10. The next 7 days of development.** D1: SEVIR download + schema/eval harness; D2: MOSDAC signup + privileged request + GFS/ERA5/IMERG/LIS pullers; D3: climatology + persistence baselines with metrics; D4: PySTEPS + lightning-jump baselines; D5: XGBoost late-fusion v0 on SEVIR features; D6: U-Net v0 + calibration; D7: FastAPI + map + replay demo of one severe case. No frontend polish — uncertainty reduction only.

---

### Key sources (selection; full ledgers in Deliverables 2–3)
MOSDAC data-access-policy & API manual (fetched) · mausam.imd.gov.in radar/nowcast pages (fetched) · dsp.imdpune.gov.in (fetched) · ECMWF Open Data announcement (fetched) · NOMADS (fetched) · ERA5/ERA5-Land CDS (fetched) · IMERG (fetched) · SEVIR AWS registry (fetched) · WeatherBench2 (fetched) · Earthformer repo (fetched) · DGMR (Nature 2021, PMC full text) · NowcastNet (Nature 2023) · MetNet/MetNet-2 (ar5iv/Nat Commun) · ProbSevere v2/v3, LightningCast (AMS WAF) · CROPC/DTE lightning mortality (fetched where possible) · IMD Damini/Mausamgram listings (fetched).
