# Vajra — Frontend / Presentation UX Audit (V2, pre-demo)

**Scope:** the presentation-facing console (`web/`), its API consumption, and the live demo
experience as a judge would see it. Produced 2026-09-27 from a full code read of
`web/index.html` (241 L), `web/app.js` (1,415 L), `web/style.css` (320 L), the API surface
(`src/vajra/api/app.py`, 41 routes), and a **live walkthrough at 1920×1080 and 1366×768**
with replay runs of `multicell_electrification_2026`, `bihar_squall_2026`, and
`sevir_s810646`. Every defect below was **verified against the running system**, not inferred
from docs. Companion docs: `FRONTEND_PRESENTATION_RESEARCH.md`,
`FRONTEND_PRESENTATION_BLUEPRINT.md`, `FRONTEND_IMPLEMENTATION_PLAN.md`.

---

## 1. Current frontend x-ray

**Stack:** vanilla ES6 + vendored MapLibre GL 3.x (`web/vendor/`), no build step, no
framework, no router. Single page, two side panels, one map, two modals, one toast.
Served statically by FastAPI at `/`.

**State model (app.js `state`):** events, eventId, runId, forecasts[], index, lead (30/60),
playing/timer/speed/loop, flashes FeatureCollection, gridBounds cache, activeAlerts,
runVerification, persona. Everything else is DOM-queried on demand.

**Data flow:** boot → `GET /events` → auto-run first SIMULATION event → `GET /runs/{id}/forecasts`
→ renderStep() per cycle → per render: `/forecasts/{id}` (grid), `/forecasts/{id}/cells.geojson`,
`/forecasts/{id}/ci.geojson`, `/forecasts/{id}/obs.png`, `field.png?lead=`, `/alerts?run_id=`,
plus periodic `GET /data-health` (60 s). Scoreboard modal → `/runs/{id}/scoreboard`.

**API routes: 41 total; 24 consumed.** Consumed-but-valuable set is fine. **Unused by the UI**
(all verified present in `app.py`): `/events/{id}` (synoptic narrative + provenance!),
`/model-health`, `/workers/status`, `/workers/poll`, `/nwp/gfs/indices`, `/nwp/gfs/status`,
`/satellite/mosdac/status`, `/satellite/ci/latest`, `/satellite/lis/latest`, `/radar/stations`,
`/radar/mosaic/latest`, `/alerts/{id}` detail, `/alerts/{id}.cap`, `/forecasts/{fid}/field.npz`.

**What is genuinely good (protect these):**
- Zero console errors/warnings at both test resolutions; playback, layer toggles, popups,
  persona switch, bulletin modal, scoreboard modal all function.
- Honesty plumbing is real: mode badge (LIVE/REPLAY/SIMULATION), fallback-rung badge,
  confidence badge, footer honesty note, per-alert `mode`/`model_version`/`confidence`.
- Keyboard shortcuts (Space, ←/→, Home, End, Esc) exist.
- CAP 1.2 XML/JSON copy/download + Atom feed + printable bilingual bulletin — a genuinely
  strong institutional story.
- Per-modality `data_quality` (OK/SUSPECT/MISSING) already exists on every alert object.
- Forecast settlement exists in the pipeline (`pipeline.py:371` `settle()`, per-lead (p,y)
  samples surfaced in run verification).

---

## 2. First-30-seconds audit (measured, 1920×1080, judge seat)

| Time | Question a judge asks | What the screen actually says | Verdict |
|---|---|---|---|
| 5 s | What is this? | "Project Vajra — Thunderstorm & Lightning Nowcasting" + a dark world map | PASS |
| 10 s | What problem does it solve? | Nothing on screen says it. Subtitle is a problem-statement ID | FAIL |
| 20 s | What is being observed? | Nothing legible; obs raster is a faint grey rectangle; Data Health says **UNAVAILABLE ×5 in red** | FAIL |
| 30 s | What is being predicted? | **No probability field visible on the map**; Alert Center says "no alerts in this window" | FAIL |
| 60 s | Why is AI/ML involved? | Rung badge reads `REDUCED_MODALITY` / `PHYSICS_BASELINE` (fallback, not the trained model); nothing explains the dual-track engine | FAIL |
| 90 s | What is the warning output? | Alert Center empty (bug, see §3.1); DDMA card says "All administrative blocks clear" while a HIGH storm is on the map | FAIL |
| 3 min | Why is this more than a weather visualization? | Only discoverable via Scoreboard modal, which on SIMULATION events shows BSS "—", ROC-AUC **0.86 fabricated by a code fallback**, and incoherent baseline verdicts | FAIL |

