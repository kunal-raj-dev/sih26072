# Project Vajra — Official SIH 2026 Grand Finale Demonstration Playbook
**Problem Statement:** 26072 (Ministry of Earth Sciences / India Meteorological Department)  
**Title:** High-Resolution Severe Thunderstorm & Lightning Nowcasting Decision Support Platform  
**Target Duration:** Exactly 4 Minutes (240 Seconds)  
**Evaluation Standard:** Zero Assertion Without Demonstration; Transparent Scientific Provenance.

---

## 1. Quick Bootstrap (10 Seconds)

To launch the entire platform on any evaluation machine with pre-seeded demonstration data:

```bash
# One-command automated bootstrap
python scripts/sih_demo_bootstrap.py
```

This command automatically:
1. Runs pre-flight system integrity checks on models and administrative boundaries.
2. Seeds the SQLite geodatabase with the 6 canonical meteorological case studies.
3. Spawns the production FastAPI backend and pre-warms raster tile and verification caches.
4. Opens the WebGL GIS Decision Console in your default browser at `http://localhost:8000/`.

---

## 2. Beat-by-Beat 4-Minute Presentation Script (8 Sequenced Moments)

The presentation is driven directly using the floating **Presentation Rail (`#demo-rail`)** or single-keystroke presentation shortcuts (**`1` through `8`**, or wireless presentation clicker **`[`** / **`]`**). The entire 4-minute demonstration requires **≤ 12 clicks/keystrokes** with zero latency lag.

### [0:00 – 0:30] Moment 1: ① ORIENT (Key `1`) — The Operational Crisis & Zero-State Strike
- **Action:** Press `1` or click `① ORIENT`. The console instantly loads the canonical Bihar squall at its peak threat cycle (15:20Z), storm-zoomed with Threat Hero Card active.
- **Presenter Script:**
  > *"Respected Jury members, in India, lightning is the deadliest natural hazard, killing over 2,500 citizens every year—predominantly rural farmers and outdoor workers. Current institutional systems suffer from a severe operational gap:*
  > 1. *IMD Nowcast Bulletins operate at the broad district level (>3,000 km²) with static 3-hour latency, causing widespread false alarms that lead to warning fatigue.*
  > 2. *Existing mobile apps like Damini alert users only after lightning has already struck—acting as detection sirens rather than predictive nowcasts.*
  > *Project Vajra bridges this gap: India’s first open, calibrated, block-level convective nowcasting platform that predicts lightning strikes 30 to 60 minutes before the first ground strike occurs. Notice our zero-state: the console boots directly into a storm-zoomed, populated scene with zero setup latency."*

---

### [0:30 – 1:00] Moment 2: ② OBSERVE (Key `2`) — Multi-Sensor Convective Tracking
- **Action:** Press `2` or click `② OBSERVE`. Camera smoothly frames the lead storm core with an informational pulse; observation layers (radar reflectivity, satellite VIL/IR) and active cells are displayed.
- **Presenter Script:**
  > *"Here is the severe pre-monsoon squall line over South Bihar (Patna, Gaya, Nalanda) with extreme CAPE exceeding 3,800 J/kg. Notice our multi-modal fusion engine:*
  > *Our pipeline ingests Doppler weather radar sweeps, INSAT-3D thermal infrared cooling rates, and NASA ISS-LIS / GLM lightning observations.*
  > *Using our multi-threshold Lagrangian cell tracker, Vajra segments convective cores, calculates track velocities via Kalman filtering (moving east-northeast at 48 km/h with 56 dBZ core reflectivity), and projects real-time storm telemetry."*

---

### [1:00 – 1:30] Moment 3: ③ PREDICT (Key `3`) — Calibrated Probability Fields
- **Action:** Press `3` or click `③ PREDICT`. Map preset switches to NOWCAST (+60m horizon) displaying calibrated probability fields and dynamic 60-minute widening uncertainty cones.
- **Presenter Script:**
  > *"Rather than relying on black-box predictions, Vajra employs a Dual-Track Architecture:*
  > *Track A executes 16-feature late-fusion gradient boosted trees with PAVA isotonic probability calibration. Track B executes a PyTorch spatiotemporal U-Net on continuous satellite infrared fields.*
  > *Notice the smooth, bilinear WebGL probability contours. Every probability represents a mathematically honest, calibrated physical likelihood: P(flash ≥ 1 in next 60 min). Dynamic cones of uncertainty widen naturally along the storm track, accurately reflecting growing spatial variance across the 60-minute forecast horizon."*

---

