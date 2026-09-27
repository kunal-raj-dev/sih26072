# Production Packaging, Deployment & Operations Guide

**Project Vajra · SIH 2026 Problem Statement ID: 26072**
*AIML-based Nowcasting of Thunderstorm and Lightning using Atmospheric Observation*

---

## 1. Executive Summary

Project Vajra is packaged as a cloud-native, containerized microservice engineered for high-availability deployment in national weather centers (e.g., IMD HQ / Regional Meteorological Centres), State Disaster Management Authorities (SDMAs), and field command vehicles.

### Key Deployment Characteristics
- **Zero-Dependency Bootstrap**: Full operational pipeline boots in $< 3\text{ minutes}$ from cold repository clone.
- **Multi-Stage Hardened Docker**: Alpine/Debian-slim multi-stage build eliminating build-time compilers and reducing container footprint.
- **Unprivileged Non-Root Isolation**: Runs under dedicated service account `vajra:vajra` (`uid=10001`, `gid=10001`).
- **Hardware Agnostic**: Automatic NVIDIA CUDA GPU acceleration with instantaneous CPU fallback.
- **Persistent Volume Architecture**: Separates ephemeral execution from persistent spatial databases, cached satellite grids, and trained model weights.

---

## 2. System Hardware & Runtime Requirements

| Component | Minimum Specification (Edge / Field) | Recommended Specification (Operational Centre) |
|---|---|---|
| **CPU Architecture** | x86_64 or ARM64 (4 Cores, 2.4 GHz+) | x86_64 (8–16 Cores, 3.2 GHz+) |
| **System Memory** | 8 GB RAM | 16–32 GB RAM |
| **Disk Storage** | 20 GB SSD (High I/O throughput) | 50–100 GB NVMe SSD |
| **GPU Acceleration** | None (CPU inference supported) | 1x NVIDIA GPU (CUDA 12.x, 8+ GB VRAM, RTX 3080/4090, T4, A10) |
| **Operating System** | Linux (Ubuntu 22.04+ / RHEL 9+), macOS 13+, Windows 11 WSL2 | Linux (Ubuntu 22.04 LTS Server) |
| **Container Engine** | Docker Engine 24.0+ & Docker Compose v2.20+ | Docker Engine 26.0+ & NVIDIA Container Toolkit |

---

## 3. Production Container Architecture

The container build is governed by a multi-stage `Dockerfile`:

```
┌────────────────────────────────────────────────────────┐
│ STAGE 1: Builder Stage (python:3.11-slim-bookworm)      │
│ - Installs gcc, g++, build-essential, git              │
│ - Builds Python wheels into virtual environment        │
│ - Eliminates compilers from final artifact             │
└───────────────────────────┬────────────────────────────┘
                            │ (Copies clean virtualenv)
                            ▼
┌────────────────────────────────────────────────────────┐
│ STAGE 2: Hardened Runtime (python:3.11-slim-bookworm)  │
│ - Installs shared libraries: libgdal32, libeccodes0    │
│ - Creates unprivileged user vajra (UID 10001)          │
│ - Configures persistent volumes and /app permissions   │
│ - Exposes Port 8000 and curl /healthz healthcheck      │
└────────────────────────────────────────────────────────┘
```

---

## 4. One-Command Quickstart

### Option A: Docker Compose (Standard Production)

1. **Clone Repository & Configure Environment**:
   ```bash
   git clone https://github.com/kunal-raj-dev/sih26072.git
   cd sih26072
   cp .env.example .env
   # Edit .env with any required credentials (e.g. NASA Earthdata)
   ```

2. **Launch System**:
   ```bash
   docker compose up --build -d
   ```

3. **Verify Deployment Health**:
   ```bash
   docker compose ps
   curl -s http://localhost:8000/healthz | jq
   ```

4. **Access Web Console**:
   Open browser to `http://localhost:8000` to interact with the real-time MapLibre GIS dashboard.

---

### Option B: SIH Grand Finale Automated Bootstrap Script

For live competition juries and zero-configuration demonstrations, run the automated bootstrap script:

