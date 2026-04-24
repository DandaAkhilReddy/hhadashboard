"""Census PDF extractor — real implementation.

Takes PDF bytes, runs Azure Document Intelligence, fuzzy-matches rows to
site names, upserts entries.daily_entries (one per site per date).

Per ADR-001:
- PDF bytes may contain patient names / MRNs (Tier C). Read here, discarded
  immediately after DI returns structured data.
- Only aggregates land in Postgres: (site_id, entry_date, census).
- Audit log fires automatically on the INSERT/UPDATE via the event listener.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entries import DailyEntry
from app.models.masters import Site
from app.models.uploads import UploadLog
from app.services.pdf_extract import extract_census_from_pdf

log = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    rows_written: int = 0
    warnings: list[str] = field(default_factory=list)


async def extract_census_pdf(
    pdf_bytes: bytes, upload_row: UploadLog, db: AsyncSession
) -> ExtractionResult:
    # Load site roster once per job invocation
    site_rows = (await db.execute(select(Site))).scalars().all()
    sites_by_name = {s.name: s.id for s in site_rows}
    known_names = list(sites_by_name.keys())

    di_result = await extract_census_from_pdf(pdf_bytes, known_names)

    if not di_result.matches:
        return ExtractionResult(
            rows_written=0,
            warnings=[
                "No site/census matches found.",
                *di_result.warnings,
            ],
        )

    # Use the PDF's upload date as the entry date — matches user intent
    # ("today's census as of upload time"). Future enhancement: parse date
    # from PDF header.
    entry_date = upload_row.uploaded_at.date() if upload_row.uploaded_at else datetime.now(timezone.utc).date()

    rows_written = 0
    for match in di_result.matches:
        site_id = sites_by_name.get(match.site_name)
        if site_id is None:
            continue
        stmt = (
            pg_insert(DailyEntry)
            .values(
                site_id=site_id,
                entry_date=entry_date,
                census=match.census,
                open_shifts=0,  # not extracted from census PDFs
                entered_by_upn=upload_row.uploaded_by_upn,
                source="pdf_extract",
                pdf_sha256=di_result.pdf_sha256,
            )
            .on_conflict_do_update(
                index_elements=["site_id", "entry_date"],
                set_=dict(
                    census=match.census,
                    source="pdf_extract",
                    pdf_sha256=di_result.pdf_sha256,
                    entered_by_upn=upload_row.uploaded_by_upn,
                    updated_at=datetime.now(timezone.utc),
                ),
            )
        )
        await db.execute(stmt)
        rows_written += 1

    log.info(
        "extract_census_pdf.ok blob=%s matched=%d unmatched_rows=%d",
        upload_row.blob_name,
        rows_written,
        len(di_result.unmatched_rows),
    )

    return ExtractionResult(
        rows_written=rows_written,
        warnings=di_result.warnings,
    )
