# SIH 2026 — PS 26072: AIML-Based Nowcasting of Thunderstorm & Lightning

> Smart India Hackathon 2026 · Problem Statement ID **26072**
> **Organization:** Ministry of Earth Sciences (MoES) · **Department:** India Meteorological Department (IMD)
> **Category:** Software · **Theme:** Disaster Management

Short-fuse (nowcasting-scale) prediction of thunderstorm and lightning hazard by
fusing multiple atmospheric observations — radar, satellite, lightning, and NWP
model data — into warnings a decision-maker can act on.

## Status

**Phase 0 — Research & problem definition.** No implementation code exists yet.
Nothing about data access, models, or architecture is assumed; every unverified
item is labelled `[UNKNOWN]` in [MASTER.md](MASTER.md).

## Repository map

| Path | Purpose |
| --- | --- |
| [MASTER.md](MASTER.md) | Single source of truth: facts, data access, decisions, architecture, MVP, risks. Every claim carries a status label. |
| [docs/RESEARCH_BRIEF.md](docs/RESEARCH_BRIEF.md) | The full 45-part research brief driving Phase 0 (problem → science → data → existing systems → gap → solution). |
| `docs/` | Research deliverables, architecture documents, decision records (populated as research lands). |
| `data/` (planned) | Datasets — `raw/`, `interim/`, `processed/`, `external/` are git-ignored (large files). |

## Working principles

1. **Science before stack.** No framework, dashboard, or model is chosen until the data-access reality is verified.
2. **Fact vs assumption.** Every important statement is labelled `[VERIFIED]`, `[RESEARCH]`, `[DECISION]`, `[PROPOSED]`, `[EXPERIMENTAL]`, `[BLOCKED]`, or `[UNKNOWN]`.
3. **Baselines before AI.** No claim of model superiority without persistence / optical-flow / tracking baselines.
4. **Honest demo.** Replayed or simulated data is always labelled as such — never presented as live government feeds.
