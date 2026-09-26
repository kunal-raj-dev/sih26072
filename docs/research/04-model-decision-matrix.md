# Deliverable 4 — Model Decision Matrix

Comparison of realistic model approaches for PS 26072, with the selected strategy. Labels: [V] fetched · [S] snippet/literature · [D] our decision.

## A. Spatiotemporal nowcasting models

| Model | Inputs | Output / horizon | Training data | Compute | Code? | Headline claim [S unless noted] | SIH feasibility |
|---|---|---|---|---|---|---|---|
| ConvLSTM (Shi 2015 [V]) | radar echo sequence | future frames | HKO radar | 1 GPU | many reimplementations | beats FC-LSTM & ROVER extrapolation | **YES** — first deep model |
| TrajGRU (Shi 2017) | HKO-7 radar | 0.5–6 h | HKO-7 (not public) | 1 GPU | reimplementations | balanced B-MSE for rare heavy rain | **YES** (reimpl) |
| DGMR (Ravuri, Nature 2021 [V: PMC]) | 4 radar frames 1 km/5-min | 18 frames / 90 min, probabilistic ensemble | UK RadarNet4, held-out 2019 [V] | 16 TPU-cores × 1 week; 1.3 s/frame inference V100 [V] | pseudocode + deepmind weights; OCF PyTorch reimpl | beats PySTEPS & U-Net on CSI/PSD/CRPS; 89–90 % forecaster preference [V] | **CONDITIONAL** — OCF weights inferable; GAN training fragile |
| MetNet (2020 [V: ar5iv]) | 16 ABI bands + MRMS + geo/time | 512-bin precip-rate distribution, 0–8 h, 1 km | CONUS 2018–19 | 225 M params, up to 256 TPUs [V] | Google closed; OCF `metnet` PyTorch | beats HRRN NWP beyond ~1 h | **NO** full retrain; conditional finetune |
| MetNet-2 (2022 [V]) | ABI + MRMS + HRRR DA state (no NWP forecast run) | 0–12 h distribution | CONUS 2017–20 | 16-TPU model-parallel [V] | skeleton Colab only | beats HREF to ~9 h | **NO** |
| NowcastNet (Nature 2023 [V]) | 9 radar fields | 20 fields / 3 h; evolution+generative | MRMS 2016–20 / CMA | heavy | Code Ocean weights [V] | 71 % meteorologist preference; tracks convective fine line | **CONDITIONAL/NO** for SIH |
| **Earthformer** (NeurIPS 2022 [V]) | SEVIR VIL 13→12 frames, 384×384 | future VIL | SEVIR 35,718/9,060/12,159 [V] | 15.1 M params, fits 1×V100 [V] | **YES — official amazon-science + checkpoints** | SEVIR SOTA CSI-M 0.4419 [V/S] | **YES — best open compute/benchmark alignment** |
| RainNet / U-Net (GMD 2020) | radar rain frames | 5-min continuous | RORD (DE) | 1 GPU | github hydrogo/rainnet | strong deterministic | **YES** — simplest deep baseline |
| DiffCast / PreDiff | radar frames | +diffusion residual/probabilistic | SEVIR | multi-GPU | released | beats DGMR-class perceptually | **CONDITIONAL** |

## B. Lightning-specific approaches (core of PS 26072)

| Approach | Inputs → target | Horizon | Evidence | Feasibility |
|---|---|---|---|---|
| **LightningCast pattern** (Cintineo 2022, operational path) [S] | ABI VIS/IR → U-Net → P(≥1 GLM flash/pixel/next hour) | 0–60 min | max CSI 0.4–0.5, POD 0.6–0.8, ~15–30 min lead; transfer-learned to Himawari | **YES in architecture** — INSAT channels in, ILLN/LIS labels out |
| ProbSevere-style fusion [S] | storm-object features (radar+satellite+lightning+NWP) → RF/XGBoost probability | 0–60 min | operational since 2017; v3 ablations quantify each modality's gain | **YES** — late fusion, laptop-scale |
| Lightning-jump rule (Schultz 2009) [S] | flash-rate 2σ jump → severe warning | 12–30 min lead (up to 36–52 automated) | classic, 320+ citations; known false-alarm behavior | **YES** — mandatory baseline |
| ERA5-sounding DL [S] | ERA5 T/q profiles → lightning occurrence | climatology→daily | Met Office FastNet-global (2025); cheap | **YES** — cheapest India-wide experiment |
| WRF-LPI (Lynn & Yair) + India evaluations [S] | WRF microphysics → Lightning Potential Index | 0–24 h | MAUSAM/RMetS India studies | feature source, not core |
| India XAI studies (Mandal 2024 NE-India lightning density; Chatterjee 2023; Jash 2025 IMD-DWR GAN; Saha 2025 XGBoost) [S] | various | density/occurrence | peer-reviewed but research-grade | prior art to cite & extend |

## C. Mandatory baselines [D]

1. **Persistence** (last observation held) — sanity floor.
2. **Climatology** (LIS/OTD 0.1° monthly + IMERG-derived) — required for Brier Skill Score.
3. **Lightning-jump rule** — lightning-side classical baseline.
4. **PySTEPS LK / STEPS ensemble** (with NWP blending) — motion baseline; note advection captures motion, not growth/decay → competitive 0–30 min, degrades after; MSE-trained DL blurs at high thresholds — report both honestly.
5. **Threshold rules** (Z≥40 dBZ proxy from radar imagery; IR ≤ −50 °C area) — naive detectors.
6. **Logistic/XGBoost tabular** — the un-fusioned single-modality controls for ablation.

**Minimum experimental benchmark [D]:** every model claim is reported relative to persistence AND climatology, at 30/60-min leads, with CSI at pre-registered thresholds + FSS + BSS + reliability diagram + lead-time curve, on day-blocked leave-year-out splits with one held-out region and separate pre-monsoon/monsoon reporting.

## D. Selected strategy [D]

| Stage | Model | Why |
|---|---|---|
| Baseline | §C above | credibility; judges ask "compared to what?" |
| **MVP** | **XGBoost late fusion over storm-cell + environmental features** (ProbSevere pattern) | only pattern with a decade of operational proof; debuggable; laptop-scale; graceful degradation built in |
| Improved | **LightningCast-style U-Net on satellite channels** (SEVIR-trained → INSAT-adapted) | direct operational analogue of our exact task; 2 km/1-min inference cheap |
| Advanced | **Earthformer** (official code, 1-GPU) on SEVIR; ensembles + time-to-first-flash regression | open SOTA reference; probabilistic upgrade |

**Why not DGMR/MetNet/NowcastNet first:** Google/DeepMind-scale data engineering + TPU training; closed training pipelines; GAN instability. They are our *ceiling citations*, not our first build. [D]

**Fusion architecture choice [D]:** late fusion (per-modality features → one calibrated classifier) first — modular, ablatable, degrades gracefully when a feed dies; early fusion (stacked-channel CNN/Earthformer) second. Ensemble disagreement reported as an uncertainty signal.
