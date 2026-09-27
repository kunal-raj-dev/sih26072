# Data Architecture, Provenance & Ingestion Specification

**Project Vajra · SIH 2026 Problem Statement ID: 26072**
*AIML-based Nowcasting of Thunderstorm and Lightning using Atmospheric Observation*

---

## 1. Executive Summary & Data Philosophy

Project Vajra is designed to operate under the harsh observational realities of the Indian subcontinent, where Doppler Weather Radar (DWR) coverage is spatially fragmented (~35 operational stations with notable radar gaps in mountainous and interior regions), commercial lightning sensor networks are proprietary and closed, and geostationary satellite channels exhibit distinct latency profiles.

To achieve operational reliability, the system implements:
1. **Multi-Modality Ingestion**: Simultaneous processing of radar, satellite, lightning point vectors, numerical weather prediction (NWP), and satellite-derived precipitation.
2. **Physical Quality Control (QC)**: Source-aware, physically grounded validation filters ensuring zero corrupted or non-physical data enters inference pipelines.
3. **Canonical Coordinate Grid**: Unification of divergent projection systems (polar sweeps, Lambert Azimuthal Equal-Area, Mercator, and unprojected HDF5) onto standard $0.1^\circ$ (~10 km) and $0.02^\circ$ (~2 km) grids.
4. **Resilient Fallback Ladder**: A 5-rung operational degradation matrix that dynamically adapts to missing or degraded sensor streams without pipeline crashes.

---

## 2. Atmospheric Observation Modality Matrix

| Modality | Ingestion Source | Native Resolution & Cadence | Native Format / Protocol | Role in Pipeline | Operational Mode |
|---|---|---|---|---|---|
| **Doppler Radar (VIL / Reflectivity)** | IMD Radar Network / SEVIR Benchmark (`s3://sevir`) | $1\text{ km}$, 5–10 min / $384 \times 384$ px, 5 min | Polar sweeps (HDF5/NetCDF) / HDF5 LAEA | Core convective cell kinematics, storm core tracking (tobac), reflectivity proxy | Real-Time / Replay Benchmark |
| **Geostationary Satellite (IR & WV)** | MOSDAC INSAT-3D/3DR/3DS / SEVIR IR107 | $4\text{ km}$ (TIR1 $10.7\,\mu\text{m}$, WV $6.8\,\mu\text{m}$), 15–30 min | HDF5 (`mdapi.py` query) / HDF5 LAEA | Convective initiation precursors, anvil cooling rate ($\Delta T / \Delta t$), cloud-top height | Real-Time / Replay |
| **Lightning Flashes (Point Vectors)** | NASA ISS-LIS / SEVIR GLM / IITM ILLN proxy | Flash centroid lat/lon, epoch UTC, radiance | HDF4/HDF5 / NetCDF / HDF5 point array | Ground-truth verification, electrification onset detection, cell jump features | Live Satellite / Benchmark / Replay |
| **Numerical Weather Prediction (NWP)** | NOAA GFS NOMADS / ECMWF Open Data / NCMRWF | $0.25^\circ$, 3-hourly forecast cycles | GRIB2 / OpenDAP / NetCDF | Environmental gating: CAPE, vertical wind shear ($0\text{--}6\text{ km}$), CIN, freezing level | Real-Time / Historical Replay |
| **Precipitation Rate** | NASA GPM IMERG V07 Early Run (`GPM_3IMERGHHE.07`) | $0.1^\circ$, 30 min (~4 h NRT latency) | HDF5 via NASA GES DISC HTTPS | Convective rainfall intensity, cold pool / microburst risk proxies | Live NRT / Historical |

---

## 3. Unit Conventions & Source-Aware Quality Control

Atmospheric data streams differ widely in their raw numerical representations. Project Vajra enforces explicit source-aware physical validation in `vajra.qc.validate_frame()`:

