# Deliverable 10 — SIH Demo Plan

A 4-minute demonstration that proves technical claims instead of asserting them. Every screen carries a data-mode badge: **LIVE / REPLAY / SIMULATION**.

## Demo flow (4:00)

| t | Beat | What judges see | Claim it proves |
|---|---|---|---|
| 0:00–0:20 | The stakes | India lightning mortality map (CROPC figures), one documented case; the victims' profile (rural, outdoor) | problem is real and specific |
| 0:20–0:50 | What exists today | IMD district nowcast (text, 3-hourly) vs Damini (alerts after detection) — side-by-side | the gap: no pre-flash, block-scale forecast |
| 0:50–1:20 | Observations | Replay of a severe case (SEVIR sandbox; India replay if ready): satellite channels animating, IMERG cells, flashes appearing | multi-observation fusion is real, not mocked |
| 1:20–2:00 | The nowcast | Cells detected + tracked; 30/60-min flash-probability grid renders; motion vectors; probability bands | the PS's core ask, working |
| 2:00–2:30 | Trust layer | Confidence spread, reliability diagram, data-health strip; toggle: kill the satellite feed → system visibly degrades a rung and says so | uncertainty + graceful degradation (U3, U5) |
| 2:30–3:10 | Decision support | Block rollup: "Blocks X, Y — P(flash ≤60 min) = 0.7 — cell from NW — confidence 0.8"; CAP-style JSON alert preview; Protective vs Operational preset toggle with its POD/FAR shown | the exact decision supported (Part 20) |
| 3:10–3:40 | Explainability | "Why" panel: top features (cell growth, cloud-top cooling rate, CAPE gate) | not a black box |
| 3:40–4:00 | The scoreboard | Head-to-head: our model vs persistence vs climatology vs PySTEPS on held-out events (BSS/CSI/lead-time curves); India-mode scores shown with EXPERIMENTAL badge + label caveats | scientific honesty; baseline-beaten claim |

## What judges learn

1. We decoded the PS into a specific, defensible target (flash probability) rather than a generic weather map.
2. We know exactly what data students can and cannot access — and designed for that reality with a fallback ladder.
3. Our ML sits on the one fusion pattern with operational pedigree (ProbSevere/LightningCast), not on hype.
4. Verification is a product feature, not an afterthought.

## Technical claims we can prove live

- End-to-end pipeline reproducibility (`docker compose up` on the demo laptop).
- Baseline-relative skill on held-out events (stored, re-runnable).
- Graceful degradation under feed failure (live toggle).
- Latency budget: ≤10 min software-added latency per cycle.
- Every displayed number traces to an archived forecast with config hash.

## Presentation narrative (Part 36)

Problem (1,300 deaths/yr, rural) → current limitation (3-hourly district text; detection-only apps) → data reality (verified open sources; INSAT+NWP core) → intelligence (calibrated fusion, physics baselines) → innovation (India's open flash-verified nowcast prototype + honesty layer) → output (block-scale probability + CAP-style alert) → impact (decision lead time for those who can act) → validation (scoreboard vs baselines, leakage-safe splits) → scalability (0.1° grid → national; privileged INSAT + ILLN access as the institutional path).

## Contingencies

- Internet dies at venue → full replay mode from local store (designed-in).
- Demo laptop dies → 3-min recorded video fallback (Phase 8 deliverable).
- Judge asks "is this real-time IMD data?" → answer prepared: "No — open-mode data plus archived Indian data; we filed for privileged INSAT and IITM lightning access; here is the request trail." Honesty is the differentiator, not a weakness.
