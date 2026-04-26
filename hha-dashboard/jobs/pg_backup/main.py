"""pg_backup cron entry point.

Schedule: `0 3 * * *` UTC (03:00 daily). Wires into the Container Apps Job
provisioned in `infra/modules/containerjobs.bicep`. The image bakes
postgresql-client-16 so `pg_dump` is on PATH inside the running container.

Local dev / one-off:
    cd hha-dashboard/api
    uv run python -m jobs.pg_backup.main

Required env (the Container Apps Job sets these via app_settings):
    DATABASE_URL_SYNC       — psycopg connection string (NOT the asyncpg one)
    AZURE_STORAGE_*         — already set for the API; same Storage Account
    ENV                     — dev / prod (used in the filename)

Required Storage RBAC:
    The job's managed identity needs **Storage Blob Data Contributor** on
    the Storage Account (or scoped just to the backups container). Wired
    via `rbac.bicep` in a follow-up — until then, dev runs use a connection
    string from settings.azure_storage_connection_string.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent.parent / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.services.audit import set_current_upn  # noqa: E402
from app.settings import settings  # noqa: E402

from .backup import BackupError, run_backup  # noqa: E402

SERVICE_UPN = "pg-backup@hhamedicine.com"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("jobs.pg_backup")


async def run() -> int:
    """Returns exit code (0 success, non-zero error)."""
    if not settings.database_url_sync:
        log.error(
            "DATABASE_URL_SYNC not configured — cannot run pg_dump. "
            "Set the env var (or settings.database_url_sync) and re-run.",
        )
        return 64  # EX_USAGE

    set_current_upn(SERVICE_UPN)

    try:
        result = await run_backup(
            env_name=settings.env,
            database_url=settings.database_url_sync,
        )
    except BackupError as e:
        log.error("pg_backup.failed: %s", e)
        return 1

    log.info(
        "pg_backup.success blob=%s size_bytes=%s",
        result["blob_name"],
        result["dump_size_bytes"],
    )
    return 0


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