```
                          ┌────────────────────────┐
                          │ Incoming Raw Frame     │
                          └───────────┬────────────┘
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │ Source-Aware Unit Parsing │
                        └─────────────┬─────────────┘
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            ▼                         ▼                         ▼
   IR Brightness Temp               VIL                     Precipitation
   150.0 K ≤ T ≤ 350.0 K      0 ≤ VIL ≤ 255            0.0 ≤ P ≤ 500.0 mm/h
            │                         │                         │
            └─────────────────────────┼─────────────────────────┘
                                      ▼
                        ┌───────────────────────────┐
                        │ Spatiotemporal QC Gate    │
                        │ - Timestamp < Max Latency │
                        │ - Bounding Box Contained  │
                        │ - Finite Values Check     │
                        └─────────────┬─────────────┘
                                      ▼
                        ┌───────────────────────────┐
                        │ Normalized Canonical Grid │
                        └───────────────────────────┘
```

### Specific QC Limits & Unit Regimes

- **Infrared Brightness Temperature (`bt_ir107`)**:
  - Internal Standard: **Kelvin ($[150.0, 350.0]\text{ K}$)**.
  - *Conversion from SEVIR raw*: $T_K = \text{raw} \times 0.01 + 273.15$ (when stored as int16 centigrade) or $T_K = 150.0 + \text{val} \times \frac{200.0}{255.0}$ (when raw uint8).
  - *Physical rationale*: Severe convective updrafts create overshooting tops with temperatures dropping below $210\text{ K}$ ($-63^\circ\text{C}$). Rapid cooling rates ($\Delta T / \Delta t \le -4\text{ K / 15 min}$) indicate explosive cloud top growth.
- **Vertically Integrated Liquid (`vil`)**:
  - Internal Standard: **0–255 raw scale** (equivalent to $[0.0, 80.0]\text{ kg/m}^2$).
  - Storm cell core identification threshold: $\text{VIL} \ge 74$ raw units.
- **Precipitation Rate (`precipitation`)**:
  - Internal Standard: **$\text{mm/hr}$ ($[0.0, 500.0]\text{ mm/hr}$)**.
  - Derived from IMERG Early Run calibrated rain rate.
- **Reflectivity (`refl_proxy`)**:
  - Internal Standard: **$\text{dBZ}$ ($[-40.0, 95.0]\text{ dBZ}$)**.
  - Convective threshold: $\ge 35\text{ dBZ}$; Severe hail/core threshold: $\ge 50\text{ dBZ}$.
- **Lightning Flashes (`flash`)**:
  - Internal Standard: Tuple array of shape `(N, 4)`: `[latitude, longitude, energy, epoch_seconds_utc]`.
  - Geometric filtering: drop points where $|\text{lat}| > 90$ or $|\text{lon}| > 180$.
  - Temporal filtering: drop points outside the active observation cycle $[T - 60\text{m}, T]$.

---

## 4. Geospatial Reference Frames & Projections

1. **Canonical Indian Subcontinent Grid (`india_0p1`)**:
   - EPSG:4326 (Plate Carrée, WGS84).
   - Domain: Latitude $6.0^\circ\text{N} \le \text{lat} \le 38.0^\circ\text{N}$, Longitude $66.0^\circ\text{E} \le \text{lon} \le 98.0^\circ\text{E}$.
   - Grid Shape: $321 \times 321$ cells ($0.1^\circ$ resolution, $d\text{lat} = -0.1^\circ$ north-to-south, $d\text{lon} = +0.1^\circ$ west-to-east).
2. **SEVIR Native Lambert Azimuthal Equal-Area (LAEA)**:
   - PROJ: `+proj=laea +lat_0=38 +lon_0=-98 +units=m +a=6370997 +b=6370997 +no_defs`.
   - Forward and inverse coordinate transforms implemented in `vajra.grid.LAEAProjection`.
   - Dual-engine execution: uses high-performance `pyproj` C library when available; falls back to pure-Python analytical formulas (Snyder 1987) with numerical closure tolerance $< 10^{-5}$ degrees.
3. **MapLibre GL Frontend Projection**:
   - Web Mercator (EPSG:3857).
   - Raster overlay boundaries are calculated by `gridToBounds(grid)` in `web/app.js`, ensuring crisp alignment with district boundaries.

---

## 5. Graceful Degradation Ladder

When observing real-time atmospheric systems, data feeds intermittently drop out. Rather than failing or returning generic errors, Project Vajra dynamically routes inference down a calibrated fallback ladder:

```
               ┌──────────────────────────────────────────────┐
               │ Rung 1: FULL MULTI-MODAL NOWCAST             │
               │ Radar + Satellite + Lightning + NWP + IMERG  │
               │ High confidence (Track A + Track B Ensemble) │
               └──────────────────────┬───────────────────────┘
                                      │ (Lightning drops)
                                      ▼
               ┌──────────────────────────────────────────────┐
               │ Rung 2: RADAR + SATELLITE + NWP              │
               │ Proxy lightning from VIL/IR; Kinematic track │
               │ Medium-high confidence                       │
               └──────────────────────┬───────────────────────┘
                                      │ (Radar blind zone)
                                      ▼
               ┌──────────────────────────────────────────────┐
               │ Rung 3: SATELLITE + NWP + IMERG (RADAR-FREE) │
               │ Track B U-Net + IR cooling rates + CAPE/Shear│
               │ Medium confidence (Primary India Operational)│
               └──────────────────────┬───────────────────────┘
                                      │ (Satellite drops)
                                      ▼
               ┌──────────────────────────────────────────────┐
               │ Rung 4: NWP INSTABILITY + CLIMATOLOGY        │
               │ Severe potential index based on CAPE/CIN/LIS │
               │ Low-medium confidence (Area advisory)        │
               └──────────────────────┬───────────────────────┘
                                      │ (NWP drops / Offline)
                                      ▼
               ┌──────────────────────────────────────────────┐
               │ Rung 5: DETERMINISTIC SIMULATION SANDBOX     │
               │ Hermetic synthetic generator (Bihar domain)  │
               │ Tagged mode=SIMULATION (Zero false live data) │
               └──────────────────────────────────────────────┘
```

Every API response and CAP alert header includes a mandatory `data_mode` and `rung` indicator (`RUNG_1_FULL`, `RUNG_3_SATELLITE_PRIMARY`, `SIMULATION`), ensuring absolute transparency for district disaster managers.

---

## 6. Directory Layout & Cache Organization

```
data/
├── admin/
│   ├── india_districts.geojson       # 765 unified Survey of India districts
│   └── bihar_blocks.geojson          # 534 Bihar administrative subdivision polygons
├── events/                           # Packaged historical severe weather events
│   ├── bihar_convective_outbreak/    # Real/synthetic Bihar severe lightning storm
│   ├── sevir_storm_S810646/          # Severe US squall line benchmark (43k flashes)
│   ├── sevir_storm_S818161/          # Supercell thunderstorm benchmark
│   └── sevir_storm_S824814/          # Mesoscale convective system benchmark
├── external/                         # Dynamically fetched raw telemetry
│   ├── sevir/                        # SEVIR HDF5 slabs via HTTP range reads
│   └── imerg/                        # NASA GES DISC HDF5 precipitation grids
└── models/                           # Serialized model weights & calibration tables
    ├── xgb_cell_fusion.json          # Trained 16-feature XGBoost booster
    ├── unet_lightningcast.pt         # Spatiotemporal PyTorch U-Net weights
    └── isotonic_calibrator.npz       # Monotonic PAVA empirical calibration lookup
```

---

## 7. Credential & Secret Management

In accordance with strict production security standards, **no credentials or private keys are committed to source control**:

1. **Configuration**: All environment variables are loaded from the operating system environment or a local, git-ignored `.env` file (modeled on `.env.example`).
2. **NASA Earthdata (`EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD`)**:
   - Used exclusively for NASA GES DISC IMERG precipitation retrieval and ISS-LIS flash vector downloads.
   - Requires one-time acceptance of the GES DISC End User License Agreement (EULA) via the Earthdata URS portal.
3. **CARTO Basemaps Key (`VAJRA_BASEMAPS__CARTO_KEY`)**:
   - Client-safe raster tile authorization token.
   - Exposed to frontend clients via `GET /api/v1/config`. When omitted, the UI seamlessly falls back to OpenStreetMap standard tiles.
4. **MOSDAC Geoportal (`MOSDAC_USERNAME`, `MOSDAC_PASSWORD`)**:
   - Configurable for direct ISRO SAC MOSDAC `mdapi.py` satellite catalog queries.