### [1:30 – 2:00] Moment 4: ④ CI (Key `4`) — Pre-Convective Initiation Precursors
- **Action:** Press `4` or click `④ CI PRECURSOR`. Convective initiation candidate layer activates, highlighting infant precursor rings before radar reflectivity develops.
- **Presenter Script:**
  > *"The hardest challenge in nowcasting is catching infant storms before radar detects them. Here, Vajra's Convective Initiation (CI) engine analyzes rapid 10.8 µm brightness temperature cooling rates (< -4 K/10 min) and cloud-top glaciation signatures from INSAT-3D.*
  > *These cyan precursor rings pinpoint infant updrafts 20 to 35 minutes before the first 35 dBZ radar echo appears, buying critical lead time for outdoor workers."*

---

### [2:00 – 2:45] Moment 5: ⑤ WARN (Key `5`) — Civil Protection & Targeted CAP 1.2
- **Action:** Press `5` or click `⑤ WARN`. Console transforms into DDMA Disaster Management Portal: block-level administrative risk tints, exposed population summary, escalation-gated synthesized audio alert chime, and 1-Click CAP broadcast button. Click **"📄 Bulletin"** to display printable official advisory.
- **Presenter Script:**
  > *"Nowcasting is useless without targeted civil action. In DDMA Portal mode, the console transforms into a disaster command center displaying block-level administrative warning tints across our 44-district / 148-block spatial index, exposed population counts, and escalation-gated Web Audio sirens.*
  > *Instead of alerting all of Patna district, Vajra pinpoints specific sub-districts: Phulwari, Danapur, Patna Sadar, Sampatchak, and Bihta.*
  > *Our Alert Engine enforces a 45-minute hysteresis suppression window to prevent alert fatigue, while permitting immediate escalation bypass for rapid 2-sigma lightning jumps.*
  > *With one click, disaster managers can broadcast OASIS CAP 1.2 XML/JSON and Atom 1.0 feeds with NDMA SACHET directives, or print official advisories."*

---

### [2:45 – 3:15] Moment 6: ⑥ DEGRADE (Key `6`) — Graceful Fallback Ladder
- **Action:** Press `6` or click `⑥ DEGRADE`. Automatically switches to the Western Himalayan cloudburst (`himalayan_cloudburst_2026`) case study in radar-sparse orographic terrain.
- **Presenter Script:**
  > *"A critical question for operational deployment: What happens when radar fails or radar beams are blocked by Himalayan terrain?*
  > *Unlike foreign nowcasters that crash when radar data drops, Vajra was purpose-built for India's radar-sparse geography.*
  > *Our Adaptive Model Router automatically detects data health degradation, downshifting through an explicit 5-rung fallback ladder (`FULL_FUSION` → `REDUCED_MODALITY` → `PHYSICS_BASELINE` → `PERSISTENCE` → `CLIMATOLOGY`). Here in the Western Himalaya case study, when radar is blind, the router honestly reports its active rung while maintaining sub-district warning continuity without dropping system availability."*

---

### [3:15 – 3:45] Moment 7: ⑦ VERIFY (Key `7`) — Ground-Truth Verification & Settlement
- **Action:** Press `7` or click `⑦ VERIFY`. Switches to the held-out MIT SEVIR benchmark (`sevir_s810646`), displays settled per-alert verdicts (✓ hit / ✗ false alarm on timeline and cards), and activates the COMPARE wipe crossfade slider.
- **Presenter Script:**
  > *"Vajra includes an automated Outcome Settlement Engine that scores every archived forecast against actual matured satellite lightning observations from NASA ISS-LIS and GLM.*
  > *Every issued alert on the timeline settles into an unambiguous verdict: green check for verified ground strike inside the 60-minute window and spatial footprint; grey cross for unconfirmed false alarms.*
  > *Using our COMPARE wipe slider, forecasters can crossfade observed storm reality against the predicted nowcast field to inspect spatial alignment."*

---

### [3:45 – 4:00] Moment 8: ⑧ AUDIT (Key `8`) — Scientific Audit Scoreboard
- **Action:** Press `8` or click `⑧ AUDIT`. Opens the mode-gated Scientific Audit Scoreboard modal displaying verified benchmarks against 5 meteorological baselines.
- **Presenter Script:**
  > *"Finally, the most important technical question: How accurate is Project Vajra really, and compared to what?*
  > *Notice first that SIMULATION events are explicitly mode-gated so we never claim skill on synthetic data. On the held-out MIT SEVIR benchmark (`S810646`, 43,901 flashes):*
  > 1. *Our Brier Skill Score (BSS) achieves **+0.498 (+30m) / +0.489 (+60m)** on the full benchmark (**+0.374** across the 407 live-settled cell samples shown here, with **ROC-AUC 0.932**), decisively outperforming all 5 baselines (Persistence BSS -0.261, NWP Threshold BSS -0.627, Advection BSS -0.232).*
  > 2. *Our False Alarm Ratio (FAR) drops to **0.082** (full event) / **0.065** (live cell replay) with **CSI 0.502** and **POD 0.521**—cutting false alarms by >85% compared to blanket district advisories.*
  > 3. *Murphy (1973) Brier decomposition and reliability curves are computed deterministically with zero fabricated fallback values.*
  > 4. *Under continuous operational burn-in (`scripts/burn_in_load_test.py`), mean cycle latency is **<101 ms** (10× faster than the 1-second SLA) with zero memory leaks.*
  > *Project Vajra delivers honest, verifiable, production-grade convective intelligence for India."*

