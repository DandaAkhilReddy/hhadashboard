# pg_backup cron — Python 3.12 slim + uv + postgresql-client-16
#
# Built from the monorepo root. Azure Container Apps Job runs this on a
# 0 3 * * * UTC schedule.
#
# Why postgresql-client-16: the Bicep deploys Postgres Flex Server v16.
# pg_dump's wire protocol works backward but server-feature compat works
# forward — using the matching major version avoids "unrecognized parameter"
# warnings on dumps from newer servers.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1

# Install postgresql-client-16. The Debian Bookworm default repo ships v15;
# add the PostgreSQL Apt repo to get 16.
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg lsb-release && \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends postgresql-client-16 && \
    apt-get purge -y curl gnupg lsb-release && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY api/pyproject.toml api/pyproject.toml
COPY api/app api/app
COPY jobs jobs

RUN cd api && uv sync --no-dev --frozen || uv sync --no-dev

WORKDIR /app
ENV PYTHONPATH=/app/api
CMD ["python", "-m", "jobs.pg_backup.main"]
