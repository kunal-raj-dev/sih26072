# V2_USER_INPUTS.md — Project Vajra Version 2 Input Matrix

**SIH 2026 · Problem Statement ID: 26072 · MoES / IMD**  
**AIML-based Nowcasting of Thunderstorm and Lightning using Atmospheric Observation**  
*Classification: Authoritative Planning Checklist · Secret Hygiene Enforced*

---

## 1. Executive Summary

This document defines all external data, institutional access credentials, compute resources, and domain policy decisions required to transition Project Vajra from the V1 proof-of-concept / multi-track MVP to a scientifically rigorous, operationally defensible Version 2 platform.

To preserve strict secret hygiene, **never commit raw tokens, passwords, or private keys into source code or markdown**. All credentials must be supplied via local, git-ignored `.env` files using the environment variable names specified below.

---

## 2. BLOCKING INPUTS

These inputs dictate whether core V2 scientific components can execute in an Indian operational context or must immediately drop to synthetic/international sandbox fallbacks.

### Input B-1: NVIDIA CUDA Compute for Spatiotemporal DL Training & Domain Adaptation
- **WHAT:** Access to an NVIDIA GPU environment (minimum 16 GB VRAM, e.g., RTX 4090, A10, T4 High-RAM, or A100 via Colab/RunPod/Local Linux Workstation) with PyTorch 2.4+ and CUDA 12.x.
- **WHY:** Track B's spatiotemporal U-Net / ConvLSTM and Earthformer-based spatiotemporal nowcasting cannot be fine-tuned or trained on multi-channel satellite-radar grids on CPU within acceptable turnaround times.
- **V2 COMPONENT:** `vajra.models.unet`, `vajra.models.spatiotemporal`, `scripts/train_spatiotemporal_v2.py`.
- **WHEN NEEDED:** Immediately upon entering V2 model training and fine-tuning.
- **FORMAT:** Linux/WSL2 shell environment with `nvidia-smi` active and PyTorch CUDA backend enabled.
- **WHERE TO PROVIDE:** Execution host environment / GPU runner.
- **CAN DEVELOPMENT CONTINUE WITHOUT IT?** Yes. Track A (GBDT late fusion) and pre-trained inference on CPU can continue, but deep spatial retraining and domain adaptation will be blocked.
- **FALLBACK:** CPU inference using quantized ONNX / TorchScript runtime with spatial patch subsampling ($96 \times 96$ instead of $192 \times 192$).

### Input B-2: ISRO MOSDAC Privileged / Operational API Access
- **WHAT:** ISRO MOSDAC user account credentials with authorization for near-real-time (NRT) INSAT-3D/3DR/3DS Imager HDF5 ingestion (`TIR1`, `WV`, `MIR`, `VIS`, `CTT`).
- **WHY:** Public registered MOSDAC accounts enforce a 3-day archive latency. To demonstrate true live or near-live Indian nowcasting, automated retrieval via `mdapi.py` or MOSDAC REST endpoints is required.
- **V2 COMPONENT:** `vajra.providers.mosdac`, `vajra.models.ci`.
- **WHEN NEEDED:** Prior to live India end-to-end rehearsal.
- **FORMAT:** Environment variables:
  ```env
  MOSDAC_USERNAME="user@organization.in"
  MOSDAC_PASSWORD="<user_password>"
  MOSDAC_API_KEY="<optional_token>"
  ```
- **WHERE TO PROVIDE:** Root `.env` file.
- **CAN DEVELOPMENT CONTINUE WITHOUT IT?** Yes. Development can run on MOSDAC 3-day archive data, cached historical events, and SEVIR sandbox data.
- **FALLBACK:** Fall back to 3-day archived HDF5 replay or open Himawari-9 / EUMETSAT IODC public feeds over the Indian Ocean.

### Input B-3: Indian Convective Ground Truth Sample (Radar or Lightning)
- **WHAT:** At least 3–5 multi-hour severe convective storm events with ground truth over India. Either:
  1. IMD Doppler Weather Radar (DWR) raw sweeps / NetCDF / MaxZ grids for stations like Patna, Kolkata, Sohra, Ranchi, or Delhi.
  2. Ground-based lightning detection records (IITM ILLN or state disaster management lightning feeds: timestamp, latitude, longitude, stroke peak current).
