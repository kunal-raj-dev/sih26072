You are not acting as a normal coding assistant.

You are acting as a multidisciplinary research and product team helping us develop a serious software solution for Smart India Hackathon 2026.

Your job is to take the problem statement below, independently research it from the internet, challenge our assumptions, study existing scientific and operational systems, determine what is actually feasible, and then design the strongest defensible solution that a student team can realistically build.

Do NOT start by suggesting features.
Do NOT start by suggesting a tech stack.
Do NOT start by designing a dashboard.

First understand the science, data, operational problem, existing solutions, constraints, and opportunity.

Then derive the product.

============================================================
PROJECT / PROBLEM STATEMENT
============================================================

Smart India Hackathon 2026

Problem Statement ID:
26072

Problem Statement:
“AIML based Nowcasting of thunderstorm and lightning using atmospheric observation including multiple radars, satellite, lightning and model data.”

Organization:
Ministry of Earth Sciences (MoES)

Department:
India Meteorological Department (IMD)

Category:
Software

Theme:
Disaster Management

============================================================
OUR OBJECTIVE
============================================================

We want to build a software-based system capable of assisting with short-term thunderstorm and lightning nowcasting using multiple atmospheric observations.

The proposed system should ideally be capable of taking relevant observations such as:

- radar observations
- satellite observations
- lightning observations
- numerical weather/model data
- other useful atmospheric observations

and turning them into useful short-term predictions / risk information / alerts.

However:

DO NOT assume that all of these data sources are actually accessible to us.

DO NOT assume that real-time APIs are public.

DO NOT assume that a research dataset is usable in a production system.

DO NOT assume that an academic model will work on Indian data.

DO NOT assume that “AI” automatically means a useful solution.

Determine these things through research.

============================================================
THE CORE QUESTION
============================================================

Answer this question rigorously:

“What is the strongest scientifically defensible, technically feasible, software-only solution that a student SIH team can build for PS 26072, while still being meaningfully different from existing systems?”

Everything in your research should ultimately support answering this.

============================================================
OPERATING MODE
============================================================

Think in this sequence:

PROBLEM
→ SCIENCE
→ DATA
→ EXISTING SYSTEMS
→ GAP
→ OPPORTUNITY
→ SOLUTION
→ MODEL
→ ARCHITECTURE
→ MVP
→ VALIDATION
→ PHASES
→ SIH DEMO

Do NOT reverse this order.

Do not begin with:
“Let’s build a React dashboard with a CNN.”

That is exactly the type of premature solutioning we want to avoid.

============================================================
RULE 1 — DEEP WEB RESEARCH
============================================================

Perform serious internet research.

Use current information available on the web.

Do not rely on one or two search results.

Search across:

- IMD
- Ministry of Earth Sciences
- ISRO
- MOSDAC
- Government of India portals
- data.gov.in
- NCMRWF
- official meteorological institutions
- Indian research institutes
- peer-reviewed literature
- IEEE
- ACM
- AMS
- Springer
- Nature
- arXiv
- GitHub
- official technical documentation
- international meteorological agencies
- operational weather organizations
- major commercial weather platforms
- relevant research projects

Search iteratively.

When you discover an important concept, organization, dataset, model, or system, search that specifically as well.

Do not stop after finding a plausible answer.

============================================================
RULE 2 — SOURCE HIERARCHY
============================================================

Use this source hierarchy:

TIER 1:
Official government / meteorological / scientific institution sources

TIER 2:
Peer-reviewed papers and reputable research institutions

TIER 3:
Official technical documentation / project repositories / engineering documentation

TIER 4:
Reputable industry sources

Avoid using random blogs or SEO websites as primary evidence.

For every important factual claim, provide a source.

For important datasets, APIs, models and operational systems, provide:

- exact name
- organization
- URL
- documentation URL where available
- publication / update date where available
- what the source proves
- limitations

Never cite a search snippet when the underlying page/document can be inspected.

============================================================
RULE 3 — FACT VS ASSUMPTION
============================================================

This distinction is mandatory.

Every important statement must effectively belong to one of these categories:

VERIFIED FACT
RESEARCH FINDING
DOCUMENTED SYSTEM CAPABILITY
OUR INFERENCE
PROPOSED DESIGN
UNVERIFIED ASSUMPTION
BLOCKED / UNKNOWN

Never present an assumption as a fact.

If information cannot be verified, explicitly say:

“Not verified.”

============================================================
PART 1 — DECODE THE PROBLEM STATEMENT
============================================================

Before thinking about the solution, determine what PS 26072 actually asks for.