The system *has* all the content to pass every row above. The presentation layer fails to
surface it. Root causes below.

---

## 3. Verified defects (P0 — demo-breaking)

### 3.1 Alert Center can never show an alert during replay (hard bug)
`app.js renderAlerts()` filters by `Math.abs(issued_at − replay_time) < 30 min`. Alert
`issued_at` is **wall-clock time of the run** (verified live: `2026-09-27T14:51:15Z`) while
`replay_time` is **event time** (`2026-05-24T15:20Z`). The window never matches; the list is
permanently "no alerts in this window". The alert objects carry `valid_from`/`valid_until`
in replay time — the filter should use those. Consequence: the DDMA overview card asserts
"🟢 All administrative blocks clear. No active convective warning" **during a P=0.60 HIGH
storm**. This is the single most damaging defect in the demo.

### 3.2 Block-level targeting partially silent (flagship feature degraded) — **RESOLVED in P0**
At audit time, the sampled alert had `affected_districts=[]`, `affected_blocks=[]`,
`population_exposed=0` (`alerts.py:146-176` populates only when the spatial index
intersects). Post-audit root-cause: **the geocoding engine itself works** — a standalone
`SpatialIndex` resolved Patna correctly, and 3 of 4 Bihar-run alerts already carried real
blocks and populations. The real gap was **admin coverage**: the generated boundary set
loaded only 24 districts / 85 blocks, and several case-study cell paths (Nawada/Jamui
corridor, Jharkhand, Himachal) fell outside it. MASTER.md's "765 districts / 534 blocks"
was aspirational, not what the generator produced. **Fix (P0/B-1+B-2):** the generator
hierarchy was extended to **44 districts / 148 blocks** covering every India case-study
cell path (real district/block names, synthetic simplified polygons, honestly documented
in MASTER.md §4 Phase 2); after regeneration, **every alert on every India event (18/18) resolves
to named blocks with exposed population** (verified across all five India replays; SEVIR's
US-domain cells correctly stay block-free).

### 3.3 The probability field — the core product — is invisible
Three stacked causes, all verified:
1. The field is rendered on the **whole-India 321×321 grid**; the storm occupies a few dozen
   pixels; peak-cycle `field.png` is ~1.5 KB (a tiny blob).
2. `fitToGrid()` fits the **entire canonical India grid**, not the event/storm bounding box —
   the camera never gets closer than zoom ≈ 5.4 over the subcontinent.
3. The timeline **lands on empty cycles**: default index = `floor(N/3)` (p = 0.0) and the
   "T0"/"+60m" jumps go to the **last** cycle (storm decayed, p = 0.0, no alerts). Peak
   cycles (e.g. 15:20Z, p_max = 0.603 HIGH) are never where the UI lands.
Net effect: a judge never sees the calibrated probability field at all.

### 3.4 Scoreboard fabricates numbers on SIMULATION runs (honesty violation inside our own UI)
`app.js:947` renders `${fmt(primaryMetrics.roc_auc || 0.86)}` — a **hardcoded 0.86 fallback**
when ROC-AUC is null. BSS shows "—", yet the header still claims "Evaluated vs GLM/ISS-LIS
Flash Truth", and the baseline matrix labels Climatology "CSI 1.00 — DEFICIENT". On
SIMULATION events the scoreboard is incoherent; on the trained SEVIR REPLAY benchmark it is
the strongest asset in the project (BSS +0.50, FAR 0.08 vs negative-skill baselines). The
component must be mode-gated.

### 3.5 The demo path doesn't run the trained model
`model-health` shows `fallback_usage_last_run {PHYSICS_BASELINE: 6, REDUCED_MODALITY: 13}` —
the XGB fusion is loaded but the router downshifts on the default SIM event. The "Dual-Track
AI" story the presenter tells is not what the badge says. Either the demo event/feature
path is fixed so FULL_FUSION engages, or the fallback ladder is elevated into an explicit,
narrated feature (it is genuinely one of the strongest scientific stories available).

