# Daily credential expiry scan — Python 3.12 slim + uv
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY api/pyproject.toml api/pyproject.toml
COPY api/app api/app
COPY jobs jobs

RUN cd api && uv sync --no-dev --frozen || uv sync --no-dev

WORKDIR /app
ENV PYTHONPATH=/app/api
CMD ["python", "-m", "jobs.cred_scan.main"]
