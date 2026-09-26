# Deliverable 2 — Data Source Matrix

Every potentially relevant dataset, with student-access verdicts. Labels: **[V]** verified by fetching the page during research (2026-09-27) · **[S]** search-snippet/multi-source, not fetched · **[U]** unknown/unverified. Verdicts: YES / CONDITIONAL / NO / UNKNOWN = can a student team actually use it.

## A. Indian official sources

### A1. Physical characteristics

| # | Dataset / Product | Source | Spatial res. | Temporal res. / cadence | Variables | Formats | Archive span |
|---|---|---|---|---|---|---|---|
| A1 | IMD DWR station products | IMD — mausam.imd.gov.in/responsive/radar.php [V] | Product images (PPI/CAPPI, e.g. `caz_delhi.gif`) | ~10 min [S]; 3-h animations [V] | Reflectivity, velocity (as images) | GIF/PNG only | No public archive [V] |
| A2 | IMD DWR numeric (level-II/volumetric) | IMD / MOSDAC catalog [V link] | ~1 km vol. | 10 min | Z, V, (dual-pol on newer) | Undocumented (HDF5?) [U] | Via paid DSP only |
| A3 | INSAT-3D/3DR/3DS imager L1B | ISRO/SAC — MOSDAC [V] | VIS/SWIR 1 km; MWIR/TIR 4 km; WV 8 km | 25-min full disc [V]; 15-min sectors [S] | 6 channels: VIS 0.52–0.72, SWIR 1.55–1.70, MWIR 3.8–4.0, WV 6.5–7.0, TIR-1 10.2–11.2, TIR-2 11.5–12.5 µm | HDF5 | Multi-year (catalog) |
| A4 | INSAT derived products (CTT, CTP, CAPE-class L2, HEM rain `3DIMG_L2B_HEM`) | MOSDAC [S] | 4–8 km | 30 min | cloud-top temp/pressure, rainfall est. | HDF5 | Multi-year |
| A5 | GSMaP-ISRO hourly rain | ISRO+JAXA — mosdac.gov.in/gsmap-isro-rain [V] | 0.1° | Hourly | Gauge-adjusted precipitation (IMD 0.25° gauges) | HDF5 | 2000-03 → |
| A6 | IMD gridded rainfall | IMD Pune (CDSP/DSP; `imdlib`) [S] | 0.25° | Daily | Rainfall | NetCDF/.grd | 1901 → ~2024 [S] |
| A7 | IMD gridded temperature | IMD Pune / DSP [S] | 0.5° (or 1.0°) | Daily | Tmax/Tmin/Tmean | NetCDF | Long-period [S] |
| A8 | IMD AWS/ARG network (1,008 AWS + 1,382 ARG) [S] | IMD — aws.imd.gov.in:8091 [V: JS shell, plain HTTP] | Station | ~10–30 min [U] | T, RH, P, wind, rain | none public | Paid DSP only |
| A9 | IITM Indian Lightning Location Network (ILLN) | IITM Pune (Earth Networks tech) [S: 83–134 sensors] | Flash geo-location | NRT | CG+IC flashes | none public | none |
| A10 | NRSC Lightning Detection System | ISRO/NRSC [S: 46 sensors] | Flash | NRT | flashes | none public | none |
| A11 | Damini app alerts | IITM/ESSO [V: Play listing] | 20/40 km radii around user | ~5 min map | proximity alerts, strike map | app UI only | none |
| A12 | CROPC Annual Lightning Reports | CROPC (IMD/IITM/NDMA-supported) [S; site JS-only V-fail] | district stats | annual | flash counts, deaths, hotspots | PDF | 2019 → |
| A13 | ENTLN in India | Earth Networks/AEM (Odisha, Bihar, CROPC MoU) [S] | flash | NRT | CG+IC | proprietary | licensees |
| A14 | data.gov.in IMD datasets | MeitY/IMD [V homepage GODL; catalog 403 to bots] | varies | varies | rainfall summaries, weather | CSV/API | varies |
| A15 | IMD public APIs (nowcast, district warnings) | IMD [S: whitelisting + attribution; doc PDF unparseable] | district/station | 3-hourly | warnings, nowcast text | JSON? | live only |
| A16 | IMD DSP (paid procurement) | dsp.imdpune.gov.in [V: registration + payment, non-MoES] | station/vol. | historical | observations | on request | historical |

### A2. Access characteristics & verdicts