- **WHY:** Without Indian ground truth, models cannot be quantitatively evaluated for skill (CSI, BSS, FAR, POD) in Indian convective regimes; all quantitative metrics remain US/SEVIR-bound.
- **V2 COMPONENT:** `vajra.providers.imd_radar`, `vajra.providers.radar_mosaic`, `vajra.verify`.
- **WHEN NEEDED:** During V2 Indianization and validation phases.
- **FORMAT:** NetCDF-4 (`.nc`), HDF5 (`.h5`), or tabular Parquet/CSV (`lat, lon, epoch_s, current_ka`).
- **WHERE TO PROVIDE:** `data/external/india_ground_truth/`
- **CAN DEVELOPMENT CONTINUE WITHOUT IT?** Yes. Replay validation continues on SEVIR benchmark events and NASA ISS-LIS orbital passes over India.
- **FALLBACK:** Satellite-only proxy validation using NASA ISS LIS optical flashes + NASA IMERG V07 early run precipitation bursts.

---

## 3. IMPORTANT INPUTS

These inputs significantly enhance the operational fidelity and administrative value of V2 alerts and decision-support products.

### Input I-1: Survey of India Official District & Block Boundary TopoJSON/GeoJSON
- **WHAT:** Authoritative administrative boundary polygons down to sub-district / block / tehsil level (765 districts, ~6,000 blocks) compliant with Survey of India demarcation.
- **WHY:** Enables sub-district impact warnings and exact local administrative joins, eliminating arbitrary square grid coordinate alerts.
- **V2 COMPONENT:** `vajra.geocoding`, `vajra.alerts`, `vajra.cap`.
- **WHEN NEEDED:** Foundation of V2 alerting and GIS console.
- **FORMAT:** Valid EPSG:4326 GeoJSON or TopoJSON with Census 2011/2021 `dtname`, `subdtname`, and population census tags.
- **WHERE TO PROVIDE:** `data/admin/india_blocks_census.geojson`
- **CAN DEVELOPMENT CONTINUE WITHOUT IT?** Yes. V1 currently bundles simplified synthetic/extracted district geometries (`india_districts.geojson` and `india_blocks.geojson`).
- **FALLBACK:** Retain existing bundled district/block geometries with documented disclaimer.

### Input I-2: NCMRWF / IMD High-Resolution Operational NWP Feeds
- **WHAT:** Automated access to NCMRWF NCUM (4 km / 12 km) or IMD WRF GRIB2 operational model outputs for thermodynamic and shear fields (CAPE, CIN, 0–6 km shear, mid-level dry air).
- **WHY:** NCUM provides superior Indian monsoon and pre-monsoon convective parameterizations compared to global NOAA GFS 0.25°.
- **V2 COMPONENT:** `vajra.providers.nwp`, `vajra.providers.gfs`.
- **WHEN NEEDED:** NWP integration milestone.
- **FORMAT:** Automated HTTP / OpenDAP / FTP pull credentials:
  ```env
  NCMRWF_RDS_USER="<user>"
  NCMRWF_RDS_PASS="<password>"
  ```
- **WHERE TO PROVIDE:** Root `.env` file.
- **CAN DEVELOPMENT CONTINUE WITHOUT IT?** Yes. Global NOAA GFS 0.25° NOMADS GRIB filter is 100% operational via pure-Python decoder.
- **FALLBACK:** Continue using NOAA GFS 0.25° NOMADS and ECMWF Open Data.

### Input I-3: Primary Stakeholder Operational Profile Decision
- **WHAT:** Formal institutional selection of the primary end-user persona:
  - *Option A:* State / District Disaster Management Authority (SDMA / DDMA) — Focus on block-level vulnerability, actionable Hindi/English warnings, shelter recommendations.
  - *Option B:* IMD Station Duty Forecaster — Focus on multi-spectral satellite channels, radar reflectivity overlays, sounding thermodynamic indices, and automated CAP bulletin generation.
- **WHY:** Dictates frontend layout hierarchy, default map layers, alert thresholds, and false alarm vs. missed event tuning.
- **V2 COMPONENT:** `web/app.js`, `vajra.alerts`, `vajra.risk`.
- **WHEN NEEDED:** Product definition and UX structuring.
- **FORMAT:** Formal configuration switch in `configs/default.yaml` (`system.target_persona: "forecaster" | "disaster_mgmt"`).
- **WHERE TO PROVIDE:** Configuration file.
- **CAN DEVELOPMENT CONTINUE WITHOUT IT?** Yes. System maintains dual persona toggle in UI.
- **FALLBACK:** Retain UI toggle allowing dynamic switching between "Forecaster Console" and "Disaster Management Portal".

