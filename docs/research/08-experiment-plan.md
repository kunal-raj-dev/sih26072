# Deliverable 8 — Experiment Plan & Validation Framework

Experiments convert research into engineering decisions. Every model claim is scored on the same harness. Labels: [D] decision · [RESEARCH] literature basis.

## Split protocol (leakage-safe) [D]

- **Block by storm day/event** — samples from one convective day never straddle splits (SEVIR event = 4-h window) [RESEARCH].
- **Leave-year-out / held-out test year** (DGMR 2019 hold-out; NowcastNet US-2021/China-2021 precedent [V]).
- **Spatial hold-out:** one held-out radar station / one held-out SEVIR geographic quadrant.
- **Seasonal reporting:** pre-monsoon (Apr–Jun) vs monsoon (Jul–Sep) reported separately — regimes not interchangeable [RESEARCH].
- **Thresholds pre-registered** before test scoring; never tuned on test.

## Experiments

### E1 — Persistence & climatology floor [D]
- **Hypothesis:** a large fraction of naive skill comes from climatology.
- **Input:** last observation frame; LIS/OTD monthly climatology.
- **Model:** persistence; monthly climatology grid.
- **Output:** 30/60-min probability fields.
- **Metrics:** BSS, CSI, FSS. **Expected:** climatology is surprisingly strong at 60 min over India (hotspots dominate).
- **Success:** stable, reproducible numbers. **Decision:** every later model must report skill *relative to these*; if we can't beat them, we say so.

### E2 — Physics baselines: PySTEPS advection + lightning jump [D]
- **Hypothesis:** advection is competitive ≤30 min but decays; jump rule gives lead but with high FAR.
- **Input:** IMERG/VIL rain fields; (sandbox) MRMS; flash-rate series.
- **Model:** PySTEPS LK + STEPS ensemble (+NWP-blend variant); 2σ jump detector.
- **Metrics:** CSI by lead, FSS, displacement error, FAR of jumps, lead time.
- **Expected:** matches literature decay shape [RESEARCH]. **Decision:** defines the bar the ML must clear at each lead; jump-FAR quantifies the headroom for ML gating.

### E3 — Late-fusion ML (MVP model) [D]
- **Hypothesis:** storm-object features + environmental gating beat both baselines and single-modality controls.
- **Input:** cell attributes (tobac/tintX on VIL/IMERG), IR cooling rates, flash trends, GFS/ERA5 CAPE/shear/RH.
- **Model:** XGBoost + isotonic calibration.
- **Metrics:** BSS vs climatology, reliability, POD/FAR/CSI, ROC-AUC, lead-time curve.
- **Expected:** ProbSevere-like gains; ablation shows each modality's contribution [RESEARCH].
- **Success:** BSS(60 min) > 0 and ≥ persistence; reliability monotone-ish. **Decision:** if fusion ablation shows satellite ≈ radar-only value, prioritize satellite-first (U2).

### E4 — Deep satellite model (LightningCast-India pattern) [D]
- **Hypothesis:** U-Net on satellite channels approaches/exceeds E3, generalizes to India with transfer.
- **Input:** SEVIR ABI channels → GLM probability; later INSAT channels.
- **Model:** U-Net, focal/weighted loss (imbalance) [RESEARCH].
- **Metrics:** as E3 + FSS; **Domain-shift check:** train US → eval on India-months (LIS labels) with explicit caveat.
- **Success:** CSI within ~10 % of E3 on sandbox. **Decision:** ship best of E3/E4 as primary; keep both behind the fallback router.

### E5 — Open-SOTA reference: Earthformer checkpoint [D]
- **Hypothesis:** published SOTA transfers to our harness with its published metrics reproduced.
- **Input:** SEVIR VIL. **Model:** official `earthformer_sevir.pt`.
- **Metrics:** CSI-M vs published 0.4419 [V]; our BSS/lead curves.
- **Decision:** sanity check for harness correctness; NOT our primary model (compute/data mismatch with India).

### E6 — India-mode integration [D, EXPERIMENTAL outcome expected]
- **Hypothesis:** INSAT+ERA5/GFS+LIS produces a useful (if weak-labelled) India nowcast.
- **Input:** MOSDAC archive + GFS/ERA5 + LIS labels; IMD DWR GIFs visual-only.
- **Model:** E3/E4 winners adapted; calibration to Indian climatology.
- **Metrics:** LIS-verified BSS/CSI + caveats; qualitative case studies (Bihar/Jharkhand events).
- **Success:** honest, documented, label-caveated scores; case studies compelling. **Decision:** demo leans on SEVIR sandbox for quantitative claims, India mode for operational story; ILLN access (backlog B-2) would upgrade this to fully-verified.

### E7 — Degradation & latency drills [D]
- **Hypothesis:** fallback ladder holds under feed loss within latency budget.
- **Method:** fault injection (delay/corrupt/drop each modality); measure output quality drift + latency.
- **Success:** graceful degradation visible and labelled; alert latency ≤ budget (Deliverable 9).

## False-alarm / missed-event policy [D]

- Missed lightning (FN) costs lives; false alarms (FP) erode trust (cry-wolf) — optimize neither "accuracy" nor a single operating point.
- Ship **calibrated probabilities** + two threshold presets: **Protective** (high POD, accepted higher FAR — for schools/events) and **Operational** (balanced — for DDMA workflow); display each preset's POD/FAR from our own scoreboard.
- Reliability diagrams published; Brier decomposition reported; recalibration monitored monthly (verification month).

## Deliverable 8 sign-off criteria

No model statement in any SIH material without: (a) harness config hash, (b) split definition, (c) baseline-relative scores, (d) calibration plot, (e) data-mode label.