Analyze every important phrase:

“AIML based”
“Nowcasting”
“thunderstorm”
“lightning”
“atmospheric observation”
“multiple radars”
“satellite”
“lightning”
“model data”

Explain what each term means scientifically and operationally.

Then answer:

1. What is the actual problem?
2. Who experiences the problem?
3. Who would consume the output?
4. What decision should the system improve?
5. What is the required forecast horizon?
6. What spatial granularity is useful?
7. What temporal granularity is useful?
8. What exactly should be predicted?
9. What should NOT be claimed?
10. What would count as a successful solution?

Also identify ambiguities in the PS.

============================================================
PART 2 — UNDERSTAND NOWCASTING SCIENTIFICALLY
============================================================

Explain:

- nowcasting
- short-range forecasting
- numerical weather prediction
- storm tracking
- convective initiation
- thunderstorm detection
- lightning prediction
- lightning probability
- storm intensity
- storm movement
- hazard forecasting
- impact-based warning

Explain why thunderstorm and lightning nowcasting is technically difficult.

Investigate:

- rapid atmospheric evolution
- nonlinear convection
- sparse observations
- sensor latency
- data quality
- spatial variability
- temporal variability
- class imbalance
- rare extreme events
- false alarms
- missed events
- geographical domain shift
- seasonality
- monsoon dynamics
- sensor outages
- uncertainty

Do not give generic weather explanations.

Focus on what matters for PS 26072.

============================================================
PART 3 — DETERMINE THE ACTUAL PREDICTION TARGET
============================================================

This is one of the most important research questions.

Investigate possible targets:

A. Thunderstorm occurrence
B. Lightning occurrence
C. Lightning probability
D. Lightning density
E. Lightning frequency/intensity
F. Storm-cell detection
G. Storm-cell movement
H. Convective initiation
I. Storm severity
J. Hazard probability
K. Time-to-event
L. Spatial hazard field
M. Probabilistic forecast

For each target explain:

- what it means
- required data
- difficulty
- usefulness
- suitable forecast horizon
- suitable evaluation metrics
- suitability for our project
- whether it belongs in MVP / later phase

Then determine the most defensible output definition for the first prototype.

============================================================
PART 4 — OFFICIAL INDIAN DATA LANDSCAPE
============================================================

This section must be extremely detailed.

Research official Indian data sources.

Investigate:

RADAR

Find information about:

- Doppler Weather Radar
- radar coverage
- radar products
- reflectivity
- velocity
- precipitation
- dual-polarization variables if available
- composite products
- temporal frequency
- data formats
- accessibility
- historical archives
- near-real-time access

SATELLITE

Investigate relevant Indian satellite observations and products, including relevant INSAT/MOSDAC resources where appropriate.

Research:

- infrared
- visible
- water vapor
- cloud-top temperature
- cloud classification
- derived atmospheric products
- scan frequency
- spatial resolution
- historical archive
- real-time accessibility

LIGHTNING

Investigate:

- Indian lightning detection infrastructure
- government datasets
- satellite-derived lightning products
- lightning networks
- lightning observations
- flash-level data
- density products
- historical datasets
- research-access datasets
- near-real-time possibilities

MODEL / ATMOSPHERIC DATA

Investigate:

- NWP model data
- reanalysis
- atmospheric profiles
- temperature
- humidity
- wind
- CAPE and relevant instability indicators
- pressure-level fields
- precipitation forecasts
- other relevant predictors

SURFACE OBSERVATION

Investigate relevant:

- AWS
- weather stations
- surface observations
- temperature
- humidity
- pressure
- wind
- rainfall

For EVERY dataset/product, create a table:

DATASET / PRODUCT
SOURCE
OFFICIAL?
OPEN?
REAL-TIME?
HISTORICAL?
SPATIAL RESOLUTION
TEMPORAL RESOLUTION
VARIABLES
ACCESS METHOD
API?
DOWNLOAD?
LICENSE
ACCESS RESTRICTION
INDIA COVERAGE
USEFULNESS
SIH FEASIBILITY
PROTOTYPE USE
PRODUCTION USE

Most importantly:

Separate:

1. Public and directly usable
2. Public but technically difficult
3. Research-accessible
4. Restricted
5. Commercial
6. Historical only
7. Unknown
8. Can only be simulated/replayed for demo

============================================================
PART 5 — DATA ACCESS REALITY CHECK
============================================================

This is mandatory.

We need a brutally honest answer to:

“What data can a student team actually get?”

Do not say:

“Use IMD radar API”

unless you have verified such access.

Do not say:

“Use real-time lightning data”

unless access is verified.

For each important data source tell us:

CAN WE ACTUALLY USE IT?
YES / NO / CONDITIONAL / UNKNOWN

Then explain why.

Identify the minimum data combination required to create a meaningful prototype if ideal data is unavailable.

Design fallbacks such as:

Ideal:
Radar + Satellite + Lightning + NWP

Fallback:
Satellite + Lightning + NWP

Fallback:
Radar + Satellite

Fallback:
Historical replay dataset

Fallback:
Public weather observation + satellite

But do not invent data sources.

============================================================
PART 6 — RESEARCH DATASETS FOR MODEL DEVELOPMENT
============================================================

Search deeply for suitable datasets globally and in India.

Look for:

- radar datasets
- satellite datasets
- lightning datasets
- severe-weather datasets
- weather observation datasets
- reanalysis
- benchmark datasets
- nowcasting datasets
- open research datasets

For each dataset provide:

- source
- time span
- geography
- resolution
- variables
- format
- size
- license
- access requirements
- training suitability
- validation suitability
- India relevance
- limitations

Then identify:

BEST DATASET FOR INITIAL EXPERIMENTATION

and explain why.

============================================================
PART 7 — EXISTING INDIAN SYSTEMS
============================================================

Research what India already has.

Do not assume we are solving a problem nobody has addressed.

Investigate:

- IMD warning systems
- thunderstorm forecasting systems
- lightning warning systems
- radar-based systems
- satellite-based warning systems
- district-level warnings
- mobile/public alerts
- research systems
- government dashboards
- operational products
- related disaster-management systems

For each system identify:

WHAT EXISTS
HOW IT WORKS
DATA USED
FORECAST HORIZON
USER
STRENGTHS
LIMITATIONS
PUBLIC ACCESS
WHAT PS 26072 MAY STILL BE ASKING FOR

This section must help us avoid reinventing existing infrastructure.

============================================================
PART 8 — GLOBAL EXISTING SYSTEMS
============================================================

Research relevant systems from:

- NOAA
- National Weather Service
- ECMWF
- EUMETSAT
- Met Office
- Bureau of Meteorology Australia
- Japan Meteorological Agency
- other relevant organizations

Also investigate serious commercial / research systems where relevant.

For each:

- objective
- data
- algorithm/model
- resolution
- forecast horizon
- operational status
- interface
- strengths
- limitations
- open-source status
- lessons for us

Do NOT merely list them.

Extract architectural ideas and gaps.

============================================================
PART 9 — STATE OF THE ART RESEARCH
============================================================

Research academic approaches for:

- radar nowcasting
- satellite nowcasting
- lightning prediction
- convective initiation
- storm tracking
- multimodal fusion
- spatiotemporal prediction
- uncertainty estimation
- probabilistic forecasting

Investigate relevant methods including, where appropriate:

- persistence baseline
- optical flow
- PySTEPS
- CNN
- U-Net
- ConvLSTM
- ConvGRU
- encoder-decoder
- attention
- Transformer
- spatiotemporal Transformer
- graph neural networks
- probabilistic models
- diffusion models
- hybrid physics + ML
- object-based storm tracking
- ensemble approaches

Do not assume the newest model is the best model.

For each serious candidate:

INPUTS
OUTPUTS
TRAINING DATA
COMPUTE
INFERENCE LATENCY
ADVANTAGES
LIMITATIONS
DATA REQUIREMENTS
INTERPRETABILITY
INDIAN RELEVANCE
SIH FEASIBILITY

============================================================
PART 10 — BASELINES
============================================================

Determine the scientific baselines we should compare against.

At minimum investigate whether appropriate baselines include:

- persistence
- climatology
- optical-flow advection
- storm-cell tracking
- conventional meteorological thresholds
- simple statistical models

The project should not claim AI superiority without baseline comparison.

Define the minimum experimental benchmark.

============================================================
PART 11 — DETERMINE WHETHER MULTI-MODAL FUSION IS ACTUALLY WORTH IT
============================================================

The problem explicitly mentions:

multiple radars + satellite + lightning + model data.

Investigate how these sources can complement one another.

Study:

EARLY FUSION
INTERMEDIATE FUSION
LATE FUSION
ENSEMBLES
SPECIALIST MODELS
HYBRID APPROACHES

Determine which approach is realistic.

Also investigate whether different modalities should have different roles.

For example, conceptually:

Radar → storm structure/movement
Satellite → cloud evolution
Lightning → electrical activity
Model data → environmental context

Do not accept this example blindly.