---

## 4. OPTIONAL INPUTS

These inputs provide incremental refinement, institutional credibility, and localized calibration but are not strictly required for development or demonstration.

### Input O-1: CROPC Annual Lightning Resilient India Reports
- **WHAT:** Annual statistical reports (2020–2025) published by the Climate Resilient Observing Systems Promotion Council (CROPC) and MoES.
- **WHY:** Provides empirical ground-level lightning strike densities, casualties by state/district, and seasonal timing across Bihar, UP, Odisha, and Jharkhand to calibrate impact vulnerability scores.
- **V2 COMPONENT:** `vajra.risk`, `docs/research/`.
- **WHEN NEEDED:** Impact-based decision support tuning.
- **FORMAT:** PDF / CSV summaries.
- **WHERE TO PROVIDE:** `data/external/cropc/`
- **CAN DEVELOPMENT CONTINUE WITHOUT IT?** Yes.
- **FALLBACK:** Use published census population density as the sole exposure metric.

### Input O-2: IMD Historical District Nowcast Bulletins
- **WHAT:** Text transcripts of 3-hourly nowcast warnings issued by IMD Regional Meteorological Centres (RMCs) during historical severe weather events.
- **WHY:** Enables side-by-side display showing IMD's broad text bulletin alongside Vajra's 15-minute gridded polygon nowcast.
- **V2 COMPONENT:** `vajra.case_studies`, `web/index.html`.
- **WHEN NEEDED:** Demonstration case study packaging.
- **FORMAT:** JSON / TXT files.
- **WHERE TO PROVIDE:** `data/events/bulletins/`
- **CAN DEVELOPMENT CONTINUE WITHOUT IT?** Yes. Existing case studies already embed reconstructed IMD bulletin texts.
- **FALLBACK:** Use currently reconstructed bulletins in `src/vajra/case_studies.py`.

### Input O-3: High-Resolution Digital Elevation Model (DEM)
- **WHAT:** SRTM 90m or CartoDEM 30m digital elevation grid over northern and eastern India.
- **WHY:** Improves orographic convective triggering and cloudburst risk modeling along Himalayan foothills and Chota Nagpur plateau.
- **V2 COMPONENT:** `vajra.features`, `vajra.models.spatiotemporal`.
- **WHEN NEEDED:** Extended modeling phase.
- **FORMAT:** GeoTIFF raster (`.tif`).
- **WHERE TO PROVIDE:** `data/static/dem/`
- **CAN DEVELOPMENT CONTINUE WITHOUT IT?** Yes.
- **FALLBACK:** Approximate elevation using low-resolution geopotential height from GFS/NWP.

---

## 5. Input Tracking & Readiness Matrix

| Input ID | Name | Priority | Status | Dependency | Fallback Active? |
|---|---|---|---|---|---|
| **B-1** | CUDA Compute Environment | 🔴 BLOCKING | Available (Host has RTX) | Local execution / training scripts | Ready |
| **B-2** | MOSDAC Privileged Credentials | 🔴 BLOCKING | Registered / Pending Privileged | `vajra.providers.mosdac` | Active (Archive/Synthetic) |
| **B-3** | Indian Ground Truth Events | 🔴 BLOCKING | Missing / Restricted | Model fine-tuning & local skill scores | Active (SEVIR + ISS-LIS) |
| **I-1** | Census Block Boundaries | 🟡 IMPORTANT | Partially Provided (V1 GeoJSON) | CAP 1.2 block geocoding | Active (Bundled GeoJSON) |
| **I-2** | NCMRWF NWP Access | 🟡 IMPORTANT | Registered | Environmental gating | Active (NOAA GFS GRIB2) |
| **I-3** | Target Persona Selection | 🟡 IMPORTANT | Resolved (Dual-mode UI) | Product & alerting presets | Active (UI Switcher) |
| **O-1** | CROPC Lightning Reports | 🟢 OPTIONAL | Available in Literature | Vulnerability weighting | Active (Census density) |
| **O-2** | IMD Bulletin Archives | 🟢 OPTIONAL | Curated in code | Case study comparison | Active (Embedded bulletins) |
| **O-3** | High-Res DEM Raster | 🟢 OPTIONAL | Future Research | Orographic lifting index | Active (NWP terrain height) |
