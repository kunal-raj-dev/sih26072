# USER REQUIRED INPUT

**Project Vajra · SIH 2026 Problem Statement 26072 (MoES / IMD)**  
*Audit Date: 2026-09-27 · Strict Secret Hygiene Enforced (No secrets in documentation)*

This document is the authoritative checklist of all technical inputs, data assets, credentials, and institutional decisions required from the user/team to progress from the MVP vertical slice to an operationally credible SIH solution.

---

## CRITICAL — REQUIRED TO CONTINUE

| Item | Why Needed | Where Used | Status | Format / Example |
|---|---|---|---|---|
| **Linux/WSL2 Environment or Docker Engine Deployment** | Windows Application Control and missing MSVC compilers block compiled extensions (`cfgrib`, `eccodes`, `scipy`, `cartopy`). NWP GRIB parsing and full geospatial toolchains cannot run natively on the current Windows host. | Backend runtime, provider ingestion, ML training | 🔴 BLOCKING | WSL2 Ubuntu 24.04 or Docker Desktop running Linux containers (`docker-compose.yml`) |
| **MOSDAC Account Credentials** | Mandatory to download INSAT-3D/3DR/3DS imagery (TIR1, TIR2, MIR, WV, VIS, CTT) via ISRO's `mdapi.py`. Without this, India satellite nowcasting cannot ingest official Indian satellite data. | `vajra.providers.mosdac`, `configs/default.yaml` | 🔴 BLOCKING (for India satellite mode) | Environment variables in `.env`: `MOSDAC_USERNAME=<email>`, `MOSDAC_PASSWORD=<pwd>`. Free signup: https://www.mosdac.gov.in/signup |
| **Operational Target Decision: Indian Geography vs SEVIR Sandbox for SIH** | The current MVP ML model (XGBoost) and verification scoreboard are trained and evaluated on US GOES-16/NEXRAD/GLM data (SEVIR). The team must decide whether SIH evaluation will accept the SEVIR benchmark as the method validation sandbox while India mode is phased in, or if an India-only demo is required on day 1. | System architecture, evaluation slides, presentation pitch | 🔴 BLOCKING | Team decision: "Option A (SEVIR method sandbox + India experimental)" OR "Option B (India data exclusively)" |

---

## DATA REQUIRED

| Item | What | Why Needed | Exact Format | Where to Provide | What Happens If Not Provided |
|---|---|---|---|---|---|
| **Indian Radar Data (DWR)** | Raw or gridded radar sweeps (reflectivity dBZ, radial velocity, or composite VIL) from 1 to 3 IMD Doppler radars (e.g. Patna, Kolkata, Delhi, Sohra). | Required to fulfill "multiple radars" in PS 26072. Currently, only public visual station GIFs are proxied, stretched incorrectly across India, with zero numeric data. | NetCDF / HDF5 / IRIS raw volumes or PyScanCf-compatible sweeps | `data/external/radar/` | The system must operate on the REDUCED_MODALITY rung (satellite + lightning only). The team cannot claim radar numerical nowcasting in India. |
| **Indian Lightning Ground Truth** | Flash-level lightning observations over India (latitude, longitude, timestamp, amplitude). | Required to train and verify an Indian lightning nowcast model. Current model is trained on US GLM flashes. | CSV, Parquet, or NetCDF with `lat, lon, epoch_s, energy` | `data/external/lightning/` | Quantitative verification (POD, FAR, CSI, BSS) over India is mathematically impossible; system must rely on NASA ISS LIS historical swaths (ended Nov 2023) or remain an unverified proxy. |
| **India Administrative Boundaries** | Official district and block/sub-district boundary geometries. | Required to generate localized CAP alerts by block/tehsil/district name instead of raw bounding boxes (`Cell C0001 [25.1, 85.2]`). | GeoJSON or TopoJSON (WGS84 EPSG:4326), sub-district level | `data/external/gis/india_districts_blocks.geojson` | Alerts will only display arbitrary cell bounding boxes and cannot support District Disaster Management (DDMA) decision-making. |
| **IMD AWS / Surface Observations** | Automated Weather Station (AWS) surface temperature, humidity, pressure, and wind gust observations. | Surface trigger detection for thunderstorm initiation and dryline/gust-front passage. | Tabular CSV / JSON / NetCDF from IMD Pune or state disaster portals | `data/external/surface/` | Surface convective triggering cannot be verified; model relies entirely on satellite IR cloud-top cooling. |

