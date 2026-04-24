# Upload ingest cron job — Python 3.12 slim + uv
# Built from the monorepo root. Azure Container Apps Job runs this on a */15 cron.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy only what we need (api/ + jobs/)
COPY api/pyproject.toml api/pyproject.toml
COPY api/app api/app
COPY jobs jobs

# Install deps into system python (smaller image, no venv needed)
RUN cd api && uv sync --no-dev --frozen || uv sync --no-dev

# Entrypoint: run the job once and exit (Container Apps Jobs cron re-invokes)
WORKDIR /app
ENV PYTHONPATH=/app/api
CMD ["python", "-m", "jobs.upload_ingest.main"]