### 3.6 Data Health panel misleads in replay context
Five red UNAVAILABLE rows (live providers) dominate the right rail even while viewing a
REPLAY/SIMULATION event; synthetic_* rows only appear after a run. First impression:
"the system is broken." Provider diagnostics belong behind a disclosure for demo mode;
event-context modality health is what L1 needs.

### 3.7 Boot auto-run picks the wrong event
Boot runs the *first* SIMULATION in the list (`multicell_electrification_2026`); the demo
script's canonical event is `bihar_squall_2026`, and the scoreboard moment requires the
trained `sevir_s810646` REPLAY. The zero state contradicts the rehearsal script.

---

## 4. Information-architecture audit (every element classified)

Legend: **KEEP** (working, valuable) · **SIMPLIFY** · **MERGE** · **MOVE** · **HIDE**
(progressive disclosure) · **REWORK** · **REMOVE** · **ADD**.

| Element (where) | Decision | Why |
|---|---|---|
| Topbar brand + subtitle | REWORK | Add one plain-language line ("Predicts lightning 30–60 min ahead") — the 10-second answer |
| Mode/rung/conf badges | KEEP + REWORK | Real honesty fields; rename rung to plain words (Full model / Reduced data / Physics-only) with tooltip |
| Persona switcher | KEEP | Genuine dual-audience story; but fix DDMA "all clear" lie (§3.1) and stop hiding verification in DDMA |
| Event select + Run button | MOVE | Demote from primary panel to a compact "EVENT" strip; Run must never be needed on stage (auto-run + preload) |
| Run status line | MERGE | Fold into the event strip; the run id is noise for judges |
| Transport buttons + speed + loop | KEEP | Works; restyle |
| Clock (UTC + IST) | KEEP | Dual clock is an IMD-credible touch; enlarge for projector |
| Timeline slider | REWORK | Becomes the narrative instrument: observed segment solid, forecast dashed, NOW pin, alert markers, peak flag, click-to-jump (see Blueprint §7) |
| Horizon tags (T-60…+60) | MERGE into timeline | Currently 9 px chips mapping to arbitrary fractions (they conflate *replay progress* with *lead time* — two different axes); their semantics move into the timeline axis |
| Lead select (+30/+60) | KEEP | Fine |
| "actual flashes" checkbox | MOVE | Becomes part of layer preset logic, not a free checkbox |
| Cycle note (issued/modalities) | MERGE | Into the threat card's evidence line |
| **Layers & Filters: 15 checkboxes** | REWORK | Replace L1 with 3 presets — OBSERVE / NOWCAST / COMPARE — and move all individual layers into an "Expert layers" disclosure. Split-slider currently fights the opacity slider (both write `prob-layer` opacity) — resolve into one COMPARE state |
| Probability opacity slider | HIDE | Expert drawer |
| Split-screen verification slider | REWORK | Keep as THE verification visual, but fix conflict + add "actual vs predicted" caption |
| District jump (hardcoded 12) | SIMPLIFY | Keep for demo (Bihar-focused is correct for the story); source centers from admin API where possible |
| Verification table (left, IMD-only) | MOVE | Merge into bottom evidence/verification strip; visible in both personas |
| Alert Center (right) | REWORK | Becomes the **threat summary hero card** (what/where/when/how-confident/why/action) + alert strip; alert ↔ map cell linked (hover/flyTo) |
| Alert card signal dump `k=v · k=v` | REWORK | Humanize into an evidence line; raw values behind disclosure |
| DDMA incident overview | REWORK | Compute from real alert blocks/population; show "—" honestly when geocoding yields nothing, never "all clear" during a storm |
| CAP dispatch / chime / feed | KEEP | Chime only on stage escalation, never per cycle (alarm-fatigue principle) |
| Data health (right) | HIDE → System status popover | Event-context modality chips at L1; provider diagnostics behind disclosure |
| Legend (9 mixed rows) | REWORK | Contextual legend — only what's currently visible; IMD traffic colors reserved exclusively for alerts |
| Footer honesty note | KEEP | Keep exactly |
| Bulletin modal | KEEP | Strong; content falls back to "Domain-wide" when blocks missing (§3.2) |
| Scoreboard modal | REWORK | Mode-gate: full audit for trained REPLAY benchmark; for SIMULATION show "skill claims use the held-out SEVIR benchmark" + link, and never render fallback numbers |
| Verification (settled) | ADD | Per-alert ✓ VERIFIED / ✗ NOT CONFIRMED verdict once the outcome window elapses — data exists (`pipeline.py` settlement) but is not surfaced per alert |
| Threat summary hero | ADD | The missing narrative anchor (Blueprint §5) |
| Event narrative (synoptic) | ADD | `/events/{id}` already returns it; 2-line orient step |
| Model/system status | ADD | `/model-health`, `/workers/status`, `/nwp/gfs/indices` for judge Q&A (L2/L3) |
| Demo rail | ADD | Thin 8-step presentation sequencer over the same UI (Blueprint §11) |