Verify scientifically.

============================================================
PART 12 — DESIGN THE ACTUAL FORECAST PIPELINE
============================================================

Design the pipeline:

OBSERVATION
↓
INGESTION
↓
QUALITY CONTROL
↓
TEMPORAL ALIGNMENT
↓
SPATIAL ALIGNMENT
↓
FEATURE ENGINEERING
↓
MODEL
↓
FORECAST
↓
CALIBRATION / UNCERTAINTY
↓
RISK INTERPRETATION
↓
ALERT
↓
USER ACTION

Explain each stage.

Identify where AI belongs and where deterministic algorithms are more appropriate.

Do not use AI everywhere.

============================================================
PART 13 — MODEL STRATEGY
============================================================

Create:

BASELINE
→ MVP MODEL
→ IMPROVED MODEL
→ ADVANCED MODEL

For example, investigate whether the progression could involve:

Baseline:
Persistence / optical flow / classical tracking

MVP:
Spatiotemporal deep-learning model

Improved:
Multimodal fusion

Advanced:
Probabilistic / uncertainty-aware / hybrid architecture

But DO NOT assume this progression is correct.

Research and derive the actual progression.

============================================================
PART 14 — SYSTEM ARCHITECTURE
============================================================

Only after completing the research, design the architecture.

Cover:

DATA INGESTION
DATA STORAGE
DATA PROCESSING
GEO-SPATIAL LAYER
FEATURE ENGINEERING
MODEL TRAINING
MODEL REGISTRY
MODEL INFERENCE
FORECAST STORAGE
API
REAL-TIME PROCESSING
ALERT ENGINE
FRONTEND
MAP
MONITORING
LOGGING
AUTHENTICATION
DEPLOYMENT

Recommend only technologies that are justified.

Consider:

- Python
- PyTorch
- FastAPI
- PostgreSQL/PostGIS
- Redis
- object storage
- Docker
- Next.js/React
- MapLibre/Mapbox/Leaflet
- Xarray
- Rasterio
- GeoPandas

But these are possibilities, NOT decisions.

============================================================
PART 15 — OPERATIONAL LATENCY
============================================================

Research the practical latency problem.

Determine the desired relationship:

OBSERVATION ARRIVES
→ PROCESSING
→ MODEL INFERENCE
→ FORECAST GENERATED
→ ALERT DELIVERED

Identify:

- acceptable latency
- data refresh rate
- inference time
- map update frequency

Design a realistic latency budget.

============================================================
PART 16 — UNCERTAINTY & TRUST
============================================================

This is a disaster-management problem.

Research how to represent:

- probability
- confidence
- uncertainty
- model disagreement
- observation quality
- missing data
- forecast evolution

A single colored “danger map” is not enough.

Determine what an operational user should actually see.

============================================================
PART 17 — FALSE POSITIVES & FALSE NEGATIVES
============================================================

This system can cause harm if warnings are poor.

Research the tradeoff between:

- missed events
- false alarms
- lead time
- warning confidence

Determine appropriate metrics and calibration strategies.

Do not optimize only for “accuracy”.

============================================================
PART 18 — VALIDATION FRAMEWORK
============================================================

Design the evaluation methodology.

Research appropriate metrics including relevant combinations of:

- POD
- FAR
- CSI
- HSS
- precision
- recall
- F1
- PR-AUC
- ROC-AUC
- Brier score
- calibration
- FSS
- spatial error
- displacement error
- lead time
- latency

Determine the correct metrics for each forecast output.

Also design:

TRAIN
VALIDATION
TEST

splits that avoid leakage.

Investigate:

- temporal leakage
- spatial leakage
- seasonal leakage
- event leakage

============================================================
PART 19 — INDIA-SPECIFIC RESEARCH
============================================================

Do not build a generic global-weather solution.

Investigate Indian-specific characteristics relevant to thunderstorm/lightning nowcasting.

Study:

- pre-monsoon thunderstorms
- monsoon convection
- post-monsoon behaviour
- regional differences
- geography
- Himalayas
- Gangetic plains
- central India
- northeast India
- coastal regions
- urban effects where relevant

Determine how geography and seasonal behaviour should influence the model and evaluation strategy.

============================================================
PART 20 — IDENTIFY THE REAL USER
============================================================

Research the operational workflow.

Potential users may include:

- IMD forecasters
- district authorities
- disaster-management agencies
- emergency services
- NDRF/SDRF
- infrastructure operators
- aviation
- railways
- agriculture
- schools/events
- public users

Do not attempt to build for everyone.

Determine:

