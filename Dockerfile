# syntax=docker/dockerfile:1.4
# Project Vajra — Production Multi-Stage Containerization (SIH 2026 PS 26072)
# Multi-stage build with optimized wheel caching, GDAL/eccodes runtime support,
# non-root security isolation, and automatic GPU/CPU fallback.

# ============================================================================
# Stage 1: Build & Dependency Resolution
# ============================================================================
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install system build dependencies for geospatial extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    pkg-config \
    libgdal-dev \
    libeccodes-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install project dependencies
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir .

# ============================================================================
# Stage 2: Hardened Production Runtime
# ============================================================================
FROM python:3.12-slim-bookworm AS runner

LABEL org.opencontainers.image.title="Project Vajra" \
      org.opencontainers.image.description="Severe Weather Convective Intelligence & Lightning Nowcasting Platform" \
      org.opencontainers.image.version="1.0.0-sih2026" \
      org.opencontainers.image.authors="Team Antigravity (SIH 2026 PS 26072)" \
      org.opencontainers.image.licenses="Apache-2.0"

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    VAJRA_PATHS__DATA_ROOT=/data \
    VAJRA_PATHS__MODELS_DIR=/data/models \
    VAJRA_PATHS__STORE_DIR=/data/store

# Install runtime shared libraries and curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libgdal32 \
    libeccodes0 \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Create unprivileged service user and group
RUN groupadd -g 10001 vajra && \
    useradd -u 10001 -g vajra -s /bin/bash -m vajra && \
    mkdir -p /data/models /data/store /app && \
    chown -R vajra:vajra /data /app

# Copy application assets
COPY --chown=vajra:vajra configs/ ./configs/
COPY --chown=vajra:vajra web/ ./web/
COPY --chown=vajra:vajra scripts/ ./scripts/
COPY --chown=vajra:vajra data/admin/ /data/admin/
COPY --chown=vajra:vajra data/events/ /data/events/
COPY --chown=vajra:vajra src/ ./src/
COPY --chown=vajra:vajra pyproject.toml ./

# Switch to unprivileged runtime user
USER vajra

# Operational health probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

EXPOSE 8000

# Launch production server with Uvicorn
CMD ["uvicorn", "vajra.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--access-log"]
