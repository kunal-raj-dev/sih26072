# Deliverable 5 — USP Matrix

Only evidence-backed differentiators retained. Each answers: existing gap → evidence → our response → implementation → difficulty → validation → demo value → long-term value.

## Core differentiator

### U1 — India's first open, flash-verified, probabilistic lightning-nowcast prototype (the "Indian ProbSevere/LightningCast slot")
- **Existing gap:** no published Indian system fuses radar/satellite/lightning/NWP into per-storm or gridded flash probabilities; IMD nowcast is 3-hourly district text; Damini alerts only after detection.
- **Evidence:** systematic search found no Indian analogue [RESEARCH]; ProbSevere (2017→) and LightningCast prove the pattern operationally abroad [S]; IITM fusion research (LPI, GAN studies) never reached operations [S].
- **Our response:** calibrated P(flash ≤ 60 min) grid + cell layer, verified against open flash data.
- **Implementation:** XGBoost late fusion + U-Net, calibration layer, SEVIR→India transfer.
- **Difficulty:** Medium. **Validation:** BSS vs climatology, reliability diagrams, lead-time curves. **Demo value:** High. **Long-term value:** High (direct IMD operational path).

## Secondary differentiators

### U2 — Satellite-primary robustness for radar-poor regions (Himalaya / NE India)
- **Gap:** ~39–47 DWRs with Himalaya/NE blind spots; DL nowcasters trained on dense US/EU mosaics transfer poorly [S]; satellite-proxy nowcasting is an emerging India-specific workaround (SII-NowNet, FORTECC) [S].
- **Response:** architecture treats satellite+NWP as primary, radar as enhancing modality; degradation ladder keeps the product alive when radar drops.
- **Implementation:** LightningCast-style satellite model + NWP gating. **Difficulty:** Medium. **Validation:** per-region skill breakdown (radar-rich vs radar-poor blocks). **Demo value:** Medium-High (show skill with radar OFF). **Long-term:** High — aligns with Mission Mausam priorities.

### U3 — Uncertainty-aware, calibrated decision support at block scale
- **Gap:** warnings are binary color codes; no reliability information reaches the decision layer [V for IMD products].
- **Response:** calibrated probabilities + confidence bands + input-health flags + user-tunable threshold presets (Protective/Operational), each preset's POD/FAR shown.
- **Implementation:** isotonic/Platt calibration; preset metadata from our own verification. **Difficulty:** Low-Medium. **Validation:** reliability diagrams per preset. **Demo value:** High (judges see the tradeoff dial). **Long-term:** High.

### U4 — Built-in verification & lead-time honesty ("we show our own scoreboard")
- **Gap:** no public flash-verified nowcast evaluation in India; NOVA (IMD's validation platform) only emerging [S].
- **Response:** every forecast archived and scored automatically (BSS/CSI/FSS/lead-time); dashboard shows live skill including when we *lose* to climatology.
- **Implementation:** forecast store + verification job + dashboard. **Difficulty:** Medium. **Validation:** is the scoreboard itself. **Demo value:** High (differentiates from every fake-accuracy hackathon demo). **Long-term:** High (trust-building with IMD).

### U5 — Graceful degradation ladder
- **Gap:** single-source systems fail visibly (Damini-style outages; DataPoint retirement shows even agencies lose feeds) [V].
- **Response:** MULTIMODAL → reduced-modality ML → physics/tracking baseline → persistence → climatology, with the active rung displayed on the map.
- **Implementation:** modality-health router choosing model per rung. **Difficulty:** Medium. **Validation:** fault-injection tests in replay mode. **Demo value:** High (kill a feed live on stage). **Long-term:** Medium-High.

## Future differentiators (post-MVP)

- **U6 Time-to-first-flash regression** target (best matches the warning decision; no Indian study uses it [S/U]).
- **U7 Last-mile actionability:** vernacular, low-bandwidth, SMS/CAP-ready outputs for the documented excluded users (96 % rural deaths; app exclusion verified) [V].
- **U8 Human-in-the-loop feedback:** forecaster override logging to build an Indian warning-decision dataset.

## Rejected USP claims (evidence)

- "AI-powered / real-time / modern dashboard / cloud-based" — not differentiators; every competitor and hackathon team claims them.
- "Unique multimodal fusion" — **false**: ProbSevere/MetNet/WoFS fuse these modalities abroad [S]; our claim is the *Indian, open, verified* instantiation (U1), not novelty of fusion.
- "Most accurate lightning prediction in India" — unverifiable without IMD internal data; violates Claims policy (Deliverable 11).
- "Proprietary sensor network" — we have none; ENTLN/Vaisala own that moat.
