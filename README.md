# SIH 2026 — PS 26072: AIML-Based Nowcasting of Thunderstorm & Lightning

> Smart India Hackathon 2026 · Problem Statement ID **26072**
> **Organization:** Ministry of Earth Sciences (MoES) · **Department:** India Meteorological Department (IMD)
> **Category:** Software · **Theme:** Disaster Management
> **Working name:** Project Vajra (temporary)

**Project Vajra** fuses satellite imagery (INSAT), open NWP fields (GFS / ECMWF Open Data /
ERA5), and precipitation & lightning observations (IMERG, NASA ISS LIS, and Indian radar
imagery where available) into **calibrated probabilities of lightning in the next 30–60
minutes** at ~10 km grid / block scale, with tracked storm-cell motion — a warning product
India does not have today: IMD nowcasts are 3-hourly district-level text, and existing apps
(Damini, Sidilu) alert only *after* lightning is already detected nearby.

## Status

| | |
|---|---|
| **Phase 0 — Research & problem definition** | ✅ **Complete (2026-09-27).** Five research tracks, fetch-verified data-access findings, 12 deliverables in [docs/research/](docs/research/). |
| **Phase 1 — Data Foundation** | ⏭️ **Next.** Day-1 external actions: file MOSDAC privileged-access request (backlog B-1) and IITM lightning-data request (B-2). |
| **Implementation code** | None yet — by design. Stack and architecture are decided ([MASTER.md](MASTER.md) §6, §13). |

## What the research found (headline)

- **Closed to students today** `[VERIFIED]`: raw Indian radar data (paid IMD procurement only),
  Indian lightning flash feeds (IITM ILLN / NRSC / Earth Networks — all proprietary), IMD-GFS
  GRIB fields (login wall), bulk AWS data (no public API).
- **Open and usable** `[VERIFIED]`: the [SEVIR](https://registry.opendata.aws/sevir) benchmark
  (GOES-16 + GLM lightning + MRMS + HRRR, no registration) as our method sandbox; GFS 0.25°
  (NOMADS, zero registration); ECMWF Open Data (CC-BY-4.0); ERA5; IMERG; NASA ISS LIS flashes
  over India; IMD gridded rainfall; IMD radar *images*; MOSDAC INSAT archive via free signup
  (3-day latency — near-real-time requires privileged approval, criteria unpublished).
- **The gap** `[RESEARCH]`: no gridded, probabilistic, flash-verified 0–2 h lightning *forecast*
  exists in India. That is the defensible opportunity ([MASTER.md](MASTER.md) §7, §10).

## Repository map

| Path | Purpose |
| --- | --- |
| [MASTER.md](MASTER.md) | Single source of truth: verified facts, data-access status, decisions D1–D10, architecture, model strategy, MVP, risks. Every claim carries a status label (`[VERIFIED]` → `[UNKNOWN]`). |
| [docs/RESEARCH_BRIEF.md](docs/RESEARCH_BRIEF.md) | The full 45-part research brief that drove Phase 0. |
| [docs/research/](docs/research/) | **12 deliverables:** 01 executive report · 02 data-source matrix · 03 existing-systems matrix · 04 model decision matrix · 05 USP matrix · 06 MVP specification · 07 development plan · 08 experiment plan · 09 architecture (Mermaid) · 10 SIH demo plan · 11 do-not-build list · 12 research backlog. |
| `data/` (planned, Phase 1) | Datasets — `raw/`, `interim/`, `processed/`, `external/` are git-ignored (large files). |

## Working principles

1. **Science before stack.** No framework, dashboard, or model is chosen until the data-access reality is verified.
2. **Fact vs assumption.** Every important statement is labelled `[VERIFIED]`, `[RESEARCH]`, `[DECISION]`, `[PROPOSED]`, `[EXPERIMENTAL]`, `[BLOCKED]`, or `[UNKNOWN]`.
3. **Baselines before AI.** No claim of model superiority without persistence / climatology / optical-flow / tracking baselines.
4. **Honest demo.** Replayed or simulated data is always labelled as such — never presented as live government feeds.
