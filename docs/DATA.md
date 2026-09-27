# Data Provenance & Access (implementation view)

Research basis: `docs/research/02-data-source-matrix.md` (full matrix). This file
records what the IMPLEMENTED system actually reads and how it is cached.

## Currently implemented providers

| Provider | Mode | Source & license | Cache location | Notes |
|---|---|---|---|---|
| `sevir` (VIL/IR107/GLM) | REPLAY | SEVIR — MIT Lincoln Lab, AWS Open Data `s3://sevir`, "no restrictions on use" | `data/external/sevir/` | Single-event slabs via h5py+s3fs **HTTP range reads** (~14 MB/event); monthly GLM files cached whole (3-33 MB). Georeferenced per-event from catalog laea corners (linear interpolation, `geolocation=approximate`). |
| `imerg` (IMERG V07C Early, precipitation) | **LIVE** | NASA GES DISC `GPM_3IMERGHHE.07` (Early run, ~4 h NRT); Final run `GPM_3IMERGHH.07` fallback for historical slots | `data/external/imerg/` | **Requires Earthdata Login** — credentials live ONLY in git-ignored `.env`; one-time GES DISC EULA acceptance via the URS `approve_app` resolution URL (completed 2026-09-27). India window 0.1° slices, `geolocation=exact`. Naming: `3B-HHR-*.MS.MRG.3IMERG.YYYYMMDD-SHHMMSS-*.HDF5`; grid stored (time, **lon**, lat) → transposed to (lat, lon). GES DISC legacy-server retirement announced for ≥2026-09-30 — cloud successor `data.gesdisc.earthdata.nasa.gov` uses the same paths. |
| `synthetic` | SIMULATION | Deterministic generator (seeded), Bihar-domain 0.1° grid | — | Used for hermetic tests + guaranteed demo; every frame carries `mode=SIMULATION`. |
| `imd_radar_gif` | LIVE (visual only) | mausam.imd.gov.in public station GIFs (© IMD) | — | **Visual reference only**; served through API proxy with `X-Data-Mode: LIVE-VISUAL-ONLY`. Allowlist-only URLs, same-host redirects. |
| `gfs_nomads` | UNAVAILABLE | NOMADS open (verified reachable) | — | GRIB2 parser (cfgrib/eccodes) not provisioned — Windows Application Control blocks some compiled wheels. Router runs reduced-modality rung. |
| ISS LIS (flash labels) | UNAVAILABLE | NASA GHRC (same Earthdata account) | — | Credentials work; orbit-file parsing not yet implemented (backlog C-1). |

## Unit Conventions & Quality Control Regimes

All incoming atmospheric observation frames are subject to source-aware physical range checks in `vajra.qc.validate_frame()`:

- **IR107 Brightness Temperature (`bt_ir107`):** Stored internally in **physical Kelvin ($[150.0, 350.0]\text{ K}$)**.
  - SEVIR HDF5 stores `ir107` as `int16` scaled by $0.01^\circ\text{C}$. The conversion to Kelvin is $T_K = \text{raw} \times 0.01 + 273.15$.
  - For raw `uint8` inputs (0–255 scale), the linear conversion is $T_K = 150.0 + \text{val} \times \frac{200.0}{255.0}$.
  - Calibrated Kelvin values allow physically grounded convective cloud-top cooling rate calculations ($\Delta T / \Delta t$) and realistic IR-to-intensity proxies without saturation.
  - Validated by source-aware QC: `("sevir", "bt_ir107")` expects $[150.0, 350.0]\text{ K}$; `("sevir_raw_ir", "bt_ir107")` allows $[0.0, 255.0]$.
- **VIL (`vil`):** Stored on SEVIR's raw 0–255 scale; published SEVIR nowcasting literature uses raw-scale thresholds (16/74/133/...). We use 74 for convective storm-cell core detection (`units="SEVIR VIL raw scale (0-255)"`).
- **Precipitation (`precipitation`):** NASA IMERG Early Run calibrated rain rate in **$\text{mm/hr}$ ($[0.0, 500.0]\text{ mm/hr}$)**. Ingested via `ImergProvider` (`Modality.SURFACE`) and wired into feature extraction (`rain_max`, `rain_mean`) and fallback convective intensity detection.
- **Reflectivity (`refl_proxy`):** Radar equivalent reflectivity in **$\text{dBZ}$ ($[-40.0, 95.0]\text{ dBZ}$)**.
- **Lightning Flashes (`flash`):** Point flash array with internal schema `(N, 4)`: `[latitude, longitude, energy, epoch_seconds_utc]`. Invalid geographic coordinates ($|\text{lat}| > 90$ or $|\text{lon}| > 180$) are dropped during QC.

## Coordinate Frames & Geospatial Projections

1. **Canonical India Regional Grid (`india_0p1`):**
   - Spatial bounds: $6.0^\circ\text{N} \le \text{lat} \le 38.0^\circ\text{N}$, $66.0^\circ\text{E} \le \text{lon} \le 98.0^\circ\text{E}$.
   - Grid specification: regular plate carrée (EPSG:4326), $d\text{lat} = -0.1^\circ$ (descending, row 0 = north), $d\text{lon} = 0.1^\circ$, $321 \times 321$ pixels.
2. **SEVIR Native Projection (LAEA):**
   - PROJ definition: `+proj=laea +lat_0=38 +lon_0=-98 +units=m +a=6370997 +b=6370997 +no_defs`.
   - Exact forward and inverse coordinate transforms implemented in `vajra.grid.LAEAProjection` (using `pyproj` C library with pure-Python Snyder 1987 analytical fallback).
   - Invariant: `inverse(forward(lat, lon)) == (lat, lon)` with tolerance $< 10^{-5}$ degrees.
3. **MapLibre GL Frontend Alignment:**
   - Display projection: Web Mercator (EPSG:3857).
   - Raster overlay bounds computed by `gridToBounds(grid)` in `web/app.js`: maps image corners `[top-left, top-right, bottom-right, bottom-left]` respecting row 0 orientation and eliminating aspect ratio distortion for both positive and negative $d\text{lat}$.


## Environment constraints discovered during the build

- Windows **Application Control** blocks `scipy` compiled extensions on this machine
  → the system deliberately has **no scipy/sklearn dependency**: connected components,
  smoothing, dilation (vajra/ndx.py) and isotonic calibration (PAVA) are pure numpy.
- SEVIR h5 slabs are (H, W, T) → transposed to (T, H, W) at preparation time;
  image row 0 = north edge (grid derived accordingly).

## Credentials

| Credential | Purpose | Where it lives |
|---|---|---|
| `VAJRA_BASEMAPS__CARTO_KEY` | CARTO Basemaps API key — removes the keyless watermark on the raster basemap (`basemaps.cartocdn.com`). Public tile-access token by design; served to the browser via `GET /api/v1/config`. Non-commercial tier: free up to 5M tile requests/month. | Environment variable or git-ignored `.env` (template: `.env.example`) |
| `EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD` | NASA Earthdata Login — IMERG (implemented, LIVE) and ISS LIS (backlog). **One-time setup done 2026-09-27:** account `kunalrajdev` accepted the NASA GESDISC DATA ARCHIVE EULA (the URS `approve_app` flow for client `e2WVk8Pw6weeLUKZYOxvTQ`). | Git-ignored `.env` or environment variables — NEVER in YAML, source, examples, or tests |
