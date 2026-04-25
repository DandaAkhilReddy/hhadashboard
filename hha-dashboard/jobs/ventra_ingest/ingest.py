"""Ventra FL ingestion service — upsert parsed rows to entries.monthly_finance_manual.

Idempotent: re-running for the same (year, month, FL) overwrites in place.
This is the same upsert pattern Sandy's manual form uses; the only differences
are `source_system='VENTRA_FL_ATHENA'` and `entered_by_upn` set to a service UPN.

Audit log fires automatically via the SQLAlchemy event listener — every Ventra
ingest run produces one audit row per month it touched.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entries_finance import MonthlyFinanceManual

from .parser import VentraRow

log = logging.getLogger(__name__)

# The "user" attributed to all Ventra ingestion. The audit row carries this
# UPN so an exec auditing the log can see "this row came from the cron, not
# Sandy." Keep stable — searched in audit reports.
SERVICE_UPN = "ventra-ingest@hhamedicine.com"
SOURCE_SYSTEM = "VENTRA_FL_ATHENA"
STATE = "FL"  # Ventra only covers FL per the FL-only scope decision


@dataclass
class IngestResult:
    rows_upserted: int = 0
    skipped: list[str] | None = None  # human-readable reasons for skipped rows


async def ingest_ventra_rows(
    db: AsyncSession,
    rows: list[VentraRow],
    *,
    service_upn: str = SERVICE_UPN,
) -> IngestResult:
    """Upsert each VentraRow into entries.monthly_finance_manual."""
    skipped: list[str] = []
    upserted = 0

    for r in rows:
        period_first = date(r.year, r.month, 1)
        # Sanity check — refuse to ingest rows where the AR buckets clearly
        # don't add up to the total. Tolerance: 1% of total OR $100, whichever
        # is larger (handles rounding).
        bucket_sum = (
            r.ar_0_30_usd
            + r.ar_31_60_usd
            + r.ar_61_90_usd
            + r.ar_91_120_usd
            + r.ar_over_120_usd
        )
        tolerance = max(r.ar_total_usd / 100, 100)
        if abs(bucket_sum - r.ar_total_usd) > tolerance:
            skipped.append(
                f"{r.year}-{r.month:02d}: AR buckets sum ({bucket_sum}) "
                f"≠ ar_total ({r.ar_total_usd}) — outside tolerance"
            )
            continue

        stmt = (
            pg_insert(MonthlyFinanceManual)
            .values(
                year=r.year,
                month=r.month,
                period_first=period_first,
                state=STATE,
                collections_usd=r.collections_usd,
                ventra_fee_usd=r.ventra_fee_usd,
                ar_total_usd=r.ar_total_usd,
                ar_0_30_usd=r.ar_0_30_usd,
                ar_31_60_usd=r.ar_31_60_usd,
                ar_61_90_usd=r.ar_61_90_usd,
                ar_91_120_usd=r.ar_91_120_usd,
                ar_over_120_usd=r.ar_over_120_usd,
                net_collection_rate_pct=r.net_collection_rate_pct,
                days_in_ar=r.days_in_ar,
                source_system=SOURCE_SYSTEM,
                entered_by_upn=service_upn,
                notes=None,
            )
            .on_conflict_do_update(
                index_elements=["year", "month", "state"],
                set_={
                    "collections_usd": r.collections_usd,
                    "ventra_fee_usd": r.ventra_fee_usd,
                    "ar_total_usd": r.ar_total_usd,
                    "ar_0_30_usd": r.ar_0_30_usd,
                    "ar_31_60_usd": r.ar_31_60_usd,
                    "ar_61_90_usd": r.ar_61_90_usd,
                    "ar_91_120_usd": r.ar_91_120_usd,
                    "ar_over_120_usd": r.ar_over_120_usd,
                    "net_collection_rate_pct": r.net_collection_rate_pct,
                    "days_in_ar": r.days_in_ar,
                    "source_system": SOURCE_SYSTEM,
                    "entered_by_upn": service_upn,
                    "updated_at": datetime.now(UTC),
                },
            )
        )
        await db.execute(stmt)
        # Audit row is written by the Postgres trigger (migration 0007) —
        # it reads `audit.upn` from the session GUC and emits one INSERT or
        # UPDATE row per touched table mutation. The caller is responsible
        # for setting the GUC before calling us; see jobs/ventra_ingest/main.py.
        upserted += 1

    await db.commit()
    log.info(
        "ventra_ingest.ok upserted=%d skipped=%d", upserted, len(skipped)
    )
    return IngestResult(rows_upserted=upserted, skipped=skipped)