PRIMARY USER
SECONDARY USER
END BENEFICIARY

Then answer:

“What exact decision does our software help the primary user make?”

============================================================
PART 21 — PRODUCT DEFINITION
============================================================

Now derive the product.

Give it a temporary project name.

Define:

PRODUCT VISION
PROBLEM
USER
INPUT
INTELLIGENCE
OUTPUT
ACTION

Then define the smallest coherent product that solves the problem.

Avoid turning it into a generic weather application.

============================================================
PART 22 — CORE PRODUCT CAPABILITIES
============================================================

Derive the actual capabilities from research.

Potential categories to evaluate:

- observation map
- radar visualization
- satellite visualization
- lightning visualization
- storm-cell detection
- cell tracking
- thunderstorm probability
- lightning probability
- forecast timeline
- affected area
- confidence
- uncertainty
- alert generation
- alert history
- event replay
- district view
- impact-aware risk
- data health
- model health
- human feedback

Only include capabilities justified by the research.

============================================================
PART 23 — USP / DIFFERENTIATION
============================================================

This needs special attention.

Do not write weak claims such as:

“AI-powered”
“Real-time”
“User-friendly”
“Modern dashboard”
“Cloud-based”

These are not strong USPs.

Instead research:

EXISTING SYSTEM
→ WHAT IT DOES
→ WHERE THE GAP IS
→ WHY THE GAP MATTERS
→ WHAT WE CAN BUILD
→ WHY IT IS DEFENSIBLE

Identify potential differentiation in areas such as:

- multimodal fusion
- hyperlocal forecasting
- lightning-focused nowcasting
- storm-cell evolution
- uncertainty-aware warnings
- explainable forecasts
- impact-based risk
- adaptive alerts
- district-level operational support
- low-bandwidth deployment
- multilingual interfaces
- graceful degradation when data sources fail
- human-in-the-loop feedback
- historical event replay and verification
- confidence-aware decision support

But ONLY retain USPs supported by evidence.

Separate:

CORE DIFFERENTIATOR
SECONDARY DIFFERENTIATOR
FUTURE DIFFERENTIATOR

============================================================
PART 24 — COMPETITIVE GAP ANALYSIS
============================================================

Create a comparison matrix:

SYSTEM
DATA
FORECAST
HORIZON
SPATIAL RESOLUTION
AI/ALGORITHM
LIGHTNING
THUNDERSTORM
UNCERTAINTY
ALERTS
USER
PUBLIC ACCESS
OPEN SOURCE
LIMITATIONS
LESSON FOR US

Then create:

EXISTING LANDSCAPE
→ UNSOLVED GAP
→ OUR OPPORTUNITY

Do not claim we are unique unless the evidence supports that statement.

============================================================
PART 25 — “DON'T BUILD THIS” ANALYSIS
============================================================

This section is mandatory.

Identify attractive but unnecessary features.

Tell us what to avoid because it would:

- waste time
- increase complexity
- weaken scientific credibility
- require inaccessible data
- create demo-only gimmicks
- distract from the actual PS
- be difficult to validate

Examples to investigate:

- generic weather app features
- social/community features
- excessive dashboards
- unnecessary microservices
- unnecessary LLM integration
- fancy AI without scientific value
- unsupported “100% accurate” forecasting claims
- huge model architectures without training data
- features that depend on unavailable government APIs

============================================================
PART 26 — MVP
============================================================

Define the smallest serious MVP.

The MVP must demonstrate:

OBSERVATION
→ PROCESSING
→ PREDICTION
→ MAP
→ WARNING / DECISION SUPPORT

Define:

- exact input data
- exact prediction target
- baseline
- model
- output format
- UI
- evaluation
- demo flow

The MVP must be achievable without pretending to have unavailable capabilities.

============================================================
PART 27 — PROTOTYPE VS OPERATIONAL SYSTEM
============================================================

Create two separate definitions.

A. SIH PROTOTYPE

What we can realistically demonstrate.

B. FUTURE OPERATIONAL SYSTEM

What would be required for deployment by a government/meteorological organization.

Clearly distinguish them.

This distinction is extremely important.

============================================================
PART 28 — THREE DATA MODES
============================================================

Design:

MODE 1 — LIVE
Real accessible data

MODE 2 — HISTORICAL REPLAY
Historical cases used to reproduce realistic forecasting scenarios

MODE 3 — SIMULATION / DEMONSTRATION
Synthetic or controlled demonstration inputs

Clearly label them.

Never recommend presenting simulated data as live government data.

============================================================
PART 29 — FAILURE / FALLBACK DESIGN
============================================================