| # | Open? | Real-time? | API? | License / restriction | Student verdict | Prototype use | Production use |
|---|---|---|---|---|---|---|---|
| A1 | Y (images) | Y | no (web) | © IMD, unofficial scrape | **YES (visual only)** | demo ground-truth, GIF→grid research [EXPERIMENTAL] | no |
| A2 | N | — | — | paid DSP | **NO** | — | YES (institutional) |
| A3 | Y (free reg.) | privileged only; general = 3-day latency [V policy] | `mdapi.py` [V] | MOSDAC T&C; 5,000 files/day | **YES** | primary India predictor | YES |
| A4 | same as A3 | 3-day / NRT-privileged | mdapi | same | **YES** | CI features, rain proxy | YES |
| A5 | "Open Access" + SSO [V] | latency unstated [U] | SSO download | open | **YES** | rain truth proxy | YES |
| A6 | Y [S] | no | `imdlib` [S] | research use | **YES** | climatology, labels | YES |
| A7 | Y [S] | no | `imdlib` | research use | **YES** | context | YES |
| A8 | N | visual only | no | — | **NO (data)** | — | — |
| A9 | N | NRT (closed) | none | government/internal | **NO** (request via IITM — backlog) | — | YES (if granted) |
| A10 | N | — | none | internal | **NO** | — | — |
| A11 | Y (app) | Y | none | app only | **YES (as alert UX)** | UX reference | — |
| A12 | Y (PDF) | annual | no | public report | **YES (context)** | mortality/hotspot grounding | — |
| A13 | N | Y | none | proprietary | **NO** | — | — |
| A14 | Y (GODL) | mixed | API key (flaky) [V-fail] | GODL | **CONDITIONAL** | minor | minor |
| A15 | N (approval) | Y | IP-whitelisted | IMD terms | **CONDITIONAL/UNKNOWN** | alert comparison | YES (if approved) |
| A16 | paid | no | email workflow | IMD policy | **NO** | — | YES (institutional) |

## B. Global model & truth data (all usable over India)

| Dataset | Source / URL | Res. / cadence | Span | Variables of interest | License | Access | Verdict |
|---|---|---|---|---|---|---|---|
| GFS 0.25° | NOAA NOMADS — nomads.ncep.noaa.gov [V] | 0.25°, hourly→f120, 3-hourly→f384; ~3.5–5 h latency | ongoing | CAPE, RH, u/v (pressure levels), precip | US public domain | GRIB2 + grib filter, zero registration | **YES** |
| ECMWF Open Data (IFS/AIFS) | ecmwf.int — open catalogue [V: CC-BY-4.0, 25 km free now; 9 km, 2-h latency in 2026] | 0.25° | 2022→ (IFS open) | CAPE-class, T/q/u/v, precip | CC-BY-4.0 | free | **YES** |
| ERA5 / ERA5-Land | Copernicus CDS [V] | 0.25° / 0.1°, hourly | 1940→ / 1950→ | CAPE, convective precip, RH, winds, MSLP | CC-BY-4.0 | cdsapi, free account | **YES** |
| IMERG V07 | NASA — gpm.nasa.gov/data/imerg [V] | 0.1°, half-hourly | 2000→ | precipitation (Early ~4 h / Late ~14 h / Final ~3.5 mo) | free, Earthdata | HTTPS/S3/GEE/PC | **YES** |
| IMDAA reanalysis | NCMRWF/CEDA — rds.ncmrwf.gov.in [V: app shell] + catalogue [S] | 12 km, hourly | 1979→ (extended) [S] | UM dynamics/physics fields | free for research [S] | CEDA/JASMIN or RDS signup | **YES (friction)** |
| NCUM/NGFS operational | NCMRWF [site timeout V; specs S] | ~12 km global, 3–4 km regional [S] | ongoing | full model fields, GRIB2 via UMRider [S] | registration required | unverified portal | **CONDITIONAL** |
| IMD-GFS T1534 / WRF | nwp.imd.gov.in [V: login wall] | 12 km / 3 km [S] | ongoing | full fields | not public ("not available in open domain" [S]) | — | **NO** |
| LIS/OTD climatology (HRAC) | NASA GHRC [S] | 0.1°, monthly/annual | 1995–2014 | flash-rate climatology | free, Earthdata | — | **YES** |
| ISS LIS (flash-level) | NASA GHRC/LANCE [S; GHRC hosts flaky V-fail] | event/group/flash + NRT 0.1° counts | 2017→ | optical flashes | free, Earthdata | Earthdata Search | **YES** |
| WeatherBench2 | google-research/weatherbench2 [V] | 0.25°–6°, Zarr on GCS | 1959–2023 | ERA5 fields + IFS baselines | Apache-2.0 code; data license per folder | anonymous xarray | **YES** |

## C. Research / benchmark datasets

