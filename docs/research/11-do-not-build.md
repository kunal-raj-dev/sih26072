# Deliverable 11 — "Do Not Build" List

Attractive but wrong. Each item: why it would hurt the project.

1. **Generic weather-app features** (city search, 7-day forecasts, UV/air-quality cards) — not the PS; a thousand apps do it better; dilutes the scientific story.
2. **LLM chatbot / "ask the weather AI"** — no predictive value; adds hallucination risk to a trust-critical system; judges increasingly penalize it; violates "no AI everywhere" (Part 12).
3. **"100 % accurate lightning prediction" claims or leaderboards vs IMD** — unverifiable without IMD internal verification data; instantly dismantled by any meteorologist judge (Part 39).
4. **Raw volumetric radar ingestion as a promise** — data is paid/approval-gated [VERIFIED]; building the pipeline before access = dead code. GIF→grid work stays [EXPERIMENTAL].
5. **Real-time ILLN/Damini integration promises** — no public API [VERIFIED]; request via IITM (backlog) instead of scraping an app.
6. **Microservices + Kubernetes + Kafka event mesh** — single-host Docker Compose suffices at our scale; ops complexity steals ML time (Part 41: avoid unnecessary complexity).
7. **WoFS-style convection-allowing ensemble DA** — requires HPC + assimilation infrastructure (a decade of NSSL effort) [S]; consume NWP instead.
8. **Training DGMR/MetNet-class models from scratch** — TPU-scale data engineering [V/S]; use open checkpoints as references (E5), build XGBoost/U-Net first.
9. **Social features, crowdsourced reports, gamification** — validation impossible in SIH timeframe; safety-adjacent liability.
10. **Public push-notification app as the MVP deliverable** — last-mile exclusion is documented (users lack smartphones/apps) [V]; CAP/SACHET-style JSON output is the right interface for now.
11. **Flashy 3-D globe / cinematic storm animations** — demo polish without evidentiary value; map layers with honest uncertainty panels win technical judges.
12. **Pixel-accuracy ("accuracy = 99 %") reporting** — meaningless under extreme class imbalance; our scoreboard uses BSS/CSI/FSS/lead-time.
13. **Scraping government portals beyond intended use** (bulk AWS portal hammering, DSP bypass attempts) — ethical + legal exposure; use official channels and record the request trail.
14. **Pretending replay/simulation is live government data** — the single fastest way to fail a knowledgeable judge's probing question; modes are always badged (Part 28).
15. **Excessive dashboards for every modality** — one operational view + verification scoreboard; panel-per-dataset sprawl hides the decision layer.