Design the system to handle:

- radar unavailable
- satellite unavailable
- lightning unavailable
- delayed feed
- malformed data
- missing observations
- conflicting observations
- model failure
- GPU failure
- API failure

Investigate whether the system should degrade gracefully through:

MULTIMODAL MODEL
→ REDUCED-MODALITY MODEL
→ PHYSICS / TRACKING BASELINE
→ PERSISTENCE BASELINE

Design a defensible fallback strategy.

============================================================
PART 30 — TECHNICAL FEASIBILITY
============================================================

Create a feasibility matrix:

CAPABILITY
DATA AVAILABLE?
TRAINING FEASIBLE?
COMPUTE FEASIBLE?
REAL-TIME FEASIBLE?
VALIDATION FEASIBLE?
SIH FEASIBLE?
FUTURE OPERATIONAL FEASIBLE?

Mark:

YES
NO
CONDITIONAL
UNKNOWN

Explain every “NO” and “CONDITIONAL”.

============================================================
PART 31 — PHASED DEVELOPMENT ROADMAP
============================================================

Only after research is completed, create the development roadmap.

Do not blindly create arbitrary phases.

Create dependency-aware phases.

For each phase provide:

PHASE NAME
OBJECTIVE
SCIENTIFIC GOAL
PRODUCT GOAL
DATA WORK
ML WORK
BACKEND WORK
FRONTEND WORK
GIS WORK
TESTING
DELIVERABLE
DEPENDENCIES
RISKS
DEFINITION OF DONE

Suggested progression to investigate:

Phase 0 — Research / Data Validation
Phase 1 — Data Foundation
Phase 2 — Baseline Nowcasting
Phase 3 — First ML Model
Phase 4 — Multimodal Fusion
Phase 5 — Real-Time Inference
Phase 6 — Risk / Alert Engine
Phase 7 — Explainability / Uncertainty
Phase 8 — Operational Dashboard
Phase 9 — Evaluation / Hardening
Phase 10 — SIH Demonstration

But change this sequence if research shows a better dependency structure.

============================================================
PART 32 — FIRST VERTICAL SLICE
============================================================

Design the FIRST END-TO-END working slice.

We should be able to go from:

DATA
→ PROCESS
→ MODEL
→ FORECAST
→ API
→ MAP
→ RESULT

even if the model is simple initially.

Define exactly what this first slice should contain.

============================================================
PART 33 — FIRST 7 DAYS
============================================================

Create a practical first-week execution plan.

Each day should answer:

WHAT DO WE BUILD?
WHY?
WHAT OUTPUT SHOULD EXIST BY END OF DAY?
HOW DO WE VERIFY IT?

Do not waste the first week building a polished frontend.

The first week should reduce the biggest technical uncertainties.

============================================================
PART 34 — PARALLEL TEAM WORKSTREAMS
============================================================

Assume a student team with multiple people.

Divide work into:

RESEARCH
DATA
ML
BACKEND
GIS
FRONTEND
DEVOPS
TESTING

Determine which tasks can run in parallel and which are blocked by others.

============================================================
PART 35 — SIH DEMO STRATEGY
============================================================

Design a 3–5 minute demonstration.

The demo should tell a clear technical story.

For example:

1. Select geographic region
2. Show current observations
3. Identify developing storm
4. Show historical/live observation sequence
5. Run/display nowcast
6. Show movement
7. Show lightning/thunderstorm probability
8. Show confidence
9. Highlight affected area
10. Generate decision-support warning
11. Explain why the system generated the alert

But derive the final flow from the actual architecture.

Identify:

WHAT JUDGES SEE
WHAT JUDGES LEARN
WHAT TECHNICAL CLAIMS WE CAN PROVE

============================================================
PART 36 — SIH PRESENTATION STORY
============================================================

Develop the technical narrative:

PROBLEM
→ CURRENT LIMITATION
→ DATA
→ AI
→ INNOVATION
→ OUTPUT
→ IMPACT
→ VALIDATION
→ SCALABILITY

Do not use marketing language without technical substance.

============================================================
PART 37 — RISK REGISTER
============================================================

Create a serious risk register.

Include:

- data access
- dataset quality
- dataset scale
- compute
- training time
- model performance
- false alarms
- latency
- API dependency
- geospatial complexity
- deployment
- real-time integration
- scientific validation
- team capacity

For each:

RISK
LIKELIHOOD
IMPACT
EARLY WARNING SIGN
MITIGATION
FALLBACK

============================================================
PART 38 — RESEARCH EXPERIMENT PLAN
============================================================

