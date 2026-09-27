# Vajra — Presentation UX Research (operational weather & disaster-decision interfaces)

**Purpose:** extract design *principles* (not visual styles) from serious operational
systems and HCI research, to govern the Vajra demo console redesign. Every principle here
is referenced by the Blueprint (`FRONTEND_PRESENTATION_BLUEPRINT.md`).

**Source-quality key:** **[F]** = primary page fetched and read directly during this
review · **[C]** = corroborated via search-result summaries of primary material ·
**[E]** = established practice / well-known literature, cited from knowledge.

---

## 1. Warning semantics & Indian institutional context

**1.1 IMD impact-based colour-coded warnings [C]**
Org: India Meteorological Department (MoES). The four-level scheme maps colour → action,
not colour → intensity: **Green** = no warning · **Yellow = "Be Updated"** ·
**Orange = "Be Prepared"** · **Red = "Take Action (immediately)"**; each level carries
predicted *impacts* (risk to life, vulnerability of hutments/kutcha houses, outdoor workers).
- URL: https://mausam.imd.gov.in (impact-based forecasting rollout, district-level warnings)
- **Principle extracted:** *Colour encodes the required action; the action words appear
  with the colour. Vajra's alert strip must show `IMD ORANGE — BE PREPARED` together,
  never a bare colour chip.* (The bulletin modal already does this; the map alert UI must match.)
- Consequence: IMD traffic colours (yellow/orange/red) are **reserved** for alert stages
  only. Probability fields, uncertainty, and CI must use different palettes.

**1.2 NDMA SACHET + CAP 1.2 in India [C]**
Org: NDMA. CAP 1.2 (ITU-T X.1303) is the national dissemination standard; SACHET is the
aggregation platform.
- **Principle extracted:** *Machine-readable alert output is a first-class demo artifact* —
  show the CAP XML, not just a pretty card. (Already implemented; keep prominent.)

**1.3 The Damini gap [E]**
Damini/Sidilu alert *after* detection nearby. **Principle:** the demo must dramatize
*detection vs prediction* explicitly (flashes you can see vs probability before the flash).

---

## 2. Probabilistic severe-weather guidance (how NOAA presents ML output)

**2.1 ProbSevere / ProbSevere v2 [C]**
Org: NOAA/NSSL/CIMSS (Cintineo et al. 2014/2020; Karstens et al. 2018, *Development of a
Human–Machine Mix for Forecasting Severe Convective Weather*). Key design: per-storm
probability **attached to the storm object itself** (panel beside the cell) with trend,
environment, and lead context; used as *guidance* inside forecaster workflow, not as a
standalone pretty map.
- **Principles extracted:**
  1. *Probability lives with the storm object* — the cell popup / threat card is the
     natural home for P(flash), trend, and evidence; not a side table alone.
  2. *Guidance is honest about being guidance* — show the model version and inputs used.

