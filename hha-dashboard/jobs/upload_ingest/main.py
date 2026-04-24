"""Upload ingest cron job — runs every 15 minutes in prod, or manually in dev.

Local dev invocation (from hha-dashboard/api/):
    uv run python -m jobs.upload_ingest.main

Prod: Azure Container Apps Job with cron schedule `*/15 * * * *`.

Flow:
  1. Claim up to 50 rows from uploads.upload_log where status='uploaded'
     via SELECT ... FOR UPDATE SKIP LOCKED (concurrent-safe)
  2. For each row: download the blob → route by file_type → run extractor
     → commit entries/facts rows (audit fires automatically)
     → update upload_log.status + blob metadata
  3. On failure: increment retry_count; if <3, requeue; if ≥3, mark error
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add api/ to sys.path so `from app...` works when running from hha-dashboard/
API_DIR = Path(__file__).resolve().parent.parent.parent / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.core.logging import configure_logging  # noqa: E402
from app.models.uploads import UploadLog  # noqa: E402
from app.services import audit as audit_service  # noqa: E402
from app.services import blob as blob_service  # noqa: E402
from app.settings import settings  # noqa: E402

from .extractors import ROUTES  # noqa: E402

log = logging.getLogger(__name__)

SERVICE_UPN = "upload-ingest@hhamedicine.com"
BATCH_SIZE = 50
MAX_RETRIES = 3


async def _claim_work(db: AsyncSession) -> list[UploadLog]:
    """Claim up to BATCH_SIZE rows via FOR UPDATE SKIP LOCKED.

    Concurrent safety: if two job instances run simultaneously, they'll
    skip each other's locked rows.
    """
    stmt = (
        select(UploadLog)
        .where(UploadLog.status == "uploaded", UploadLog.retry_count < MAX_RETRIES)
        .order_by(UploadLog.uploaded_at)
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    rows = list((await db.execute(stmt)).scalars().all())

    now = datetime.now(timezone.utc)
    for r in rows:
        r.status = "processing"
        r.processing_started_at = now
    await db.commit()
    return rows


async def _process_one(db: AsyncSession, row: UploadLog) -> None:
    """Download blob → route → save → mark processed."""
    blob_name = row.blob_name
    log.info("ingest.processing id=%d blob=%s type=%s", row.id, blob_name, row.file_type)

    try:
        data = await blob_service.download_bytes(
            settings.azure_storage_uploads_container, blob_name
        )
        # Verify integrity
        sha = hashlib.sha256(data).hexdigest()
        if sha != row.sha256:
            raise ValueError(f"SHA-256 mismatch (blob vs upload_log): {sha} != {row.sha256}")

        extractor = ROUTES.get(row.file_type)
        if extractor is None:
            raise ValueError(f"Unknown file_type '{row.file_type}' — no extractor registered")

        result = await extractor(data, row, db)

        row.status = "processed"
        row.processing_finished_at = datetime.now(timezone.utc)
        row.rows_written = result.rows_written
        row.error_message = "\n".join(result.warnings) if result.warnings else None
        await db.commit()

        # Update blob metadata (tag as processed → lifecycle policy deletes in 7d)
        await blob_service.set_metadata(
            settings.azure_storage_uploads_container,
            blob_name,
            {
                "type": row.file_type,
                "uploaded_by_upn": row.uploaded_by_upn,
                "original_filename": row.original_filename,
                "status": "processed",
                "sha256": row.sha256,
                "processed_at": row.processing_finished_at.isoformat(),
                "rows_written": str(result.rows_written),
            },
        )
        log.info(
            "ingest.ok id=%d rows=%d warnings=%d",
            row.id,
            result.rows_written,
            len(result.warnings),
        )

    except Exception as e:
        log.exception("ingest.fail id=%d blob=%s", row.id, blob_name)
        # Rollback any partial entries writes from the failed extractor
        await db.rollback()
        # Refetch to avoid stale-row issues
        row = (await db.execute(select(UploadLog).where(UploadLog.id == row.id))).scalar_one()
        row.retry_count += 1
        row.error_message = f"{type(e).__name__}: {e!s}"[:500]
        row.processing_finished_at = datetime.now(timezone.utc)
        row.status = "error" if row.retry_count >= MAX_RETRIES else "uploaded"
        await db.commit()


async def main() -> None:
    configure_logging(settings.log_level)
    # Attach audit listener; set service UPN on contextvar for the whole job
    audit_service.install_audit_listener()
    audit_service.set_current_upn(SERVICE_UPN)

    log.info("upload_ingest.start")

    engine = create_async_engine(settings.database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with SessionLocal() as db:
            work = await _claim_work(db)
            if not work:
                log.info("upload_ingest.no_work")
                return
            log.info("upload_ingest.claimed count=%d", len(work))

            # Process each row in its own transaction so failures are isolated
            for row in work:
                async with SessionLocal() as row_db:
                    # Re-bind row into this session
                    fresh = (
                        await row_db.execute(select(UploadLog).where(UploadLog.id == row.id))
                    ).scalar_one()
                    await _process_one(row_db, fresh)

        log.info("upload_ingest.done")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