Design the experiments we should actually run.

Examples:

Experiment 1:
Persistence baseline

Experiment 2:
Optical-flow / tracking baseline

Experiment 3:
Radar-only ML

Experiment 4:
Satellite + radar

Experiment 5:
Radar + satellite + lightning

Experiment 6:
Add model/environmental variables

But determine the actual experiments from the literature and available datasets.

For each experiment define:

HYPOTHESIS
INPUT
MODEL
OUTPUT
METRICS
EXPECTED RESULT
SUCCESS CRITERIA
DECISION AFTER EXPERIMENT

This converts research into engineering decisions.

============================================================
PART 39 — SCIENTIFIC CLAIMS WE MUST NOT MAKE
============================================================

Create a section:

“CLAIMS WE MUST NOT MAKE WITHOUT EVIDENCE”

Examples to investigate:

- operational-grade prediction
- superior accuracy
- government deployment
- real-time access
- universal geographic performance
- exact lightning prediction
- guaranteed warning lead time

State what evidence would be required before making such claims.

============================================================
PART 40 — FINAL ARCHITECTURE
============================================================

After all research and decisions, create:

1. High-level architecture
2. Detailed data pipeline
3. ML pipeline
4. Real-time inference pipeline
5. Forecast pipeline
6. Alert pipeline
7. Fallback architecture
8. User workflow

Use Mermaid diagrams.

============================================================
PART 41 — FINAL TECH STACK
============================================================

Now, and only now, recommend the technology stack.

For every technology answer:

WHY THIS?
WHY NOT SIMPLER?
WHAT DEPENDENCY DOES IT SOLVE?

Potential areas:

Frontend
Backend
ML
Data Processing
GIS
Database
Storage
Cache
Queue
Model Serving
Deployment
Monitoring
Testing

Avoid unnecessary complexity.

============================================================
PART 42 — CODEBASE / PROJECT STRUCTURE
============================================================

Design an implementation-oriented project structure.

Separate concerns clearly between:

- frontend
- backend
- data pipeline
- ML
- inference
- GIS
- evaluation
- experiments
- datasets
- configuration
- documentation

Explain what belongs where.

============================================================
PART 43 — BACKLOG
============================================================

Convert the final architecture into:

EPIC
→ FEATURE
→ TASK
→ SUBTASK

Mark each:

MUST HAVE
SHOULD HAVE
COULD HAVE
LATER

Every item should trace back to a real requirement or architectural dependency.

============================================================
PART 44 — MASTER DECISION TABLE
============================================================

Create a final table:

DECISION
OPTIONS CONSIDERED
EVIDENCE
SELECTED APPROACH
WHY
TRADE-OFF
CONFIDENCE
WHAT WOULD MAKE US REVISIT IT

This becomes extremely important for future development.

============================================================
PART 45 — FINAL VERDICT ON THE SOLUTION
============================================================

Do NOT simply say:

“This is an excellent idea.”

Instead answer:

1. What is the actual solution we should build?
2. What is the minimum scientifically meaningful version?
3. What data do we need?
4. What data can we actually access?
5. What model should we begin with?
6. What should be our baseline?
7. What is our real differentiator?
8. What is the biggest technical risk?
9. What is the biggest scientific risk?
10. What should we build first?
11. What should we postpone?
12. What would make this solution genuinely impressive?
13. What would make the solution scientifically weak?
14. What would make the SIH demo misleading?
15. What are the biggest unknowns we still need to resolve?

============================================================
FINAL DELIVERABLES
============================================================

Produce the following outputs.

------------------------------------------------------------
DELIVERABLE 1 — EXECUTIVE RESEARCH REPORT
------------------------------------------------------------

A complete research report containing:

1. Problem Understanding
2. Scientific Background
3. Nowcasting Fundamentals
4. Indian Atmospheric Data Landscape
5. Official Data Sources
6. Dataset Accessibility
7. Indian Existing Systems
8. Global Existing Systems
9. Academic State of the Art
10. Model Comparison
11. Data Fusion Strategy
12. User / Operational Analysis
13. Product Opportunity
14. Competitive Gap
15. USP Analysis
16. Proposed Solution
17. Technical Architecture
18. AI/ML Architecture
19. Validation
20. Risk / Alert Engine
21. Failure Handling
22. Feasibility
23. MVP
24. Development Roadmap
25. SIH Demonstration
26. Risks
27. Future Expansion

------------------------------------------------------------
DELIVERABLE 2 — DATA SOURCE MATRIX
------------------------------------------------------------

A highly detailed table containing every potentially relevant dataset.

