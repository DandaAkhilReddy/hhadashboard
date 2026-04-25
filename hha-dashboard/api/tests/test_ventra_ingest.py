"""Ventra ingest service tests.

Mocks the AsyncSession so tests run without Postgres. Verifies:
  - well-formed rows produce one upsert each
  - AR-bucket-vs-total mismatch outside tolerance is skipped (warning recorded)
  - source_system + entered_by_upn are set correctly on every upsert
  - empty list is a no-op (no execute calls)
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from jobs.ventra_ingest.ingest import SERVICE_UPN, ingest_ventra_rows
from jobs.ventra_ingest.parser import VentraRow


def _row(
    *,
    year: int = 2026,
    month: int = 3,
    collections: str = "2280000",
    ar_total: str = "5600000",
    buckets: tuple[str, str, str, str, str] = (
        "1568000",
        "1120000",
        "784000",
        "728000",
        "1400000",
    ),
    ncr: str = "43",
    days_in_ar: str = "39.9",
) -> VentraRow:
    return VentraRow(
        year=year,
        month=month,
        collections_usd=Decimal(collections),
        ventra_fee_usd=Decimal(collections) * Decimal("0.05"),
        ar_total_usd=Decimal(ar_total),
        ar_0_30_usd=Decimal(buckets[0]),
        ar_31_60_usd=Decimal(buckets[1]),
        ar_61_90_usd=Decimal(buckets[2]),
        ar_91_120_usd=Decimal(buckets[3]),
        ar_over_120_usd=Decimal(buckets[4]),
        net_collection_rate_pct=Decimal(ncr),
        days_in_ar=Decimal(days_in_ar),
    )


def _mock_db() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_ingest_one_row_one_upsert() -> None:
    db = _mock_db()
    rows = [_row()]

    result = await ingest_ventra_rows(db, rows)

    assert result.rows_upserted == 1
    assert result.skipped == []
    # Exactly one execute (the upsert) + one commit
    assert db.execute.await_count == 1
    assert db.commit.await_count == 1


@pytest.mark.asyncio
async def test_ingest_multi_row_backfill() -> None:
    db = _mock_db()
    rows = [_row(month=1), _row(month=2), _row(month=3)]

    result = await ingest_ventra_rows(db, rows)

    assert result.rows_upserted == 3
    assert db.execute.await_count == 3


@pytest.mark.asyncio
async def test_ingest_skips_row_when_buckets_dont_sum() -> None:
    """AR buckets that don't add up to ar_total are flagged + skipped."""
    db = _mock_db()
    # ar_total claims 5.6M but buckets sum to 1M
    bad = _row(
        ar_total="5600000",
        buckets=("200000", "200000", "200000", "200000", "200000"),
    )

    result = await ingest_ventra_rows(db, [bad])

    assert result.rows_upserted == 0
    assert result.skipped is not None
    assert len(result.skipped) == 1
    assert "AR buckets sum" in result.skipped[0]
    # No upsert executed for the skipped row
    assert db.execute.await_count == 0


@pytest.mark.asyncio
async def test_ingest_within_tolerance_passes() -> None:
    """1% rounding tolerance — buckets sum to $5,599,500 vs total $5,600,000."""
    db = _mock_db()
    near_match = _row(
        ar_total="5600000",
        buckets=("1568000", "1119500", "784000", "728000", "1400000"),  # off by $500
    )

    result = await ingest_ventra_rows(db, [near_match])

    assert result.rows_upserted == 1
    assert result.skipped == []


@pytest.mark.asyncio
async def test_ingest_empty_list_is_noop() -> None:
    db = _mock_db()
    result = await ingest_ventra_rows(db, [])

    assert result.rows_upserted == 0
    assert db.execute.await_count == 0
    # commit still fires (cheap, idempotent on empty txn)
    assert db.commit.await_count == 1


@pytest.mark.asyncio
async def test_ingest_uses_service_upn_by_default() -> None:
    """All rows attributed to the service UPN — the audit log will show this."""
    assert SERVICE_UPN == "ventra-ingest@hhamedicine.com"

    db = _mock_db()
    await ingest_ventra_rows(db, [_row()])

    # Inspect the upsert statement passed to execute — confirm it carries the
    # right entered_by_upn. The compiled SQL is opaque to us here, but the
    # `values()` call captures it as a parameter dict.
    call = db.execute.await_args
    stmt = call.args[0]
    # SQLAlchemy Insert — pull out the Pythonic params
    compiled = stmt.compile()
    assert compiled.params["entered_by_upn"] == SERVICE_UPN
    assert compiled.params["source_system"] == "VENTRA_FL_ATHENA"
    assert compiled.params["state"] == "FL"


@pytest.mark.asyncio
async def test_ingest_custom_service_upn() -> None:
    db = _mock_db()
    await ingest_ventra_rows(db, [_row()], service_upn="custom@hha.com")

    compiled = db.execute.await_args.args[0].compile()
    assert compiled.params["entered_by_upn"] == "custom@hha.com"


@pytest.mark.asyncio
async def test_ingest_does_not_write_explicit_audit_row() -> None:
    """Audit rows are written by the Postgres trigger (migration 0007), not
    by the ingest service. The service must NOT call session.add() with an
    AuditLog instance — that would produce duplicate rows.
    """
    from app.models.audit import AuditLog

    db = _mock_db()
    rows = [_row()]

    await ingest_ventra_rows(db, rows)

    audit_adds = [
        c for c in db.add.call_args_list
        if c.args and isinstance(c.args[0], AuditLog)
    ]
    assert audit_adds == [], (
        "ingest_ventra_rows must not write AuditLog rows directly — the "
        "Postgres trigger handles audit. Found explicit add() calls."
    )