---

## ACCESS / CREDENTIALS REQUIRED

*Store all values ONLY in the local git-ignored `.env` file. Never commit credentials to version control.*

| Credential Name | Service / Provider | Purpose | Where to Provide | What Happens If Not Provided |
|---|---|---|---|---|
| `MOSDAC_USERNAME` / `MOSDAC_PASSWORD` | ISRO MOSDAC (https://www.mosdac.gov.in) | Download INSAT-3D/3DR/3DS HDF5 archives and NRT products. | Root `.env` | Provider reports `UNAVAILABLE`; INSAT ingestion disabled. |
| `CDSAPI_URL` / `CDSAPI_KEY` | Copernicus Climate Data Store (https://cds.climate.copernicus.eu) | ERA5 reanalysis CAPE, wind shear, and moisture for environmental gating and historical case studies. | Root `.env` or `~/.cdsapirc` | Environmental NWP features remain `NaN`; model runs on reduced-modality rung. |
| `EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD` | NASA Earthdata (https://urs.earthdata.nasa.gov) | IMERG half-hourly precipitation (GES DISC) and ISS LIS orbital lightning swaths. | Root `.env` | **Already configured & verified live** for GES DISC. Needed for ISS LIS HDF4/NetCDF downloads. |
| `NCMRWF_USERNAME` / `NCMRWF_PASSWORD` | NCMRWF Research Data Server (https://rds.ncmrwf.gov.in) | High-resolution IMDAA (12 km) reanalysis and NCUM operational numerical model fields. | Root `.env` | **Already configured & verified live**. Ingestion adapter pending GRIB parser. |
| `VAJRA_BASEMAPS__CARTO_KEY` | CARTO Basemaps (https://carto.com) | Raster basemap rendering in MapLibre GL without "API key required" watermark. | Root `.env` | **Already configured**. Falls back to keyless OpenStreetMap tiles if unset. |

---

## MODEL / ML INPUTS REQUIRED

| Item | What | Why Needed | Exact Format | Where to Provide | What Happens If Not Provided |
|---|---|---|---|---|---|
| **Deep Learning Compute Resource** | Access to an NVIDIA GPU (local RTX 3080/4090 or cloud T4/A100/Colab/Kaggle). | Training a spatiotemporal neural network (LightningCast U-Net or Earthformer) on satellite grids cannot be executed on CPU within hackathon timeframes. | Linux environment with CUDA 12.x and PyTorch 2.x | Dev machine / cloud VM | Deep learning cannot be implemented; system remains restricted to the lightweight XGBoost tabular cell model. |
| **Operational Prediction Target Definitions** | Formal meteorological threshold for "Thunderstorm": e.g., Reflectivity ≥ 40 dBZ or IMERG rain rate ≥ 10 mm/h + lightning flash ≥ 1. | PS 26072 asks for "thunderstorm and lightning nowcasting". Currently, only lightning probability `P(flash ≥ 1)` is predicted. | YAML config definitions | `configs/default.yaml` under `nowcast.targets` | Judges can challenge that thunderstorm severity/occurrence is not explicitly predicted, only lightning strikes. |
| **Lead-Time Horizons** | Confirmation of primary operational nowcast horizons: 15 min, 30 min, 45 min, 60 min, or up to 3 hours. | Dictates model sequence length and evaluation time steps. | List of integer minutes | `configs/default.yaml` (`lead_minutes: [15, 30, 45, 60]`) | Fixed at default `[30, 60]` minutes. |

---

## PRODUCT / DOMAIN DECISIONS REQUIRED

| Decision | Context | Options | Impact on Architecture |
|---|---|---|---|
| **Primary End-User Persona** | Is this dashboard designed for: (A) District Disaster Management Authority (DDMA / District Collector), (B) State IMD Meteorological Centre Forecaster, or (C) SACHET Public Alert Engine automated dispatch? | Option A: DDMA / Collector<br>Option B: IMD Duty Forecaster<br>Option C: Automated CAP Dissemination Engine | DDMA needs simple block-level action recommendations ("Shelter cattle, stop outdoor farming"); Forecaster needs raw radar/satellite spectral layers and diagnostic indices; SACHET needs machine-to-machine CAP XML. |
| **Risk Band Threshold Calibration** | Current probability thresholds (Low ≤ 0.2, Mod ≤ 0.4, Elev ≤ 0.6, High ≤ 0.8, Severe > 0.8) are arbitrary project heuristics. | Option 1: Retain project bands with explicit disclaimer<br>Option 2: Align with IMD 4-stage warning system (Green: No Warning, Yellow: Watch/Be Updated, Orange: Alert/Be Prepared, Red: Warning/Take Action) | Affects alert engine classification, UI color palettes, and decision-support semantics. |
| **False Alarm vs Missed Event Preference** | Operational trade-off in convective warning: Higher Probability of Detection (POD) causes higher False Alarm Ratio (FAR). | Option 1: Protective preset (schools, outdoor labor — high POD)<br>Option 2: Operational preset (balanced POD/FAR) | Already implemented as dual presets in `alerts.py`; team must decide which is displayed by default during presentation. |

---

## OPTIONAL BUT VALUABLE INPUT

| Item | What | Why Useful | Source |
|---|---|---|---|
| **IITM ILLN Collaboration Request** | Formal academic request to IITM Pune for research-grade lightning flash data. | Provides official ground-truth Indian lightning data; transforms project credibility from an external student effort into an institutional prototype. | Email to IITM Pune Director / Damini research group |
| **CROPC Lightning Resilient India Reports** | Annual reports by Climate Resilient Observing Systems Promotion Council (CROPC). | Provides ground-truth district-wise lightning mortality, vulnerability hot-spots (Bihar, Odisha, MP, UP), and seasonal strike statistics. | Public PDF downloads from CROPC / MoES |
| **IMD District Nowcast Bulletin Archives** | Historical text bulletins issued by IMD for severe weather events. | Allows side-by-side comparison of Vajra's 30–60 min gridded nowcast against IMD's standard 3-hourly text bulletin. | Regional Meteorological Centre (RMC) archives |

---

## ALREADY PROVIDED & VERIFIED

| Item | Details | Verification Date | Status |
|---|---|---|---|
| **NASA Earthdata Account** | Username `kunalrajdev`. GES DISC EULA accepted via URS `approve_app` for client `e2WVk8Pw6weeLUKZYOxvTQ`. | 2026-09-27 | ✅ Verified Live (fetching IMERG V07 Early run) |
| **NCMRWF Research Data Server** | Registered account verified against `https://rds.ncmrwf.gov.in/api` with Fast-API cookie authentication. | 2026-09-27 | ✅ Verified Live |
| **CARTO Basemaps Key** | Token active in `.env` and piped through `/api/v1/config` to MapLibre GL. | 2026-09-27 | ✅ Verified in UI |
| **SEVIR Sandbox Dataset** | 6 complete severe weather events cached in `data/external/sevir/events/` with VIL, IR107, and 44,000+ GLM flashes. | 2026-09-27 | ✅ Verified in Replay & Training |
| **XGBoost Late-Fusion Model** | Trained on 4 SEVIR events (3,652 samples), calibrated via isotonic PAVA, evaluated on held-out event S810646. | 2026-09-27 | ✅ Verified (BSS +0.50, POD 0.52, FAR 0.08) |

---

## EXPLICITLY NOT NEEDED

| Item | Why Not Needed |
|---|---|
| **Commercial Weather APIs (OpenWeatherMap, AccuWeather, Tomorrow.io)** | These provide point forecasts from global models, not gridded physical nowcasting from raw radar/satellite observations. Using them would destroy project credibility in front of IMD evaluators. |
| **Commercial Lightning Networks (Earth Networks / Vaisala)** | Proprietary and expensive; project aims for open-science reproducibility. |
| **Generative AI / LLM API Keys (OpenAI, Anthropic, Gemini)** | Physical atmospheric nowcasting is an Earth-observation computer vision and spatiotemporal ML task. Generative LLMs do not produce physically consistent nowcasts and are out of scope. |
| **Paid Basemap Subscriptions (Mapbox, Google Maps)** | MapLibre GL with OpenStreetMap and CARTO provides 100% free raster tiles up to 5M requests/month. |