------------------------------------------------------------
DELIVERABLE 3 — COMPETITOR / EXISTING SYSTEM MATRIX
------------------------------------------------------------

Indian + global + academic + commercial.

------------------------------------------------------------
DELIVERABLE 4 — MODEL DECISION MATRIX
------------------------------------------------------------

Compare realistic model approaches.

------------------------------------------------------------
DELIVERABLE 5 — USP MATRIX
------------------------------------------------------------

For every proposed USP:

EXISTING GAP
EVIDENCE
OUR RESPONSE
IMPLEMENTATION
DIFFICULTY
VALIDATION
DEMO VALUE
LONG-TERM VALUE

------------------------------------------------------------
DELIVERABLE 6 — MVP SPECIFICATION
------------------------------------------------------------

Exact MVP scope.

------------------------------------------------------------
DELIVERABLE 7 — PHASED DEVELOPMENT PLAN
------------------------------------------------------------

Dependency-aware development phases.

------------------------------------------------------------
DELIVERABLE 8 — EXPERIMENT PLAN
------------------------------------------------------------

Experiments required before claiming model effectiveness.

------------------------------------------------------------
DELIVERABLE 9 — ARCHITECTURE DOCUMENT
------------------------------------------------------------

Technical architecture + Mermaid diagrams.

------------------------------------------------------------
DELIVERABLE 10 — SIH DEMO PLAN
------------------------------------------------------------

Exactly what we should demonstrate.

------------------------------------------------------------
DELIVERABLE 11 — “DO NOT BUILD” LIST
------------------------------------------------------------

Features / approaches that should be avoided.

------------------------------------------------------------
DELIVERABLE 12 — RESEARCH BACKLOG
------------------------------------------------------------

Remaining questions that need verification.

============================================================
FINAL 10-SECTION SUMMARY
============================================================

At the very end provide exactly these sections:

1. THE PROBLEM IN ONE PARAGRAPH

2. THE SOLUTION IN ONE PARAGRAPH

3. WHAT WE SHOULD ACTUALLY BUILD

4. WHAT DATA WE CAN ACTUALLY USE

5. WHAT MODEL WE SHOULD START WITH

6. WHAT EXISTING SYSTEMS ALREADY DO

7. WHERE THE REAL GAP IS

8. OUR DEFENSIBLE DIFFERENTIATION

9. THE FIRST WORKING VERTICAL SLICE

10. THE NEXT 7 DAYS OF DEVELOPMENT

============================================================
MASTER.md REQUIREMENT
============================================================

After completing the research, create a proposed MASTER.md structure.

MASTER.md will become the project’s source of truth.

It must eventually contain:

- problem statement
- scientific definition
- verified facts
- data sources
- data-access status
- architecture
- model strategy
- validation standards
- UX/product definition
- USP
- MVP
- development phases
- decisions
- unresolved questions
- known limitations
- risks
- current implementation state

Use these labels throughout:

[VERIFIED]
[RESEARCH]
[DECISION]
[PROPOSED]
[EXPERIMENTAL]
[BLOCKED]
[UNKNOWN]

Future agents/developers should be able to read MASTER.md and understand:

WHAT we are building
WHY we are building it
HOW it works
WHAT evidence supports it
WHAT remains uncertain

============================================================
CRITICAL THINKING REQUIREMENT
============================================================

Challenge us.

If our assumed approach is scientifically weak, say so.

If the PS sounds like it expects functionality that is impossible with public data, say so.

If a proposed USP already exists elsewhere, say so.

If the best solution requires institutional access that we cannot obtain, say so.

If a simpler baseline can outperform a complex neural network under our data constraints, say so.

If a flashy AI feature has little scientific value, reject it.

If a feature is useful but belongs in a later phase, say so.

Do not tell us what we want to hear.

We want the most evidence-backed path.

============================================================
MOST IMPORTANT PRINCIPLE
============================================================

DO NOT OPTIMIZE FOR:

“a cool-looking AI weather website.”

OPTIMIZE FOR:

“a scientifically grounded, data-aware, operationally meaningful, technically feasible software system for thunderstorm and lightning nowcasting that can be convincingly demonstrated at SIH.”

The final recommendation should survive questioning from:

- a meteorologist
- an ML researcher
- a government technology expert
- a disaster-management expert
- a software architect
- an SIH judge

The report should therefore continuously answer:

WHAT?
WHY?
HOW?
BASED ON WHAT EVIDENCE?
HOW DO WE VALIDATE IT?
WHAT CAN WE ACTUALLY BUILD?