| Dataset | Source | Geography / span | Contents | License | Access | India relevance | Verdict |
|---|---|---|---|---|---|---|---|
| **SEVIR** | MIT LL — `s3://sevir` (registry.opendata.aws/sevir [V]) | US/GOES-East, 2017–2019+ | 384×384 @2 km, 5-min: ABI C02/C07–C09/C13–C15 + **GLM lightning (LTM)** + MRMS VIL + (HRRR via sevir_challenges); ~2 TB (subset ~2 GB) | "No restrictions on use" [V] | `aws s3 --no-sign-request` | none geographic; **the method sandbox** — only open dataset with aligned satellite+lightning+radar+NWP | **YES — best for initial experimentation** |
| MRMS | NOAA NODD — `s3://noaa-mrms-pds` [S] | CONUS, 2000s→ | QC composite reflectivity 0.01°/2-min, QPE, MESH | public domain | anonymous S3 | method reference; pairs with SEVIR | **YES** |
| HKO-7 | Shi et al. 2017 authors [S] | Hong Kong 2013–15 | radar CAPPI 480×480 @15 min | unclear | email authors | low | **CONDITIONAL/NO** |
| MetNet data | Google | CONUS | — | not released | — | — | **NO** |
| PySTEPS example data | github.com/pySTEPS/pysteps-data [V] | FMI/MCH/BOM/MRMS/DWD samples | radar composites, NWP grids | per-provider (one non-commercial) | git clone | plumbing tests | **YES** |
| Earthformer training stack | amazon-science/earth-forecasting-transformer [V] | SEVIR VIL 13→12 frames, 384×384 | code Apache-2.0 + pretrained `earthformer_sevir.pt` | Apache-2.0 | git + S3 script | direct baseline reproduction | **YES** |
| GOES-16/19 ABI on GEE | Google Earth Engine [V] | Americas 2017→ | 16-band 2 km/10-min | open | GEE API | method dev only (wrong sector) | **YES** |
| Himawari-9 AHI | AWS Open Data (JMA/NESDIS P-Tree) [S] | 140.7E full disc incl. India | 10-min multispectral | open | anonymous S3 | **fallback live satellite for India** if MOSDAC NRT delayed | **YES** |
| Planetary Computer | Microsoft [S] | global | ERA5 Zarr, GOES CMI, IMERG | free | STAC API | hosting convenience | **YES** |

## D. Access-class separation (brief Part 4 requirement)

1. **Public & directly usable:** SEVIR, MRMS, GFS NOMADS, ECMWF Open Data, ERA5/Land, IMERG, LIS/OTD, WeatherBench2, IMD gridded rainfall/temp, IMD DWR images, Himawari-9 AWS, PySTEPS data.
2. **Public but technically difficult:** MOSDAC (signup + mdapi + 3-day tier), IMDAA (CEDA/RDS), GEE/Planetary Computer APIs, ISS LIS (Earthdata).
3. **Research-accessible:** NCUM (registration), HKO-7 (authors).
4. **Restricted:** ILLN, NRSC LDS, real-time AWS bulk, IMD-GFS GRIB, MOSDAC privileged tier.
5. **Commercial:** ENTLN, Vaisala GLD360, Tomorrow.io, DTN.
6. **Historical only:** IMD gridded climatology, LIS/OTD, CROPC reports, SEVIR (2017–19+).
7. **Unknown:** MOSDAC radar-catalog contents, IMD API exact endpoints, MOSDAC product-level latency.
8. **Simulate/replay only for demo:** IMD raw radar (until granted), ILLN flashes (until granted) — always labelled SIMULATION/REPLAY.

## E. Verification ledger (summary)

- **Fetched during research [V]:** mausam.imd.gov.in (radar.php live GIF, DWR-network page "Under Maintance", district nowcast GIS), dsp.imdpune.gov.in (paid policy, gridded selector), mosdac.gov.in (policy tiers, API manual incl. `mdapi.py` params/quotas, signup fields, INSAT-3DR channel table, GSMaP-ISRO page, restoration notice), data.gov.in (GODL homepage), aws.imd.gov.in:8091 (JS shell), Damini Play listing, mausamgram.imd.gov.in (no lightning variable), tropmet.res.in (STORM listed; product URL 404), NOMADS, ERA5/ERA5-Land CDS, IMERG, SEVIR AWS registry, WeatherBench2 docs, pysteps-data, Earthformer repo, GEE GOES-16/IMERG pages, MOSDAC re-check, ECMWF open-data announcement.
- **Snippet-only [S]:** radar/AWS network counts, INSAT sector-scan cadence, NCUM specs, ILLN sensor counts, CROPC figures, ISS LIS product details, MRMS bucket, Himawari-AWS, HKO-7 route, IMD API whitelist details, commercial pricing.
- **Unresolved [U]:** MOSDAC privileged criteria, MOSDAC radar-catalog contents/formats, IMDAA CAPE availability, ISS LIS detection efficiency over India (label quality), data.gov.in live IMD dataset list.