---

## 5. Frontend ↔ backend traceability (target UI → data → status)

| Target UI element | Data | API | Status |
|---|---|---|---|
| Threat hero (what/where/when) | alert fields | `/alerts?run_id&lead` | READY (after §3.1 filter fix) |
| Blocks + exposed population | affected_blocks, population_exposed | same | **BLOCKED on §3.2 backend/data fix** |
| IMD stage strip | imd_stage, headline | same | READY |
| Confidence + rung (plain words) | confidence, fallback_rung | forecasts list | READY |
| Per-modality data chips | alert.data_quality | same | READY |
| Evidence "why" line | contributing_signals | same | READY |
| Trend (Δp vs previous cycle) | steps[].p_flash_max of adjacent cycles | `/runs/{id}/forecasts` | READY (client-side) |
| Show-on-map (alert → camera) | alert.bbox | same | READY |
| Probability field + zoom | field.png + cells bbox | existing | READY (client-side fixes) |
| Timeline alert markers | alert valid_from/imd_stage | existing | READY |
| Settled verdict per alert | flashes in (valid_from, valid_until) | `/events/{id}/flashes.geojson` | READY (client-side) |
| Verification hero numbers | scoreboard metrics | `/runs/{id}/scoreboard` | READY (mode-gate needed) |
| Reliability mini-chart | scoreboard reliability bins | same | READY |
| Event narrative | provenance, synoptic narrative | `/events/{id}` | READY |
| Model/Q&A panel | `/model-health`, `/workers/status`, `/nwp/gfs/indices` | existing | READY |
| Offline basemap | — | — | SMALL (vendor/fallback tiles decision) |
| Full 765-district admin layer | data/admin/*.geojson | `/admin/*` | **SMALL BACKEND/DATA change** (index loads 24/85 today) |

**Backend work required overall: small.** Two items (alert geocoding population, admin
dataset size) + everything else is frontend. No imagined data anywhere in the target design.

---

## 6. Failure-mode inventory (current behavior → required behavior)

| Failure today | Current behavior | Required |
|---|---|---|
| Replay run slow | Button disabled + text only | Skeleton + progress note; runs pre-warmed at boot |
| field/obs PNG missing | Silent catch → empty layer | Chip "field unavailable this cycle", story continues |
| Basemap tiles unreachable (offline venue) | Blank dark map, app still works | Vendor/fallback style; map must never be the failure point |
| Alerts empty (bug) | "no alerts" forever | Fixed by §3.1; honest "no alert above threshold" state otherwise |
| Geocoding empty | "Domain-wide" fallback text | "—" + disclosure; never fake blocks |
| Wrong persona mid-demo | Full panel swap | Persona preserved per step in demo rail |
| Accidental map drag/zoom | Presenter must re-find storm | Reset-view button + demo rail re-orients |
| Model downshifted | Small badge only | Narrated rung chip + explanation popover |

---

## 7. Presentation readiness verdict

Technically clean (0 console errors), scientifically loaded, presentation-hostile: the three
load-bearing demo moments — *probability field*, *named-block alert*, *verification* — are
either invisible, broken, or fabricated-looking in the current UI. All three are fixable
with small, targeted work (§5). The full repair sequence, target design, and rehearsal plan
are in the companion blueprint and implementation plan.