**2.2 LightningCast [E]**
Org: NOAA/CIMSS (Rudlosky et al. 2020) — already Vajra's declared precedent (MASTER.md §2).
Continuous GOES/GLM-derived probability fields for next-hour lightning.
- **Principle:** *continuous calibrated fields are the product; cells/cones are the
  explanation layer on top.* So the field must be the most visible map element in the
  NOWCAST view (it currently isn't — see audit §3.3).

**2.3 NHC Track Forecast Cone [F]** (fetched: https://www.nhc.noaa.gov/aboutcone.shtml)
The cone encloses circles whose radii contain **2/3 of official 5-year forecast errors**
along the track; it describes *centre-track uncertainty only*, is fixed per season, and
NHC explicitly warns that impacts extend outside the cone and that the cone is not a
per-storm confidence statement.
- **Principles extracted:**
  1. *Uncertainty envelopes need a one-sentence caption in the UI* — "cone = where the
     storm centre is expected to stay 2 of 3 times" — or viewers over-read them.
  2. *Uncertainty is drawn as a boundary (outline/tint), never as a hazard fill.*
  3. *Envelopes widen with lead time* — Vajra's cones should visibly widen +30→+60.

---

## 3. Communicating probability & uncertainty to non-specialists

**3.1 Joslyn et al., *Communicating uncertainty in weather forecasts* [C]**
(PNAS 2007 and follow-ups; corroborated via ResearchGate/AMS/secondary summaries.)
Deterministic phrases + explicit probability ("70% chance") plus stating the complement
improves decisions; people misread hedged or format-switching forecasts.
- **Principles extracted:**
  1. *Always pair the probability with its reference class:* "64% chance of ≥1 flash
     within 60 min in this block" — never a bare "64%".
  2. *Be consistent: same probability format everywhere* (card, popup, bulletin, alert).
- URL: https://www.pnas.org/doi/10.1073/pnas.0700557103 (fetch blocked; direction corroborated)

**3.2 Kox et al. 2015, *Perception and use of uncertainty in severe weather warnings* [C]**
Uncertainty is better received as frequency/probability + graphic than as verbal hedges.
- **Principle:** *one visual uncertainty device, used consistently* (Vajra: the forecast
  cone + a reliability note), not multiple competing metaphors.

**3.3 Met Office public research on probabilistic forecasts [C]**
~70% of respondents prefer or accept uncertainty information when presented clearly.
- **Principle:** *uncertainty is a feature to show, not hide* — a confidence readout and a
  reliability statement are demo strengths, provided the three axes stay separate.

**3.4 The three-axis rule (hazard ≠ confidence ≠ data quality) [E, synthesized]**
Operational meteorology separates: *what will happen* (hazard/probability), *how much to
trust it* (calibration/confidence/model rung), and *what the inputs are worth* (sensor
health). Conflating them (e.g., a single "confidence 65%" badge doing three jobs) is the
most common failure in ML weather UIs.
- **Principle:** *Vajra's UI must render three visibly distinct channels: probability
  palette on the map; confidence as a labelled readout with rung; data quality as
  per-modality chips (OK/SUSPECT/MISSING).* The alert payload already carries all three.

---

## 4. Temporal design (timeline as instrument)

**4.1 Radar-loop / GFA conventions [C, E]**
Operational time sliders segment the axis: *observed* (solid, past) vs *forecast*
(dashed/tinted, future), with a pinned NOW marker and discrete steps at data cadence
(e.g., Aviation Weather Center GFA help: slider into the past shows observed, into the
future shows forecast).
- **Principles extracted:**
  1. *Past and future must be visually distinct by both colour family and line/dash
     pattern* (redundant encoding for colourblind viewers).
  2. *NOW is pinned and labelled; the horizon (+30/+60) is marked as ticks, not as
     "pages" of the app.*
  3. *Alert events are markers on the axis* (issue ▲, expected impact, verification ✓).

**4.2 Animation discipline [E]**
Radar loops animate the *phenomenon*, never the chrome; speed is adjustable; the loop
always has a visible time readout; looping is explicit (Vajra has this — keep).
- **Principle:** *motion encodes storm advection and forecast evolution only. No ambient
  or decorative animation anywhere in the console.*

---

## 5. Decision-support & control-room UX

**5.1 Situation awareness (Endsley) [E]**
Perception → comprehension → projection. Operational displays support all three levels:
what/where (perception), what it means (comprehension), what happens next (projection).
- **Principle:** *Vajra's single screen must answer, in order: what & where (map +
  threat card) → what it means (IMD stage + evidence) → what's next (+30/+60 timeline +
  cones). The current screen buries level-2 and level-3 answers.*

**5.2 Common Operating Picture / EOC displays [E]**
FEMA/DHS COP practice: one authoritative screen; highest-priority item gets the most
visual weight; everything else one click away; status clutter (comm health, logs) is
collapsed but reachable.
- **Principle:** *the "dashboard wall" is an EOC anti-pattern.* One threat narrative +
  progressive disclosure beats many parallel cards. (Directly motivates the audit's
  panel-collapse plan.)

**5.3 Progressive disclosure in complex consoles [E]**
Three levels: L1 always-visible minimal set; L2 one click for the technically curious;
L3 on request for experts. Never delete depth — relocate it.
- **Principle:** *L1 = story (map, threat, alert, timeline, verification numbers).
  L2 = evidence (why-panel, event narrative, reliability). L3 = engineering (layer
  checkboxes, NPZ, workers, model-health, CAP raw XML).*

**5.4 Alarm fatigue [E]**
Warnings that fire repeatedly at constant salience get ignored; escalation semantics
(new/updated/severity-jump) restore attention.
- **Principle:** *audio chime fires on escalation only; visual pulse once per new alert;
  suppression state is visible ("45-min hysteresis active").* (Backend already implements
  suppression; the UI should narrate it.)

---

## 6. Projection / large-screen legibility

**6.1 Presentation-distance readability [E]**
Rules of thumb used for 10-foot/presentation UI: secondary text ≥ ~16–18 px at 1080p for
3–5 m viewing; primary numbers/hero text ≥ 24–32 px; contrast ≥ WCAG AA (4.5:1 body,
3:1 large) on the dark theme; one idea per panel; avoid dense small tables on stage —
show the 4 numbers that matter and put the table behind a click.
- **Principle:** *current 11–13 px panels fail the judge-seat test.* Minimum body 16 px,
  headings 12→14 px caps, hero numbers 28 px+, legend ≥ 14 px. (Verification: the audit
  screenshots show 9–13 px text everywhere.)

