# Data Provenance & Access (implementation view)

Research basis: `docs/research/02-data-source-matrix.md` (full matrix). This file
records what the IMPLEMENTED system actually reads and how it is cached.

## Currently implemented providers

| Provider | Mode | Source & license | Cache location | Notes |
|---|---|---|---|---|
| `sevir` (VIL/IR107/GLM) | REPLAY | SEVIR — MIT Lincoln Lab, AWS Open Data `s3://sevir`, "no restrictions on use" | `data/external/sevir/` | Single-event slabs via h5py+s3fs **HTTP range reads** (~14 MB/event); monthly GLM files cached whole (3-33 MB). Georeferenced per-event from catalog laea corners (linear interpolation, `geolocation=approximate`). |
| `synthetic` | SIMULATION | Deterministic generator (seeded), Bihar-domain 0.1° grid | — | Used for hermetic tests + guaranteed demo; every frame carries `mode=SIMULATION`. |
| `imd_radar_gif` | LIVE (visual only) | mausam.imd.gov.in public station GIFs (© IMD) | — | **Visual reference only**; served through API proxy with `X-Data-Mode: LIVE-VISUAL-ONLY`. Allowlist-only URLs, same-host redirects. |
| `gfs_nomads` | UNAVAILABLE | NOMADS open (verified reachable) | — | GRIB2 parser (cfgrib/eccodes) not provisioned — Windows Application Control blocks some compiled wheels. Router runs reduced-modality rung. |
| `imerg_earthdata` | UNAVAILABLE | NASA Earthdata (free registration) | — | Credentials not provisioned. |

## VIL / IR107 / GLM semantics

- **VIL** is stored on SEVIR's raw 0-255 scale; published SEVIR nowcasting work uses
  raw-scale thresholds (16/74/133/...). We use 74 for storm-cell detection and never
  claim physical units (`units="SEVIR VIL raw scale (0-255)"`).
- **IR107** is used as a raw-scale feature (cold-cloud proxy) plus an intensity proxy
  for radar-free detection — every proxy frame is annotated as such.
- **GLM flashes** are stored per event as (N,5): seconds-from-window-start, lat, lon,
  energy, extra. Our internal contract is (N,4): lat, lon, energy, epoch seconds.

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

MOSDAC / Earthdata credentials (not yet needed) would follow the same pattern:
environment variables (`VAJRA_*`) or a git-ignored `.env` — never in YAML or code.