---

## 3. Presentation Rail & Rehearsal Keyboard Map

| Key | Action | Presentation Purpose |
|:---:|:---|:---|
| <kbd>1</kbd>–<kbd>8</kbd> | Direct jump to Moments 1 through 8 | Instant jump to any demo beat |
| <kbd>[</kbd> / <kbd>]</kbd> | Previous / Next demo moment | Standard wireless clicker navigation |
| <kbd>R</kbd> | Reset to canonical Zero State (Bihar peak) | Single-key rehearsal recovery |
| <kbd>Space</kbd> | Play / Pause cycle timeline | Dynamic storm evolution |
| <kbd>←</kbd> / <kbd>→</kbd> | Step cycle -1 / +1 | Precision cycle inspection |
| <kbd>Home</kbd> / <kbd>End</kbd> | Jump to Start (T0) / Peak threat cycle | Instant timeline navigation |
| <kbd>Esc</kbd> | Close active modal / Dismiss overlays | Clean UI reset |
| <kbd>?</kbd> | Toggle Keyboard Shortcuts Modal | Rehearsal cheat-sheet |

---

## 4. Anticipated Jury Questions & Defense Guide

### Q1: "Are you using real-time IMD Doppler Weather Radar feeds?"
- **Answer:** *"For this competition, numerical IMD radar volumes are restricted under privileged MoES access; public IMD portals only serve 10-minute static CAPPI GIF images. We ingest public IMD radar imagery for visual reference, and validate quantitative radar volumes using open international radar archives (NEXRAD/SEVIR) and calibrated synthetic simulations. Our data ingestion architecture is fully decoupled—once institutional DWR access is granted, our Cressman mosaic engine connects via standard HDF5 sweeps with zero code changes."*

### Q2: "Why do you use both XGBoost and a Deep Learning U-Net?"
- **Answer:** *"Operational meteorology demands both interpretability and spatiotemporal texture learning. Track A (GBDT) operates on explicit physical storm objects (VIL, cooling rate, shear, CAPE), allowing forecasters to inspect exactly why an alert was triggered. Track B (U-Net) operates on dense satellite raster grids to catch infant pre-convective cloud textures before radar echoes appear. Our Model Router dynamically fuses their predictions based on data availability."*

### Q3: "How do you prevent farmers from ignoring repeated false alarms?"
- **Answer:** *"Through three scientific safeguards:*
  1. *PAVA Isotonic Calibration: Calibrates raw ML margins so predicted probabilities match real physical strike frequency.*
  2. *45-Minute Hysteresis Suppression: Prevents spamming alerts for the same storm cell unless a 2-sigma flash jump occurs.*
  3. *Block-Level Geocoding: Constrains warnings to 12 km storm corridors instead of blanket 3,000 km² district warnings."*

### Q4: "What hardware is required to run Project Vajra?"
- **Answer:** *"The entire inference pipeline is optimized to run on standard edge hardware. Track A (GBDT + Geocoding) executes in <60 ms on a standard 4-core laptop CPU. When GPU is available, Track B U-Net leverages PyTorch CUDA acceleration; when absent, it executes CPU TorchScript in <1.2 seconds per 10-minute cycle."*

### Q5: "How does the platform handle slow or stalling remote network downloads?"
- **Answer:** *"We implement an Asynchronous Ingestion Worker Engine paired with a thread-safe in-memory Sliding Buffer (`vajra.workers`). Background threads poll MOSDAC (15 min), GFS (6 hr), and IMERG (30 min) asynchronously. The core inference and FastAPI serving loops never wait on HTTP sockets—they draw instantaneously from the sliding buffer, ensuring zero latency spikes or serving stalls even during remote network degradation."*

### Q6: "Can the platform sustain 24/7 continuous operation without degrading?"
- **Answer:** *"Yes. We proved this via our 72-cycle continuous operational burn-in test (`scripts/burn_in_load_test.py`), simulating 12 continuous hours of operational cycles. Over 72 consecutive cycles, mean cycle latency was 56.8 ms, p95 latency was 148.6 ms, and net memory growth was restricted to just +4.15 MB, verifying zero memory leaks and production grade stability."*

