FROM python:3.12-slim

WORKDIR /app

# System deps kept minimal: everything runs on wheels (no compiled GDAL/eccodes yet).
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY configs ./configs
COPY web ./web
COPY scripts ./scripts

# Data/models/store are mounted as volumes so artifacts survive container restarts.
ENV VAJRA_PATHS__DATA_ROOT=/data \
    VAJRA_PATHS__MODELS_DIR=/data/models \
    VAJRA_PATHS__STORE_DIR=/data/store

EXPOSE 8000
CMD ["uvicorn", "vajra.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
