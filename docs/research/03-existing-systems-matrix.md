# Deliverable 3 — Existing Systems Matrix (India + Global + Commercial + Academic)

Labels: [V] fetched · [S] snippet/literature · [U] unknown. Purpose: avoid reinventing existing infrastructure and extract the exploitable gap.

## A. Indian systems

| System | What it does / how | Data | Horizon | Users | Strengths | Limitations | Public access | PS-26072 residue (what's still missing) |
|---|---|---|---|---|---|---|---|---|
| IMD district/station **Nowcast warnings** [V] | Forecaster-compiled text + GIS (No Warning/Watch/Alert/Warning) per district & ~1,084 stations [S], 3-hourly, valid next 3 h | DWR, INSAT, synoptic, NWP guidance | 0–3 h, 3-h cycle | SDMAs, districts, public | National, institutionalized, free | District granularity; text-heavy; forecaster-intensive; no gridded probability | mausam.imd.gov.in nowcast GIS [V] | Gridded probabilistic nowcast; sub-district localization; flash-verified skill |
| IMD **Impact-Based Forecasts** (color-coded) [V] | Green/yellow/orange/red district & sub-division maps; event bulletins | multi-source | daily + event, ≤5 d | disaster managers, media | IBF institutionalized; CAP-compatible | coarse; lightning a sub-bullet | GIS pages [V] | 0–2 h dynamic risk layer |
| **Aerodrome warnings** (AMO/IAF) [S] | TAF/METAR/trends; TS/squall/hail warnings, ~1–4 h validity | airport DWR, AWOS | 0–1 h | pilots, DGCA, AAI | statutory, tight loop | airport-only, not public | SOP PDF [S] | hyperlocal public analog |
| IITM **STORM** TS prediction [V listing; product URL 404] | WRF-based thunderstorm guidance to 24 h/3-h steps [S] | WRF + radar assimilation | 0–24 h | IMD forecasters | research-grade physics incl. LPI/WRF-ELEC | guidance only; not public product | no | operational ML fusion |
| IITM **ILLN** lightning network [S: 83–134 sensors] | CG+IC flash detection, feeds Damini | proprietary sensors | NRT detection | IITM/IMD | pan-India detection efficiency quantified [S] | detection, not prediction; closed data | none | flash-verified forecast product |
| **Damini** app [V] | Alerts within 20/40 km of detected strikes; live map; claimed 30–45 min notice [S] | ILLN | alert on detection | public, farmers | free, UMANG listed | **detection-proximity, not forecast**; verified user-reported miss; low adoption | app | true pre-flash forecast |
| **Mausamgram** [V] | Gram-panchayat (12 km) forecasts, hourly→10 d | NWP post-processing | — | villagers, panchayats | genuinely fine-grained | **no thunderstorm/lightning variable** [V] | web | lightning variable at GP scale |
| **SACHET/CAP** (NDMA) [S; fetch failed] | CAP alerts to all phones (SMS/cell-broadcast), 36 States/UTs | IMD/CWC CAP XML | minutes | citizens | last-mile standard | content upstream = coarse warnings | sachet.ndma.gov.in | high-resolution alert content |
| **CROPC** Lightning Reports [S] | Annual flash/death statistics; district action plans | ILLN+IMD+press | annual | NDMA/SDMAs | only India mortality dataset | not a warning system; PDFs hard to access | press/PDF | verification ground truth context |
| State systems (Odisha/Bihar ENTLN; Karnataka **Sidilu**; AP plan) [S] | proprietary detection + SMS/app alerts | ENTLN/KSNDMC sensors | ~45 min claimed | state machinery, farmers | formal state action plans | siloed, proprietary, outside national CAP; low farmer adoption [S] | limited | unified open national product |

## B. Global operational & research systems

| System | Org | Data | Algorithm | Horizon / resolution | Lightning? | Uncertainty? | Open? | Lesson for us |
|---|---|---|---|---|---|---|---|---|
| **MRMS** [V: AWS cookbook] | NOAA/NWS | 180+ radars, GOES, HRRR, gauges, NLDN | QC 3-D mosaics + severe/QPE algorithms | analysis; 1 km / 2 min | ingested | deterministic | data open (`s3://noaa-mrms-pds`), algorithms closed | **The data pipeline is the product.** India has no MRMS equivalent → a documented open composite pipeline is itself a contribution |
| **ProbSevere v2/v3** [S: WAF 2020/2024] | CIMSS/NOAA | MRMS storm objects + ABI + total lightning + NWP growth rates | Random-forest ML → calibrated severe probabilities; v3 = "Improved Exploitation of Data Fusion" | 0–60 min, per storm object | predictor + ablation-quantified | calibrated probabilities | no (guidance in AWIPS) | **Our architectural template**: object features → ML → calibrated probability to a human |
| **LightningCast** [S: WAF 2022] | CIMSS/NOAA | GOES ABI VIS/IR | U-Net CNN → P(≥1 GLM flash next hour), 2 km/1-min | 0–60 min | **core output** | probability fields | model closed; CSPP Geo pattern public | **Direct template**: swap ABI→INSAT, GLM→ILLN/LIS labels; transfer-learning precedent (Himawari) |
| **GLM lightning jump** [S: Erdmann 2023] | NOAA | GLM flash rates | 2σ rate-change rule | 0–30 min lead | core | threshold-based; high false alarms | no | mandatory simple baseline; known FA behavior = our ML delta |
| **WoFS** [S] | NSSL | radar+satellite+lightning EnKF, 36-member 3-km CAM ensemble | ensemble DA + probabilistic hazards | 0–6 h, 3 km | assimilated | ensemble probabilities | no | gold standard we cannot build; consume NWP instead |
| Met Office **NowCast/STEPS** [S: Bowler 2006; DataPoint retired V] | Met Office | radar composite + UKV | STEPS: cascade extrapolation + downscaled NWP blending, stochastic ensembles | 0–6 h, 1–5 km | no | ensembles | no (API now paid) | blend weights by scale/lead; even rich agencies retract open data — control your data mirrors |
| BoM **STEPS** [S] | Australia | national radar mosaics | STEPS ensembles | 0–1 h (+6 h blend) | separate obs | ensembles | partial (gitlab 403) | verify **warning lead time**, not just hit rates (SWWTI) |
| JMA **HRPN** [S: WMO reports] | Japan | radar + VSRF NWP | extrapolation with non-linear motion+intensity correction, NWP blend | 0–1 h, 250 m→1 km, 5-min | separate products | probabilistic research | no | tiered resolution schedule mirrors extrapolation decay |
| **NWC SAF CI** [S] | EUMETSAT | SEVIRI IR + cloud-tracking winds | CI probability (Mecikalski-Bedka lineage) | 0–60 min, ~3 km | CI proxy | probability | software free (registered) | satellite-only CI works where radar is sparse — exactly rural India |
| **TITAN/Auto-Nowcaster** [S: Dixon & Wiener 1993] | NCAR | reflectivity | object cell tracking + CI predictors | 0–1 h | flags | deterministic+trends | open (`lrose-titan`) | 1993-era object tracking still operational backbone; reimplement via tobac/tintX |
| **PySTEPS** [V: repo/docs] | community | any gridded rain field + NWP | LK/DARTS/VET advection + S-PROG/STEPS + **NWP blending module** | 0–2 h typical | no | ensembles | **BSD-3, active** | our physics engine and baseline, free |
| Earth Networks/AEM [S] | commercial | ENTLN (~430M events/yr) | flash-rate DTA polygons | 0–45 min | core | unpublished | no | sells speed+density; no India district product |
| Vaisala Xweather [S] | commercial | NLDN/GLD360 + radar/models | ~15 s alerting, AviCast | 0–1 h | core | no | no | GLD360 covers India but enterprise-priced |
| Tomorrow.io / DTN / Pelmorex [S] | commercial | own+3rd-party feeds | proprietary ML fusion | 0–6 h | included | proprietary | no | value = detection density × latency × trust; not forecast cleverness |

## C. Academic state of the art (condensed; full: Deliverable 4)

ConvLSTM/TrajGRU (HKO) · DGMR (Nature 2021, UK) · MetNet-1/2/3 (Google) · NowcastNet (Nature 2023, China) · Earthformer (NeurIPS 2022, SEVIR SOTA CSI-M 0.4419) · RainNet · DiffCast/PreDiff (diffusion) · India studies: Mandal 2024 (XAI lightning density NE India), Chatterjee 2023 (seasonal lightning ML), Jash 2025 (GAN on IMD DWR, S. India), Saha 2025 (XGBoost lightning, Bangladesh ERA5), WRF-LPI evaluations over India.

## D. Landscape → unsolved gap → our opportunity

- **Landscape:** observation-rich detection & coarse-text warnings (India); mature object-ML fusion & satellite lightning nowcasting (US); blended probabilistic extrapolation (UK/AU/JP); dense commercial alerting.
- **Unsolved gap (evidence §1–6 in Deliverable 1 §7):** India has no gridded, probabilistic, flash-verified 0–2 h lightning nowcast at sub-district scale, no radar-poor-robust (satellite-primary) nowcaster, no open benchmark/pipeline/verification dashboard, and its fusion research never reached operations.
- **Our opportunity:** occupy the **Indian ProbSevere/LightningCast slot** as an open prototype: open data pipeline + calibrated fusion nowcast + block-scale decision support + published verification — explicitly a demonstrable prototype, not an operational replacement.
