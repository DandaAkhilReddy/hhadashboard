# Ventra ingest Container Apps Job — Python 3.12 slim + uv.
#
# Triggered by KEDA azure-queue scaler on q-ventra-manifests (see
# infra/modules/containerjobs.bicep). One replica per manifest, scale-to-zero
# when the queue is empty.
#
# Built from the monorepo root. Shares the api/pyproject.toml dependency
# closure (no separate jobs/ventra_ingest/pyproject.toml) — same pattern as
# jobs/upload_ingest/Dockerfile.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1

WORKDIR /app

RUN pip install --no-cache-dir uv

# Copy only what we need (api/ + jobs/)
COPY api/pyproject.toml api/pyproject.toml
COPY api/app api/app
COPY jobs jobs

# Install deps into system python (smaller image, no venv needed)
RUN cd api && uv sync --no-dev --frozen || uv sync --no-dev

WORKDIR /app
ENV PYTHONPATH=/app/api
CMD ["python", "-m", "jobs.ventra_ingest.main"]
