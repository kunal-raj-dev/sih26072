# MASTER.md — Project Source of Truth

**SIH 2026 · Problem Statement 26072 · MoES / IMD**
**AIML-based Nowcasting of Thunderstorm and Lightning using atmospheric observation (multiple radars, satellite, lightning, model data)**

This is the single source of truth for the project. Any agent or teammate should be
able to read this file and learn: WHAT we are building, WHY, HOW it works, WHAT
evidence supports it, and WHAT remains uncertain.

Rules:

1. Every load-bearing statement carries exactly one status label.
2. A label is upgraded only with a recorded source (URL + access date) or a recorded decision (§13).
3. This file is updated at every meaningful milestone — stale truth is worse than no truth.

## Label legend

| Label | Meaning |
| --- | --- |
| `[VERIFIED]` | Confirmed against an official / primary source; link + access date recorded. |
| `[RESEARCH]` | Supported by peer-reviewed literature or reputable institutions. |
| `[DECISION]` | Team decision, recorded in §13 with options and rationale. |
| `[PROPOSED]` | Candidate idea, not yet agreed or evidenced. |
| `[EXPERIMENTAL]` | Under active test; outcome pending. |
| `[BLOCKED]` | Cannot proceed: access, data, compute, or dependency missing. |
| `[UNKNOWN]` | Not yet investigated, or could not be verified. |

## 1. Problem Statement

`[VERIFIED]` (source: SIH 2026 problem statement, as provided by the team)

> "AIML based Nowcasting of thunderstorm and lightning using atmospheric observation including multiple radars, satellite, lightning and model data."

- Organization: Ministry of Earth Sciences (MoES)
- Department: India Meteorological Department (IMD)
- Category: Software · Theme: Disaster Management

## 2. Scientific Definition

`[UNKNOWN]` — prediction target, forecast horizons, spatial/temporal granularity,
and exact output definition to be derived from research brief Parts 1–3 before any model work.

## 3. Verified Facts

`[UNKNOWN]` — none recorded yet. First entries expected from data-access verification (brief Parts 4–5).

## 4. Data Sources

`[UNKNOWN]` — inventory under construction. Candidate categories to verify:
IMD Doppler Weather Radar network, INSAT/MOSDAC satellite products, lightning
detection networks, NWP model data (NCMRWF/IMD), surface observations (AWS).
**No source is assumed usable** until its access status is verified.

## 5. Data-Access Status

`[UNKNOWN]` — the honest per-source matrix (can a student team actually get it:
YES / NO / CONDITIONAL / UNKNOWN, plus license and latency) is Deliverable 2 and
must exist before any ingestion code is written.

## 6. Architecture

`[PROPOSED]` — final architecture is derived only after research (brief Parts 12, 14, 40).
Sketch pipeline: observation → ingestion → QC → alignment → features → model →
forecast → calibration → risk → alert → user. AI is used only where research shows
it beats deterministic methods; per-stage choices TBD.

## 7. Model Strategy

`[PROPOSED]` — the progression baseline → MVP → improved → advanced is a hypothesis
to validate against the literature (brief Parts 9–10, 13), not a commitment.
Classical baselines (persistence, optical flow, storm-cell tracking) are mandatory
before any AI-superiority claim.

## 8. Validation Standards

`[UNKNOWN]` — metric set (POD / FAR / CSI / HSS / FSS / Brier …), leakage-safe
train/val/test splits (temporal, spatial, seasonal), and per-output metric mapping
to be fixed (Deliverable 8) before model training.

## 9. UX / Product Definition

`[UNKNOWN]` — primary user, the exact decision the software improves, and the
smallest coherent product to be derived (brief Parts 20–22).

## 10. USP / Differentiation

`[UNKNOWN]` — no differentiator is claimed until the existing-systems analysis
(Indian + global, brief Parts 7–8, 23–24) demonstrates a real gap.

## 11. MVP

`[UNKNOWN]` — exact inputs, prediction target, baseline, model, output format, UI,
evaluation, and demo flow (brief Part 26). Must be achievable without pretending
to have unavailable data.

## 12. Development Phases

`[PROPOSED]` — dependency-aware phases to be derived from research (brief Part 31);
the suggested Phase 0–10 progression is a starting sketch, to be restructured if
the evidence demands it.

## 13. Decision Log

| # | Decision | Options considered | Evidence | Rationale | Trade-off | Date |
| - | -------- | ------------------ | -------- | --------- | --------- | ---- |
| D1 | Initialize repo docs-first; no tech stack chosen yet | (a) pick stack now, (b) research-first scaffold | Brief's operating mode: science → data → … → stack | Premature stack choice is the exact failure mode the brief warns against | Slower visible progress | 2026-09-27 |

## 14. Unresolved Questions

- Which data sources can the team actually access, at what latency, under what license? `[UNKNOWN]`
- Is real-time radar access obtainable at all for a student team? `[UNKNOWN]`
- What is the right first prediction target given obtainable data? `[UNKNOWN]`
- What do IMD's existing warning products already cover, so we don't rebuild them? `[UNKNOWN]`

## 15. Known Limitations

- No verified real-time government data access at this time. `[UNKNOWN]`
- No implementation code, data, or model exists yet.

## 16. Risks

| Risk | Likelihood | Impact | Early warning | Mitigation | Fallback |
| ---- | ---------- | ------ | ------------- | ---------- | -------- |
| Core data sources inaccessible to a student team | High | Critical | Parts 4–5 verification fails | Verify access FIRST, before any code | Historical replay / open research datasets |
| (full register to be built — brief Part 37) | | | | | |

## 17. Current Implementation State

- **2026-09-27** — Repository initialized. Contents: `README.md`, this file,
  research brief archived at `docs/RESEARCH_BRIEF.md`, `.gitignore`.
  No code, no data, no model. Phase 0 (research & data-access verification) not started.