```bash
python scripts/sih_demo_bootstrap.py
```

This single command automatically:
1. Validates system dependencies and environment integrity.
2. Seeds local administrative boundaries and cached case-study benchmarks.
3. Pre-warms the Dual-Track ML models into memory.
4. Launches the high-performance FastAPI server in the background.
5. Launches an interactive keyboard presentation controller and opens the browser.

---

## 5. Environment Variables & Configuration Matrix

All configuration parameters can be supplied via environment variables or a `.env` file:

| Variable Name | Default Value | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Network binding interface for the FastAPI web server. |
| `PORT` | `8000` | Network port for HTTP REST API and WebSocket streaming. |
| `VAJRA_DATA_DIR` | `/app/data` (Docker) / `data` (Local) | Path to persistent storage containing boundaries, models, and cache. |
| `VAJRA_LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `VAJRA_DEVICE` | `auto` | Execution device for neural networks (`auto`, `cuda`, `cpu`). |
| `VAJRA_BASEMAPS__CARTO_KEY` | *(Empty)* | CARTO Basemaps API key for raster tiles (falls back to OSM if absent). |
| `EARTHDATA_USERNAME` | *(Optional)* | NASA Earthdata username for live IMERG precipitation downloads. |
| `EARTHDATA_PASSWORD` | *(Optional)* | NASA Earthdata password for live IMERG precipitation downloads. |
| `MOSDAC_USERNAME` | *(Optional)* | SAC ISRO MOSDAC credentials for live INSAT imagery queries. |
| `MOSDAC_PASSWORD` | *(Optional)* | SAC ISRO MOSDAC credentials for live INSAT imagery queries. |

---

## 6. Service Endpoints & Health Probes

| Endpoint | Protocol | Purpose | Expected Status |
|---|---|---|---|
| `/healthz` | HTTP GET | Kubernetes / Docker liveness and readiness probe. | `200 OK` `{"status": "healthy"}` |
| `/` | HTTP GET | Serves the MapLibre GL presentation GIS console. | `200 OK` (HTML) |
| `/docs` | HTTP GET | Interactive OpenAPI / Swagger developer documentation. | `200 OK` (HTML) |
| `/api/v1/pipeline/nowcast` | HTTP POST | Triggers execution of the real-time nowcasting cycle. | `200 OK` (JSON) |
| `/api/v1/alerts/feed.atom` | HTTP GET | Standard CAP 1.2 Atom syndication alert feed. | `200 OK` (XML) |
| `/api/v1/verify/scoreboard` | HTTP GET | Machine learning verification metrics vs. 5 baselines. | `200 OK` (JSON) |

---

## 7. Troubleshooting & Operational Runbook

### Issue: Container Exits Immediately with Permission Denied
- **Root Cause**: The volume mounted to `/app/data` is owned by `root` on the host machine.
- **Remedy**:
  ```bash
  sudo chown -R 10001:10001 ./data ./logs
  docker compose restart
  ```

### Issue: Port 8000 Already in Use
- **Root Cause**: Another service (or an orphaned local Python process) is listening on port 8000.
- **Remedy**:
  ```bash
  # Change port mapping in .env or run with custom port:
  PORT=8080 docker compose up -d
  ```

### Issue: GPU Not Detected Inside Container
- **Root Cause**: NVIDIA Container Toolkit is not configured on the Docker daemon.
- **Remedy**:
  1. Verify host GPU driver: `nvidia-smi`.
  2. Install nvidia-container-toolkit: `sudo apt-get install -y nvidia-container-toolkit`.
  3. Restart Docker daemon: `sudo systemctl restart docker`.
  4. Note: Vajra will gracefully fall back to CPU with zero pipeline failures if CUDA is unavailable.

### Issue: High Memory Usage Under Continuous Streaming
- **Root Cause**: Excessive in-memory forecast caching over hundreds of cycles.
- **Remedy**:
  The system includes an automatic LRU cache eviction policy. Run `scripts/burn_in_load_test.py` to verify memory stability (confirmed net growth $< 2\text{ MB}$ over 24 continuous cycles).
