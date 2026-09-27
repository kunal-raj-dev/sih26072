# Required User Inputs — Credentials & Registrations

**Project Vajra · SIH 2026 PS 26072 · last updated 2026-09-27**

Everything the team must register for, approve, or paste into the environment for
the system to reach its full planned capability. **Nothing here blocks the current
vertical slice** — the SEVIR replay pipeline, baselines, API, and UI run with zero
credentials (see §4). Items are ordered by priority.

Status legend: ✅ obtained · 🟡 requested/pending · ⬜ not started · ➖ not needed

---

## 1. Free registrations (self-service, do these now)

### 1.1 MOSDAC account — `HIGH`

| | |
|---|---|
| **Register at** | https://www.mosdac.gov.in/signup |
| **Cost** | Free (email + mobile verification, "Purpose" field required — use: *academic nowcasting research, SIH 2026 PS 26072*) |
| **Unlocks** | INSAT-3D/3DR/3DS satellite imagery via the `mdapi.py` API — the India-mode satellite predictor |
| **Tiers (verified)** | General account = archive with **3-day latency** (sufficient for training data). **Privileged** account = near-real-time — request it in the same application; approval criteria are unpublished, so file early (research backlog **B-1**) |
| **Env vars** | `MOSDAC_USERNAME`, `MOSDAC_PASSWORD` |
| **Status** | ⬜ |

### 1.2 NASA Earthdata Login — `HIGH` — ✅ obtained & verified live

| | |
|---|---|
| **Register at** | https://urs.earthdata.nasa.gov (free) |
| **Unlocks** | **IMERG half-hourly precipitation — IMPLEMENTED & LIVE** (`vajra/providers/imerg.py`, GES DISC `GPM_3IMERGHHE.07` Early run, India 0.1° window) + **ISS LIS flash-level data over India** (labels for the India model; parsing pending, backlog C-1) |
| **Env vars** | `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD` (git-ignored `.env`) |
| **One-time setup done 2026-09-27** | Logged in via URS and accepted the **NASA GESDISC DATA ARCHIVE EULA** (`approve_app` for client `e2WVk8Pw6weeLUKZYOxvTQ`) — required before any GES DISC download works |
| **Verified live** | `get_history()` returned real India-window frames (max 38.65 mm/hr, mode LIVE) |
| **Status** | ✅ |

### 1.3 Copernicus CDS API key — `MEDIUM`

| | |
|---|---|
| **Register at** | https://cds.climate.copernicus.eu (free; API key shown on your profile page) |
| **Unlocks** | ERA5 / ERA5-Land environmental features (CAPE, humidity, winds) via the `cdsapi` client |
| **Env vars** | `CDSAPI_URL`, `CDSAPI_KEY` |
| **Status** | ⬜ |

### 1.4 NCMRWF / CEDA account — `MEDIUM-LOW`

| | |
|---|---|
| **Register at** | https://rds.ncmrwf.gov.in (or CEDA/JASMIN for the mirror) |
| **Unlocks** | IMDAA 12 km India reanalysis; NCUM model fields (backlog **B-4**, **B-6**) |
| **Env vars** | `NCMRWF_USERNAME`, `NCMRWF_PASSWORD` |
| **Status** | ✅ Registered + login verified against the live API (2026-09-27) |

**Verified access recipe** (site was unreachable during research; probed live 2026-09-27):

- API base: `https://rds.ncmrwf.gov.in/api` (the web app is a Vite SPA; `/auth/login`
  paths without the `/api` prefix just serve the SPA shell).
- Login: `POST /api/auth/login` with JSON `{"email": ..., "password": ...}` —
  FastAPI backend; the username-style field is `email`, not `username`.
- Response: JSON `{"access_token", "token_type": "bearer"}` **and** an HttpOnly
  `access_token` cookie (`Path=/`, Max-Age 15 days). The backend authenticates
  API calls via the **cookie** — sending `Authorization: Bearer` to `/api/auth/me`
  returns 401 "Not authenticated"; the `Cookie: access_token=...` header works.
- Session check: `GET /api/auth/me` → account JSON (id, email, name, institution).

---

## 2. Institutional approvals (requests, not keys — send early)

These are "apply and wait" items with long lead times. Send the request email the
same day you register for §1.1 — they are the highest-value data paths for the
India model.

| Item | Contact route | Unlocks | Backlog | Status |
|---|---|---|---|---|
| **IITM lightning network (ILLN) flash data** | Data request to IITM Pune (lightning/Damini team) | Ground-truth lightning labels — upgrades India-mode from satellite-only labels (weak) to verified flashes | B-2 | ⬜ |
| **IMD public API access** | IMD data cell / RMC (IP whitelisting + attribution required) | Official nowcast/warning feed for comparison and alert interop | B-3 | ⬜ |
| **MOSDAC privileged tier** | Included in the §1.1 application | Near-real-time INSAT → LIVE satellite mode | B-1 | ⬜ |

---

## 3. Where credentials go (never in git)

Put values in a **git-ignored `.env`** at the repo root (`.env` and `.env.*` are
already excluded by `.gitignore`; keep only `.env.example` tracked):

```dotenv
# .env — NEVER commit this file
MOSDAC_USERNAME=
MOSDAC_PASSWORD=
EARTHDATA_USERNAME=
EARTHDATA_PASSWORD=
CDSAPI_URL=https://cds.climate.copernicus.eu/api
CDSAPI_KEY=
NCMRWF_USERNAME=
NCMRWF_PASSWORD=
```

Rules (enforced by project policy):
- No secret values in source code or YAML configs (`configs/default.yaml` stays clean).
- No hardcoded API keys anywhere, including the frontend.
- Providers read credentials from the environment at runtime; a missing credential
  makes the provider report `UNAVAILABLE` honestly — it never degrades silently.

---

## 4. Explicitly NOT needed (verified anonymous access)

No account, key, or payment is required for any of these — already working in the
repo:

| Source | Access | Verified |
|---|---|---|
| SEVIR replay events (GOES-16 ABI + GLM + NEXRAD VIL) | `s3://sevir`, anonymous | 2026-09-27 |
| NOAA GFS 0.25° GRIB2 | NOMADS, no registration | 2026-09-27 |
| ECMWF Open Data | free, CC-BY-4.0, no account | 2026-09-27 |
| IMD public radar GIF imagery | public web pages (visual reference only) | 2026-09-27 |
| Map basemaps | MapLibre + OSM/Carto free tiles, no API key | — |

Also **not needed by design**: LLM/API keys, paid weather APIs, commercial
lightning feeds (Earth Networks/Vaisala) — see `docs/research/11-do-not-build.md`.

---

## 5. Quick checklist

- [ ] MOSDAC account created (and privileged tier requested)
- [x] Earthdata account created (kunalrajdev) + GES DISC EULA accepted
- [ ] CDS account + API key copied
- [ ] IITM ILLN data-request email sent
- [ ] IMD API access email sent
- [ ] `.env` created from the template above (git-ignored)
- [ ] Credentials verified: run one MOSDAC archive pull + one IMERG/LIS download

Once §5's first three boxes are ticked, hand the `.env` to the development session —
wiring the provider adapters to consume them is a small config change, not a redesign.
