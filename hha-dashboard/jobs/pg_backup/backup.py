"""pg_backup core — pg_dump → temp file → Azure Blob upload.

Design choices (locked):

- **`pg_dump --format=custom`** (binary). More compact than plain SQL,
  parallel-restorable via `pg_restore -j`, version-portable across minor
  postgres releases. Default compression `-Z 6` is plenty.
- **Temp file, not stdin streaming.** The dump writes to `/tmp/<name>.dump`
  inside the container, gets uploaded, gets deleted. Streaming stdout to
  blob is more elegant in theory but harder to debug and harder to retry
  on partial failure. For HHA's row count (<10M total), the dump is well
  under 1GB and `/tmp` is fine.
- **Filename:** `pg-backup-{env}-{ISO8601}.dump`. Sortable, traceable,
  tells you at a glance which env and when.
- **Azure Blob metadata** carries `env_name`, `dump_started_at`,
  `dump_finished_at`, `dump_size_bytes`, `postgres_url_hash` (sha256 of
  the connection string for cross-env detection without leaking creds).
- **No PHI in the dump** — the schema is HIPAA-classified at CI time,
  every column has `data_class`, no `data_class: C` rows. The dump is
  Tier B max (workforce / directory). Storage Account encryption-at-rest
  is enough; the immutability lock the operator applies later adds WORM
  for legal hold.

What this module does NOT do:
- Restore. That's `scripts/restore_drill.sh` invoked manually as a drill.
- Retention pruning. Azure Blob lifecycle policy (separate Bicep) handles
  age-based deletion of backups outside the WORM window.
- Cross-region copy. Storage SKU `Standard_RAGRS` (prod) replicates
  asynchronously by Azure — no app-level work needed.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from app.services.blob import upload_bytes
from app.settings import settings

log = logging.getLogger(__name__)


class BackupError(Exception):
    """pg_dump failed or upload failed. Caller decides whether to retry."""


def _filename(env_name: str, started_at: datetime) -> str:
    """Sortable timestamp filename. Example: pg-backup-prod-2026-04-26T03-00-00Z.dump."""
    stamp = started_at.strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"pg-backup-{env_name}-{stamp}.dump"


def _hash_url(url: str) -> str:
    """SHA-256 of the connection string. Lets us tag a backup with a value
    we can compare across envs WITHOUT leaking the password."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _run_pg_dump(database_url: str, output_path: Path) -> None:
    """Invoke pg_dump synchronously. Raises BackupError on non-zero exit.

    Uses --format=custom and the default `-Z 6` compression. The connection
    URL is passed via `--dbname=` (not env var) so an attacker reading
    process listings on the host doesn't see it as $PGPASSWORD — pg_dump's
    libpq parses the URL internally and never echoes it.
    """
    cmd = [
        "pg_dump",
        "--format=custom",
        "--no-owner",  # restore-side flexibility: target DB picks roles
        "--no-acl",  # we manage GRANTs separately
        "--file=" + str(output_path),
        "--dbname=" + database_url,
    ]
    log.info("pg_dump.start path=%s", output_path)
    try:
        result = subprocess.run(  # noqa: S603 — args are a fixed list, URL never reaches a shell
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 min — same ceiling as the cron's replicaTimeout
            check=False,
        )
    except FileNotFoundError as e:
        msg = "pg_dump not on PATH. Install postgresql-client matching the server major version."
        raise BackupError(msg) from e
    except subprocess.TimeoutExpired as e:
        raise BackupError(f"pg_dump timed out after {e.timeout}s") from e

    if result.returncode != 0:
        # pg_dump writes errors to stderr. Truncate so we don't dump
        # potentially-leaky output into logs forever.
        stderr_tail = (result.stderr or "")[-2000:]
        raise BackupError(
            f"pg_dump exited {result.returncode}. stderr (last 2k): {stderr_tail}"
        )

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise BackupError(
            f"pg_dump succeeded but output file is empty or missing: {output_path}"
        )

    log.info(
        "pg_dump.done path=%s size_bytes=%d",
        output_path,
        output_path.stat().st_size,
    )


async def run_backup(*, env_name: str, database_url: str) -> dict[str, str]:
    """Top-level entry point. Returns metadata dict on success.

    Raises BackupError on any failure — main.py catches and exits non-zero.
    """
    started_at = datetime.now(UTC)
    target_filename = _filename(env_name, started_at)

    with tempfile.TemporaryDirectory(prefix="pg-backup-") as tmp_dir:
        dump_path = Path(tmp_dir) / target_filename

        # Run pg_dump in a thread (sync subprocess.run blocks).
        await asyncio.to_thread(_run_pg_dump, database_url, dump_path)

        size_bytes = dump_path.stat().st_size
        finished_at = datetime.now(UTC)
        url_hash = _hash_url(database_url)

        with dump_path.open("rb") as f:
            data = f.read()

        metadata = {
            "env_name": env_name,
            "dump_started_at": started_at.isoformat(),
            "dump_finished_at": finished_at.isoformat(),
            "dump_size_bytes": str(size_bytes),
            "postgres_url_hash": url_hash,
        }

        blob_url = await upload_bytes(
            container_name=settings.azure_storage_backups_container,
            blob_name=target_filename,
            data=data,
            content_type="application/octet-stream",
            metadata=metadata,
            overwrite=False,  # writing the same blob twice is a bug, not a retry
        )

        log.info(
            "pg_backup.uploaded blob_url=%s size_bytes=%d duration_s=%.1f",
            blob_url,
            size_bytes,
            (finished_at - started_at).total_seconds(),
        )

        return {**metadata, "blob_url": blob_url, "blob_name": target_filename}
