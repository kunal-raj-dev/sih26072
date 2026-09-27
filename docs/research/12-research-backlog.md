# Deliverable 12 — Research Backlog (Unresolved Questions)

Open items requiring verification or external action, with owners and next actions. This list feeds MASTER.md §14 and Phase 0 closeout.

## B. Access & institutional actions (time-sensitive)

| # | Item | Why it matters | Next action | Status |
|---|---|---|---|---|
| B-1 | MOSDAC **privileged** account criteria & approval | gates LIVE INSAT (NRT); general tier = T-3 days [VERIFIED] | Register + file purpose statement day 1; email MOSDAC support; record trail | OPEN |
| B-2 | IITM **ILLN flash data** research access | would upgrade India labels from satellite-only (weak) to ground-truth; unlocks E6 fully | Email IITM (lightning group / Damini team) with proposal; CROPC contact as alternate | OPEN |
| B-3 | **IMD public API** access (IP whitelist) | official nowcast/warning feed for comparison + alert interop | Identify API doc PDF; request via IMD data cell / RMC | OPEN |
| B-4 | NCMRWF **NCUM GRIB** registration + portal confirmation (rds/Maharshi) | India-native NWP fields beyond GFS | Register; email datahelp; verify portal URLs (site timed out during research) | PARTIAL — registered + API login verified live (2026-09-27, see REQUIRED_USER_INPUTS §1.4); remaining: confirm NCUM GRIB dataset availability/download paths |
| B-5 | **DWR GIF use terms** (attribution, scraping policy) | compliance for GIF→grid experiment | Written clarification from IMD; keep rate limits polite | OPEN |
| B-6 | IMDAA via CEDA/RDS — confirm **CAPE availability** + current end year | India reanalysis feature quality | Register CEDA; inspect variable list | OPEN |

## C. Scientific / technical verifications

| # | Item | Why | Action |
|---|---|---|---|
| C-1 | **ISS LIS detection efficiency & sampling over India** (label quality ceiling) | determines how much weight India-mode scores can claim | Literature review (Ghosh/Taori papers) + empirical: LIS vs SEVIR-GLM overlap study in sandbox |
| C-2 | INSAT **CTT/derived L2 products** enumeration behind MOSDAC catalog (JS shell) | CI feature richness | After B-1 approval: enumerate catalog programmatically |
| C-3 | **GIF→grid radar proxy** accuracy (georeferencing `caz_*.gif` frames) | optional radar feature from images only | Georeference pilot on 2 stations; measure vs IMERG cells |
| C-4 | **MOSDAC latency per product** for privileged tier | live-cycle planning | After B-1: timestamp probe over 48 h |
| C-5 | **Himawari-9 over-India fallback** quality vs INSAT (viewing-angle penalty at 68°E) | fallback robustness | Sample comparison on 3 convective days |
| C-6 | **ECMWF Open Data 9 km / 2-h latency** rollout (2026) | better NWP gating when live | Monitor announcement; adapt ingest config |
| C-7 | Earthformer **per-threshold CSI table** reproduction (paper values partially snippet-only) | harness correctness | E5 reproduction run |
| C-8 | Whether **time-to-first-flash** is viable with LIS sampling gaps | future target U6 | Sandbox study |

## D. Known unknowns accepted for now

- Exact IMD DWR network count/cadence drifts (Mission Mausam expansion, 37→73→126 figures conflict) [S] — re-verify before any radar-coverage claims in the deck.
- SACHET CAP end-to-end integration path for a student prototype [fetch failed].
- IAF/railway internal nowcasting practices (undocumented publicly) — treated out of scope.
- MOSDAC "restoration work in progress" services (observed 2026-09-27) — recheck before Phase 5.
