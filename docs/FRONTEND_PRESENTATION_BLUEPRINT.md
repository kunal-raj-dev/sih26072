# Vajra — Presentation Experience Blueprint (target UX for the SIH demo)

**Status:** DESIGN DIRECTION — no code written. Derived from `FRONTEND_UX_AUDIT.md`
(verified defects + data surface) and `FRONTEND_PRESENTATION_RESEARCH.md` (principles).
Numbers in the wireframes are 1920×1080; a 1366×768 variant keeps every L1 element.

**The narrative this UI must make self-evident:**

> OPEN → ORIENT → OBSERVE → DETECT → PREDICT → TRACK → WARN → EXPLAIN → VERIFY

("What's happening → what Vajra sees → what Vajra predicts → where it goes → who is warned
→ why → was it right.") Every element below serves exactly one step of that chain.

---

## 1. Target information architecture

```
SYSTEM (Vajra console, one screen)
└── EVENT (preloaded canonical case study; selectable)
    └── RUN (auto-executed replay; rung + model provenance visible)
        └── CYCLE (timeline position; observed vs forecast segment)
            ├── OBSERVATIONS   obs field, flashes (past window)          [map]
            ├── DETECTIONS     cells, tracks, CI precursors               [map]
            ├── FORECAST       probability field +30/+60, cones           [map]
            ├── THREAT         hero card: what/where/when/conf/why/action [right rail]
            ├── ALERT          IMD stage strip, blocks, population, CAP   [right rail]
            ├── EVIDENCE       why-this-forecast line; data-quality chips [bottom strip]
            └── VERIFICATION   settled verdicts + benchmark numbers       [bottom strip]
```

Level assignment (from research principle 8):
- **L1 (always visible):** map (storm-zoomed), timeline, threat hero, alert strip,
  verification hero numbers, mode/rung badges, clocks.
- **L2 (one click):** why-this-forecast detail, event synoptic narrative, reliability
  diagram, full scoreboard, system status (model/workers/NWP), CAP XML.
- **L3 (expert drawer):** 15 individual layer checkboxes, opacity/opacity-split sliders,
  station selectors, NPZ/GeoJSON links, raw contributing signals table.

---

## 2. Target primary screen (1920×1080)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ⚡ VAJRA · Thunderstorm & Lightning Nowcast        [🔬 IMD] [🛡 DDMA]         │
│ Predicts lightning 30–60 min ahead   REPLAY · Bihar Squall 2026  15:20Z 20:50IST│
│                                                       RUNG: FULL MODEL ▾     │
├───────────────────────────────────────────────────┬──────────────────────────┤
│                                                   │ ① CURRENT THREAT         │
│                                                   │ ⚡ Lightning · P=64%      │
│                 MAP  (fit to EVENT bbox)          │   within +60 min         │
│                                                   │ 📍 Cell C0002 → Gaya     │
│   NOWCAST view (default preset):                  │   dist. — 3 blocks       │
│   · probability field (risk palette)              │ 🕑 Window 15:20→16:20Z   │
│   · detected cells + tracks + cones               │ 📶 Conf 65% · Data:      │
│   · observed flashes (past window)                │   radar● sat● lgt● nwp○  │
│   · CI precursor rings (cyan)                     │ ▸ WHY THIS FORECAST      │
│   · admin outlines (ghost)                        │ [🎯 Show on map]         │
│                                                   ├──────────────────────────┤
│   contextual legend (only visible layers)         │ ② ALERT                  │
│                                                   │ 🟠 IMD ORANGE — BE       │
│                                                   │   PREPARED               │
│                                                   │ Blocks: … · 👥 284,000   │
│                                                   │ [📄 Bulletin][📡 CAP ▾]  │
│                                                   ├──────────────────────────┤
│                                                   │ ③ EVENT ▾ (collapsed)    │
│                                                   │ 2-line synoptic narrative│
├───────────────────────────────────────────────────┴──────────────────────────┤
│ OBSERVED ━━━━━━━━━━━●NOW●┄┄┄┄┄+30┄┄┄┄┄┄+60  FORECAST      ▲ORANGE   ✓VERIFIED│
│ [⏮][◀][▶/❚❚][⏭][🔁]  [ OBSERVE | NOWCAST | COMPARE ]      (click axis to jump)│
├──────────────────────────────────────────────────────────────────────────────┤
│ EVIDENCE  VIL 56 dBZ · ΔTb −12 K/15 min · 2 flashes already · cell 48 km/h    │
│ VERIFY    This event: POD .52 FAR .08 · Benchmark (SEVIR held-out): BSS +.50  │
│           [ Full audit ▾ ]   [ System status ▾ ]   [ Expert layers ▾ ]        │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Minimums for 1366×768:** right rail 340 px (stacks threat+alert); bottom strip collapses
to two lines; map keeps ≥ 62 % width. All L1 elements survive.

---

## 3. Demo zero state (what the judge sees before the presenter touches anything)

| Aspect | Value |
|---|---|
| Event | `bihar_squall_2026` (canonical narrative) auto-run at boot; second benchmark event `sevir_s810646` pre-warmed in background |
| Cycle | **peak-threat cycle** of the run (argmax p_flash_max) — never an empty tail cycle |
| Camera | fit to event cells/flashes bbox + 60 px padding (never the whole India grid) |
| Layers | NOWCAST preset (prob field + cells + tracks/cones + flashes + CI + ghost admin) |
| Right rail | Threat hero populated from top active alert; alert strip shows IMD stage; EVENT collapsed |
| Badges | `REPLAY` (or `SIMULATION` — labelled), rung in plain words, clocks running |
| Bottom | evidence line populated; verification numbers appear once run settles |

Boot sequence: server up → seed → auto-run canonical event → jump to peak cycle → fit
camera → render. Target ≤ 8 s cold; the presenter's first words happen over a working scene.

---

## 4. Map experience (primary story)

**Zoom:** camera = event bbox, not domain grid. `fitToGrid` is replaced by
`fitToEvent(cells ∪ flashes ∪ alert bboxes)`.

**Layer hierarchy (replaces 15 checkboxes):**
- **OBSERVE preset:** obs field (enhanced, labelled "VIL / IR — observed"), past-window
  flashes, cell outlines (no fill), admin ghost. Answers: "what happened".
- **NOWCAST preset (default):** probability field (primary), cells + tracks + cones, CI
  rings, flashes window, admin ghost. Answers: "what Vajra expects".
- **COMPARE preset:** fixed split — observed left / probability right (or slider), with
  caption "OBSERVED vs NOWCAST". Answers: "how do we know". Fixes the slider-vs-opacity
  conflict by making compare an exclusive mode.
- **Expert drawer (L3):** uncertainty field, radar mosaic, radar rings/stations, IMD live
  GIF, opacity controls, raw GeoJSON/NPZ links.

**Visual encoding (per research principle 11):**
- Probability field: sequential YlOrRd-family ramp at ≥ 0.2 with smooth alpha; bands
  labelled in the contextual legend; **never** reuses IMD traffic colours verbatim — IMD
  colours are reserved for the alert strip.
- Cells: white/dark outline + name; cones: dashed boundary, alpha fill, visibly widening
  with lead, captioned ("expected storm-centre envelope, 60 min").
- CI: cyan dashed rings, distinct hue.
- Flashes: white points, blue stroke; *forecast* flashes (after settlement, for
  verification view) ghosted/diamond vs observed circles.
- Zone labels: storm-cell id + P(flash) label rendered on map at ≥ zoom 7 (canvas or
  symbol layer), so the map reads without the rail.

**Map ↔ rail linkage:** hovering an alert card highlights its cells (pulse once) and
offers flyTo; clicking a cell opens the threat card detail. No layer is ever shown without
a legend entry; legend shows only active layers.

---

## 5. Timeline (the narrative instrument)

- **Axis = replay time.** Observed segment solid; from T0 (issue) dashed/tinted; +30/+60
  ticks; NOW playhead labelled with the dual clock.
- **Markers:** alert-issue ▲ (coloured by IMD stage, stacked if multiple), expected-impact
  ⚑, verification ✓/✗ at settlement, peak-threat flag.
- **Behaviour:** click-to-jump anywhere; play/pause/step/speed/loop retained; keyboard
  1–8 (demo rail), Space, ←/→, Home (start), End (peak, **not** last cycle).
- **The old horizon tags die:** their legitimate semantics (past/now/future) become the
  axis segments; lead-time selection stays as +30/+60 in the timeline controls.
- **Landing logic:** run load → peak cycle; "T0" button → first alert-issue cycle (or
  peak if none); never lands on p = 0 tail cycles.

---

## 6. Threat summary hero (the missing anchor)

One card answers WHAT/WHERE/WHEN/CONFIDENT/WHY/ACTION (research §5.1, §2.2):

- **WHAT:** "⚡ Lightning" or "⛈ Thunderstorm" (hazard).
- **HOW LIKELY:** "P = 64 % of ≥1 flash within 60 min in this block" (reference class,
  one format everywhere).
- **WHERE:** region from alert geocoding ("Cell C0002 → Gaya dist., blocks: …"); honest
  "Cell bbox (block resolution pending)" fallback — never fake blocks, never "all clear"
  during a storm.
- **WHEN:** valid window (from `valid_from/until`).
- **TREND:** Δp vs previous cycle with an up/down glyph (data: adjacent steps).
- **CONFIDENCE:** % + rung in plain words (FULL MODEL / REDUCED DATA / PHYSICS ONLY) with
  a one-line tooltip; **data-quality chips** radar●sat●lgt●nwp from alert.data_quality.
- **WHY (disclosure):** evidence line humanized from contributing_signals
  ("intensity 110 · 2 flashes already · nearly stationary") with raw values at L3.
- **ACTION:** recommended_action text; **[🎯 Show on map]** flyTo + pulse.

---

## 7. Alert experience

- **IMD stage strip** with action words ("ORANGE — BE PREPARED") — the only place traffic
  colours live. Alert cards: severity/hazard, region, lead, P, blocks+population (when
  geocoding yields them), CAP actions. Max 2 cards visible; older ones collapse into a
  count ("+3 earlier").
- **Chime** fires only on stage escalation; suppression state narrated ("45-min
  suppression active").
- **CAP 1.2** XML/JSON copy + download + Atom feed kept one click away (L2).
- **Bulletin** modal unchanged (it's already strong) but gains the honest blocks fallback.

## 8. Confidence / uncertainty experience

Three channels, always visible, never merged (research §3.4):
1. **Hazard:** probability field + P readouts.
2. **Confidence:** % + rung chip + one-line explanation ("calibrated on held-out events;
   reliability monotone" when true).
3. **Data quality:** per-modality chips (OK/SUSPECT/MISSING) — from alert data_quality;
   UNAVAILABLE live providers move to System status popover (L2).
Uncertainty field stays L3, drawn as outline/hatch tint (never hazard-coloured), captioned.

## 9. Verification experience

- **Per-alert settled verdict:** when the outcome window elapses, the alert card shows
  "✓ VERIFIED — 3 flashes in window" or "✗ NOT CONFIRMED — predicted 64 %". Data:
  `/events/{id}/flashes.geojson` filtered to (valid_from, valid_until] ∩ bbox. This is the
  single most persuasive judge moment and needs no backend change.
- **COMPARE preset** gives the visual forecast-vs-actual.
- **Bottom VERIFY strip:** 4 hero numbers from the **mode-gated** scoreboard (held-out
  SEVIR benchmark: BSS +0.50, FAR 0.08, POD 0.52, CSI 0.50) + "Full audit ▾". On
  SIMULATION runs the strip states "skill benchmark: held-out SEVIR event" and the
  scoreboard never renders fallback numbers (audit §3.4 removed).

## 10. Data / model health experience

L1: nothing (chips on threat card carry event context). L2 **System status popover:**
model (version, provenance, rung usage), workers (ingestion status), NWP indices, provider
table — sourced from existing `/model-health`, `/workers/status`, `/nwp/gfs/indices`,
`/data-health`. The red wall moves off the first screen; diagnostics stay reachable.

## 11. Presentation mode analysis — one unified console + a thin demo rail

Two products are rejected (audit + research principle 7/8). The justified mechanism is a
**demo rail**: a dismissible bottom-left chip row — ①ORIENT ②OBSERVE ③DETECT ④PREDICT
⑤TRACK ⑥WARN ⑦EXPLAIN ⑧VERIFY — where each chip sets **real UI state** (event, cycle,
camera, preset, panel focus). Keyboard 1–8; `R` reset to zero state. It is a sequencer
over the operational console — no fake slideshow, no duplicated UI, and every step is
exactly what an operator could do manually. Operational mode = the same console with the
rail dismissed.

## 12. Judge moments (from real V2 capabilities)

| # | Moment | Judge sees | Behind it | Interactions | Time |
|---|---|---|---|---|---|
| 1 | **Zero-state strike** | Populated, storm-zoomed, mid-event scene with threat card | boot autorun + peak landing + event fit | 0 | 0:00 |
| 2 | **Detection** | Cells + tracks with velocity/dBZ popup | cells.geojson + Kalman tracker | click cell | 0:40 |
| 3 | **Prediction** | Probability field fades in at +60, cones widen | field.png + preset | preset auto | 1:10 |
| 4 | **CI precursor** | Cyan rings with P(initiation) + lead-to-first-flash | ci.geojson | click ring | 1:40 |
| 5 | **Impact targeting** | ORANGE strip, named blocks + population, bulletin, CAP XML | alerts + geocoding + CAP | 2 clicks | 2:10 |
| 6 | **Graceful degradation** | Rung narrated downshift, data chips go SUSPECT, availability holds | fallback ladder + himalayan event | 1 click | 2:40 |
| 7 | **Verification** | Settled ✓ verdict + COMPARE + BSS +0.50 vs negative baselines | settlement + scoreboard | 2 clicks | 3:10 |
| 8 | **Depth on demand** | Why-panel, model/workers status, CAP raw | L2/L3 popovers | 1 click | 3:40+ |

## 13. 3–5 minute demo script (rehearsal-ready)

| Time | Screen state | Presenter action | Judge learns | Failure → recovery |
|---|---|---|---|---|
| 0:00–0:30 | Zero state (moment 1) | Speak: gap (2,500 deaths/yr; 3-hourly district bulletins; Damini = detection) | the problem + "this is live intelligence" | if boot slow: speak over Event strip |
| 0:30–1:10 | OBSERVE→DETECT | Click cell (moment 2): velocity, dBZ, flash history | multi-sensor detection | popup miss → point at rail card |
| 1:10–1:45 | NOWCAST (moment 3) | Field on; scrub +30→+60; cones widen | calibrated prediction before strikes | field chip → narrate from threat card |
| 1:45–2:10 | CI (moment 4) | Click cyan ring | warning before radar echo | skip cleanly |
| 2:10–2:40 | WARN (moment 5) | Alert strip → bulletin modal → CAP feed | block-level, standards-based action | geocoding empty → bbox region text (honest) |
| 2:40–3:10 | DEGRADE (moment 6) | Himalaya event; rung narrated | satellite-primary resilience | rung unchanged → explain ladder exists |
| 3:10–3:50 | VERIFY (moment 7) | Settled verdict + COMPARE + scoreboard 4 numbers | forecast checked against reality | scoreboard slow → bottom strip numbers |
| 3:50–4:00 | Rest state | "Everything shown is the real system — replay labelled, nothing faked." | honesty close | — |

## 14. Judge question mode (progressive disclosure answers)

- *"How did it predict this?"* → WHY disclosure (signals, features, model version, rung).
- *"What data?"* → System status popover (providers, freshness, workers) + event provenance.
- *"How confident?"* → confidence readout + reliability note + reliability diagram (L2).
- *"How do you know it works?"* → VERIFY strip + full audit modal (mode-gated).
- *"What if radar fails?"* → moment 6 replay + rung explanation popover.
- *"What happened historically?"* → event selector + synoptic narrative.
- *"Show the raw output."* → CAP XML / NPZ / GeoJSON links (L3).

## 15. Design-system direction

- **Type scale (1080p):** hero numbers 28–32 px semibold; section titles 14 px caps;
  body 16 px; secondary 13 px; floor = 12 px (only for attribution). Tabular numerals for
  all times/metrics. One family (system UI stack is fine).
- **Spacing:** 4/8 px grid; panels 16 px padding; consistent 8 px radii; one border colour.
- **Status colours:** success `#22c55e` / degraded `#f59e0b` / unavailable `#f87171` — but
  traffic yellows/oranges/reds **only** in the alert strip; probability uses its own ramp;
  CI cyan; uncertainty neutral hatch.
- **Contrast:** AA on dark theme; verify legend swatches against `--bg`.
- **Print/bulletin:** unchanged (already compliant).

## 16. Motion direction

Only: timeline playback (phenomenon), fade of field on cycle change (≤150 ms), single
pulse on new/escalated alert, flyTo camera moves. No ambient animation, no particles, no
decorative transitions. `prefers-reduced-motion` honoured.

## 17. Accessibility direction

Focus-visible states on all controls; aria-labels retained (already present); alert strip
announced via `aria-live=polite`; colour never the sole encoding (dash/shape redundancy);
keyboard-first demo rail; contrast per §15.

## 18. Performance direction

Keep vanilla stack (no framework migration before the demo). Preload both demo runs at
boot; cache forecast details (already cached); avoid re-fetching flashes (cached once);
image overlays updated via `updateImage` only when cycle/lead changes; total render budget
≤ 50 ms per cycle (measured cycle latency is ~100 ms server-side — the budget is the UI's).
Basemap fallback: vendor offline tiles or graceful "basemap unavailable" chip so the map
frame never blocks the demo.

---

# VAJRA PRESENTATION EXPERIENCE — FINAL DIRECTION

## 1. The current UI problem
The system is powerful but the console tells no story: the probability field is effectively
invisible (domain-fit camera + empty-cycle landings), the Alert Center is permanently empty
due to a time-base bug, block targeting silently returns nothing, the scoreboard fabricates
a fallback ROC value, and the first screen leads with five red UNAVAILABLE rows. The three
demo-critical moments — prediction, warning, verification — are the three most broken
surfaces.

## 2. What the judge must understand
(1) Vajra predicts lightning 30–60 min ahead at ~10 km/block scale; (2) it fuses radar +
satellite + lightning + NWP; (3) output is *calibrated probability*, honestly labelled;
(4) warnings are block-level, IMD-coded, CAP 1.2 machine-readable; (5) forecasts are
verified against actual flashes; (6) it degrades gracefully when sensors fail.

## 3. What should be visible immediately
Map fit to the storm at the peak-threat cycle; probability field; cells + tracks + cones;
threat hero (what/where/when/confidence/action); IMD alert strip; timeline with
observed|forecast segmentation; verification hero numbers; mode + rung badges.

## 4. What should be hidden until needed
15 layer checkboxes (expert drawer); opacity/split sliders (COMPARE mode instead);
provider diagnostics (System status popover); raw signal dumps (WHY disclosure); CAP
raw XML; NPZ/GeoJSON; reliability table; workers/NWP status.

## 5. Ideal primary screen
§2 wireframe: header story-line + badges; map (event-fit) + right rail (threat hero,
alert, event narrative); narrative timeline; evidence + verification strip. All L1,
zero hunting.

## 6. Ideal map experience
Event-fit camera; three presets OBSERVE/NOWCAST/COMPARE; expert layers drawer; separate
palettes per semantic domain; on-map cell probability labels; alert↔map linkage.

## 7. Ideal forecast experience
Probability field is the hero layer; +30/+60 as timeline ticks; cones widen with lead and
carry their caption; landing always on the peak cycle; reference-class wording everywhere.

## 8. Ideal alert experience
IMD stage strip with action words; ≤2 cards + collapse count; blocks + population when
geocoding delivers, honest fallback otherwise; chime on escalation only; CAP one click away.

## 9. Ideal verification experience
Per-alert settled ✓/✗ with flash counts; COMPARE visual; mode-gated benchmark numbers
(BSS +0.50, FAR 0.08, POD 0.52, CSI 0.50) with full audit behind a click; no fabricated
values ever.

## 10. Ideal 3–5 minute demo
§13 script: zero-state → detect → predict → CI → warn → degrade → verify → close; 8 judge
moments; every step has a named failure recovery; presenter never runs a replay live.

## 11. What should be removed
Horizon-tag chips (folded into the timeline axis); the standalone "Run nowcast replay"
button from the stage path (auto-run + preload); the red provider wall from L1; the
`roc_auc || 0.86` fallback; hardcoded verdict badges on meaningless runs.

## 12. What should be simplified
Layer panel → 3 presets + drawer; alert signal dump → evidence line; verification table →
bottom strip; event/run controls → compact strip; legend → contextual.

## 13. What should be restructured
Right rail becomes threat-first (threat/alert/event); timeline becomes the narrative
instrument; data health becomes event-context chips + System status popover; verification
moves from a hidden modal to an L1 strip; personas keep their specialties but share
verification.

## 14. What should be added
Threat hero card; demo rail (8-step sequencer); settled per-alert verdicts; event
narrative; System status popover; on-map probability labels; honest empty/fallback states;
offline basemap fallback; reset-view control.

## 15. Implementation phases
P0 Demo-critical fixes → P1 Timeline narrative → P2 Threat hero + linkage → P3 Map
presets/hierarchy → P4 Design system/legibility → P5 Verification moment → P6 DDMA
completion → P7 Demo rail + rehearsal hardening → P8 A11y/perf/polish → P9 Readiness.
(Full task breakdown: `FRONTEND_IMPLEMENTATION_PLAN.md`.)

## 16. Critical path
P0 (alert window fix, geocoding data fix, scoreboard honesty, zero-state) feeds everything:
P1→P2→P5→P7 are the spine; P3/P4 run parallel; P8/P9 close.

## 17. Risks
Geocoding fix may expose synthetic cells outside block coverage (mitigate: align case-study
cell placement with block coverage — they are SIMULATION anyway); trained-model rung may
still downshift on synthetic events (mitigate: narrate the ladder — it is a feature);
offline venue basemap (mitigate: fallback style); chime autoplay policies (gate on user
gesture); scope creep into a redesign (mitigate: P0–P5 only touch existing components).

## 18. Final acceptance criteria
A cold-start judge sees, within 30 s and without interaction: a storm-zoomed map with a
visible probability field, a populated threat card, a correctly-staged alert, and honest
badges; within 4 minutes the presenter hits all 8 judge moments with ≤ 12 clicks; every
number on screen is real or explicitly labelled; zero console errors at 1366×768 and
1920×1080; all four audit P0 defects fixed and regression-tested.
