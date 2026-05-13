"""Cross-file validator tests for the Ventra ingest pipeline.

V6 and V9 cross-row are pure-Python and run unconditionally.
V12 and V13 require a live Postgres (uses the same skip-if-no-postgres
fixture as test_audit_triggers.py) — they exercise real SELECTs against
masters.sites and ops.processed_files.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date
from decimal import Decimal

import pytest
from jobs.ventra_ingest.exceptions import ADRViolation, ValidationError
from jobs.ventra_ingest.manifest import Manifest, ManifestEntry
from jobs.ventra_ingest.parsers import ARSnapshotRow, CollectionsRow
from jobs.ventra_ingest.validators import (
    DedupDecision,
    check_dedup,
    validate_ar_buckets_sum,
    validate_drop_consistency,
    validate_fl_only,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import SessionLocal

pytestmark = pytest.mark.asyncio

DROP = date(2026, 5, 15)


# =========================================================================
# V6 — validate_drop_consistency (pure Python)
# =========================================================================


def _collections_row(d: date, fac: int = 901) -> CollectionsRow:
    return CollectionsRow(
        date=d,
        facility_no=fac,
        payer_class="commercial",
        gross_charges=Decimal("1000"),
        payments_received=Decimal("800"),
        contractual_adjustments=Decimal("0"),
        write_offs=Decimal("0"),
        payer_refunds=Decimal("0"),
        patient_refunds=Decimal("0"),
        net_revenue=Decimal("800"),
        source_system="CB",
    )


def _ar_row(d: date, fac: int = 901, bucket: str = "0-30") -> ARSnapshotRow:
    return ARSnapshotRow(
        snapshot_date=d,
        facility_no=fac,
        aging_bucket=bucket,  # type: ignore[arg-type]
        outstanding_amount=Decimal("1000"),
        source_system="CB",
    )


async def test_v6_passes_when_dates_match() -> None:
    parsed = {
        "collections.csv": [_collections_row(DROP), _collections_row(DROP)],
        "ar_snapshot.csv": [_ar_row(DROP)],
    }
    validate_drop_consistency(parsed, DROP)  # no raise


async def test_v6_fails_on_collections_date_drift() -> None:
    parsed = {
        "collections.csv": [
            _collections_row(DROP),
            _collections_row(date(2026, 5, 14)),  # off by one
        ],
    }
    with pytest.raises(ValidationError) as exc:
        validate_drop_consistency(parsed, DROP)
    assert exc.value.rule == "V6"
    assert exc.value.details["line_no"] == 3
    assert exc.value.details["row_date"] == "2026-05-14"


async def test_v6_fails_on_ar_snapshot_date_drift() -> None:
    parsed = {"ar_snapshot.csv": [_ar_row(date(2026, 5, 16))]}
    with pytest.raises(ValidationError) as exc:
        validate_drop_consistency(parsed, DROP)
    assert exc.value.rule == "V6"
    assert exc.value.details["file_name"] == "ar_snapshot.csv"


async def test_v6_skips_physician_monthly_date_check() -> None:
    # physician_monthly.month is intentionally exempt — vendor may emit
    # prior-month or restated months on any drop_date.
    parsed: dict[str, list] = {}  # empty is fine
    validate_drop_consistency(parsed, DROP)  # no raise


# =========================================================================
# V9 cross-row — validate_ar_buckets_sum (pure Python)
# =========================================================================


async def test_v9_passes_on_unique_keys() -> None:
    rows = [
        _ar_row(DROP, fac=901, bucket="0-30"),
        _ar_row(DROP, fac=901, bucket="31-60"),
        _ar_row(DROP, fac=902, bucket="0-30"),
    ]
    validate_ar_buckets_sum(rows)  # no raise


async def test_v9_fails_on_duplicate_key() -> None:
    rows = [
        _ar_row(DROP, fac=901, bucket="0-30"),
        _ar_row(DROP, fac=901, bucket="0-30"),  # duplicate
    ]
    with pytest.raises(ValidationError) as exc:
        validate_ar_buckets_sum(rows)
    assert exc.value.rule == "V9"
    assert exc.value.details["facility_no"] == 901
    assert exc.value.details["aging_bucket"] == "0-30"


async def test_v9_no_op_on_empty_or_missing() -> None:
    validate_ar_buckets_sum(None)
    validate_ar_buckets_sum([])


# =========================================================================
# V12 + V8 — validate_fl_only (live Postgres)
# =========================================================================


async def _can_connect_to_postgres() -> bool:
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="module", autouse=True)
async def _skip_if_no_postgres() -> None:
    if not await _can_connect_to_postgres():
        pytest.skip("Postgres not reachable — skipping V12/V13 DB tests")


async def _seed_site(
    session: AsyncSession, name: str, state: str
) -> int:
    """Insert a masters.sites row; return the assigned id."""
    r = await session.execute(
        text(
            "INSERT INTO masters.sites (name, state, status) "
            "VALUES (:n, :s, 'ACTIVE') RETURNING id"
        ),
        {"n": name, "s": state},
    )
    sid = int(r.scalar_one())
    await session.commit()
    return sid


async def _cleanup_sites(session: AsyncSession, ids: list[int]) -> None:
    for sid in ids:
        await session.execute(
            text("DELETE FROM masters.sites WHERE id = :id"), {"id": sid}
        )
    await session.commit()


async def test_v12_passes_when_all_facilities_are_fl() -> None:
    async with SessionLocal() as session:
        fl_id = await _seed_site(session, "V12-Test-FL", "FL")
        try:
            parsed = {"collections.csv": [_collections_row(DROP, fac=fl_id)]}
            await validate_fl_only(session, parsed)  # no raise
        finally:
            await _cleanup_sites(session, [fl_id])


async def test_v12_raises_adr_violation_on_tx_facility() -> None:
    async with SessionLocal() as session:
        fl_id = await _seed_site(session, "V12-Test-FL-2", "FL")
        tx_id = await _seed_site(session, "V12-Test-TX", "TX")
        try:
            parsed = {
                "collections.csv": [
                    _collections_row(DROP, fac=fl_id),
                    _collections_row(DROP, fac=tx_id),  # TX in Ventra feed!
                ],
            }
            with pytest.raises(ADRViolation) as exc:
                await validate_fl_only(session, parsed)
            assert exc.value.rule == "V12"
            assert exc.value.details["facility_no"] == tx_id
            assert exc.value.details["hha_state"] == "TX"
            assert exc.value.details["file_name"] == "collections.csv"
        finally:
            await _cleanup_sites(session, [fl_id, tx_id])


async def test_v12_raises_v8_for_unknown_facility() -> None:
    async with SessionLocal() as session:
        fl_id = await _seed_site(session, "V12-Test-FL-3", "FL")
        try:
            parsed = {
                "collections.csv": [
                    _collections_row(DROP, fac=fl_id),
                    _collections_row(DROP, fac=999999),  # not in sites
                ],
            }
            with pytest.raises(ValidationError) as exc:
                await validate_fl_only(session, parsed)
            assert exc.value.rule == "V8"
            assert exc.value.details["facility_no"] == 999999
        finally:
            await _cleanup_sites(session, [fl_id])


# =========================================================================
# V13 — check_dedup (live Postgres)
# =========================================================================


def _manifest_for(drop_date: date, files: list[tuple[str, str, int]]) -> Manifest:
    """Build a Manifest from (file_name, sha256, row_count) tuples."""
    return Manifest(
        drop_date=drop_date,
        entries=[
            ManifestEntry(file_name=name, sha256=sha, row_count=rc)
            for name, sha, rc in files
        ],
    )


async def _seed_ingest_run(session: AsyncSession, drop_date: date) -> uuid.UUID:
    r = await session.execute(
        text(
            "INSERT INTO ops.ingest_run (vendor, drop_date, manifest_path, status) "
            "VALUES ('ventra', :dd, 'test/_MANIFEST.csv', 'succeeded') "
            "RETURNING run_id"
        ),
        {"dd": drop_date},
    )
    run_id = uuid.UUID(str(r.scalar_one()))
    await session.commit()
    return run_id


async def _seed_processed_file(
    session: AsyncSession,
    drop_date: date,
    file_name: str,
    sha256: str,
    row_count: int,
    run_id: uuid.UUID,
) -> None:
    await session.execute(
        text(
            "INSERT INTO ops.processed_files "
            "(vendor, drop_date, file_name, blob_path, sha256, row_count, run_id) "
            "VALUES ('ventra', :dd, :fn, :bp, :sha, :rc, :rid)"
        ),
        {
            "dd": drop_date,
            "fn": file_name,
            "bp": f"ventra/{drop_date.isoformat()}/{file_name}",
            "sha": sha256,
            "rc": row_count,
            "rid": run_id,
        },
    )
    await session.commit()


async def _cleanup_ingest_run(session: AsyncSession, run_id: uuid.UUID) -> None:
    await session.execute(
        text("DELETE FROM ops.processed_files WHERE run_id = :rid"), {"rid": run_id}
    )
    await session.execute(
        text("DELETE FROM ops.ingest_run WHERE run_id = :rid"), {"rid": run_id}
    )
    await session.commit()


async def test_v13_passes_on_fresh_drop() -> None:
    """No prior processed_files rows for this drop_date — every entry fresh."""
    drop = date(2026, 6, 1)
    sha_a = hashlib.sha256(b"fresh-a").hexdigest()
    sha_b = hashlib.sha256(b"fresh-b").hexdigest()
    manifest = _manifest_for(drop, [("collections.csv", sha_a, 10), ("ar_snapshot.csv", sha_b, 20)])

    async with SessionLocal() as session:
        decision = await check_dedup(session, manifest)
    assert isinstance(decision, DedupDecision)
    assert decision.skip_entirely is False
    assert decision.already_processed == []


async def test_v13_skip_entirely_on_identical_redelivery() -> None:
    drop = date(2026, 6, 2)
    sha_a = hashlib.sha256(b"redeliver-a").hexdigest()
    manifest = _manifest_for(drop, [("collections.csv", sha_a, 5)])

    async with SessionLocal() as session:
        run_id = await _seed_ingest_run(session, drop)
        await _seed_processed_file(session, drop, "collections.csv", sha_a, 5, run_id)
        try:
            decision = await check_dedup(session, manifest)
            assert decision.skip_entirely is True
            assert decision.already_processed == ["collections.csv"]
        finally:
            await _cleanup_ingest_run(session, run_id)


async def test_v13_quarantines_on_content_change() -> None:
    drop = date(2026, 6, 3)
    original_sha = hashlib.sha256(b"original").hexdigest()
    new_sha = hashlib.sha256(b"changed").hexdigest()
    manifest = _manifest_for(drop, [("collections.csv", new_sha, 5)])

    async with SessionLocal() as session:
        run_id = await _seed_ingest_run(session, drop)
        await _seed_processed_file(session, drop, "collections.csv", original_sha, 5, run_id)
        try:
            with pytest.raises(ValidationError) as exc:
                await check_dedup(session, manifest)
            assert exc.value.rule == "V13"
            conflicts = exc.value.details["conflicts"]
            assert len(conflicts) == 1
            assert conflicts[0]["file_name"] == "collections.csv"
            assert conflicts[0]["prior_sha256"] == original_sha
            assert conflicts[0]["new_sha256"] == new_sha
        finally:
            await _cleanup_ingest_run(session, run_id)


async def test_v13_partial_skip_does_not_skip_entirely() -> None:
    """One file already processed, one is new — main flow processes the drop."""
    drop = date(2026, 6, 4)
    sha_a = hashlib.sha256(b"existing").hexdigest()
    sha_b = hashlib.sha256(b"new").hexdigest()
    manifest = _manifest_for(
        drop,
        [("collections.csv", sha_a, 5), ("ar_snapshot.csv", sha_b, 10)],
    )

    async with SessionLocal() as session:
        run_id = await _seed_ingest_run(session, drop)
        await _seed_processed_file(session, drop, "collections.csv", sha_a, 5, run_id)
        try:
            decision = await check_dedup(session, manifest)
            assert decision.skip_entirely is False
            assert decision.already_processed == ["collections.csv"]
        finally:
            await _cleanup_ingest_run(session, run_id)