**6.2 Colour systems for scientific maps [E]**
Separate semantic palettes: reflectivity uses the dBZ convention (green→yellow→orange→red
→magenta); probability uses a *sequential* ramp with the alert colours reserved away;
uncertainty uses neutral outline/hatch; distinct hue for CI; point markers for flashes.
Colourblind-safe: redundant shape/dash encoding; avoid red-green-only distinctions
(Okabe–Ito/viridis practice).
- **Principle:** *one gradient cannot serve probability, risk, uncertainty, and radar.*
  Vajra currently mixes yellow/orange/red probability bands with the same hues as IMD
  stages — the two systems must be visually separated.

---

## 7. Consolidated principle set (the contract for the Blueprint)

1. Colour = action (IMD traffic colours only for alert stages, with action words).
2. Hazard, confidence, data-quality are three separate visual channels.
3. Probability is paired with its reference class, everywhere, in one format.
4. Observed vs forecast is doubly encoded (colour + dash/texture), with NOW pinned.
5. Uncertainty is a captioned envelope (outline/tint), widening with lead.
6. Probability lives with the storm object (popup/threat card), not only in a legend.
7. One authoritative screen (COP): story on top, everything else one click away.
8. Progressive disclosure L1/L2/L3; depth relocated, never deleted.
9. Motion encodes the phenomenon only; alerts escalate, they don't spam.
10. Judge-seat legibility: ≥16 px body, hero numbers 28 px+, AA contrast.
11. Distinct palettes per semantic domain; colourblind-redundant encoding.
12. Failure states are information: honest chips, never silent blanks, never fake numbers.
13. Zero state is a populated, storm-zoomed, mid-event working state.
14. Machine-readable outputs (CAP 1.2, NPZ) are demo artifacts, shown on request.
15. Verification is a first-class moment: forecast vs actual, per alert, plus benchmark
    numbers with their mode/evaluated-against provenance.

**Source register (as required):**

| Source | Org/Author | Date | URL | Relevance | Principle extracted | Quality |
|---|---|---|---|---|---|---|
| Definition of the NHC Track Forecast Cone | NOAA/NHC | 2026 season | https://www.nhc.noaa.gov/aboutcone.shtml | Uncertainty envelope semantics | Cone = statistical envelope; caption it; outline not fill | [F] |
| Impact-based colour-coded warnings | IMD (MoES) | current | https://mausam.imd.gov.in | Warning hierarchy for India | Colour = action; Yellow/Orange/Red wording | [C] |
| ProbSevere v2 / HWT evaluations | NOAA NSSL/CIMSS; Karstens et al. 2018 | 2018–2023 | https://inside.nssl.noaa.gov (HWT blog); AMS journals | ML guidance presentation | Probability with storm object; guidance framing | [C] |
| Communicating uncertainty in weather forecasts | Joslyn et al. | 2007+ | https://www.pnas.org/doi/10.1073/pnas.0700557103 | Probability communication | Reference class + consistent format | [C] |
| Perception and use of uncertainty in severe weather warnings | Kox et al. (DWD) | 2015 | https://www.sciencedirect.com (journal) | Uncertainty reception | One consistent uncertainty device | [C] |
| Met Office probabilistic-forecast research | Met Office | 2019–2024 | https://digital.nmla.metoffice.gov.uk | Public acceptance of uncertainty | Show uncertainty deliberately | [C] |
| CAP 1.2 / SACHET | OASIS/ITU; NDMA | current | https://sachet.ndma.gov.in | Alert interoperability | CAP output as demo artifact | [C] |
| AWIPS/warning operations; EOC COP practice | NOAA/NWS; FEMA/DHS | ongoing | (operational practice) | Control-room IA | One screen, hierarchy, collapsed status | [E] |
| Situation Awareness (5-level model) | Endsley | 1995 | (literature) | Decision-support structure | Perception→comprehension→projection | [E] |
| WCAG 2.1 contrast; presentation-size conventions | W3C; industry | current | https://www.w3.org/WAI/WCAG21 | Legibility | ≥16 px body, AA contrast at judge distance | [E] |
| NEXRAD/reflectivity colormap conventions; colourblind-safe scales | NOAA; Okabe–Ito/viridis practice | ongoing | (convention) | Scientific palettes | One palette per semantic domain | [E] |
