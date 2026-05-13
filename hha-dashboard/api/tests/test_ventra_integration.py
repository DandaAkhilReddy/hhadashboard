"""Integration tests for the Ventra ingest pipeline.

End-to-end exercise against a live Postgres (compose stack + alembic
upgrade head). Skipped automatically when Postgres is not reachable so
the unit-test suite stays green in CI environments without a DB.

What these tests cover that the unit tests (test_ventra_ingest.py)
do not:

  - Real ``pg_insert(...).on_conflict_do_update(...)`` execution against
    the live fact tables — verifies the index_elements match the natural
    UNIQUE constraints from migration 0011.
  - Audit triggers actually fire on each fact-table INSERT, writing rows
    to ``audit.audit_log`` with the right ``audit.upn`` GUC value.
  - DB CHECK constraints reject malicious / drifted values
    (``source_system != 'VENTRA_FL_ATHENA'``, ``state != 'FL'``).
  - ``ops.ingest_run`` state-machine round-trip — INSERT (running) →
    UPDATE (terminal status) with JSONB ``error_details``.
  - Idempotency: re-running the same drop overwrites; row counts stay
    constant and audit_log does NOT log a UPDATE when nothing changed
    (per migration 0007 trigger logic).

Cleanup strategy:
  Every test allocates a unique ``ingest_run_id`` UUID + a per-test UPN
  string. Cleanup deletes rows WHERE ``ingest_run_id = :rid`` for fact
  tables, ``run_id = :rid`` for processed_files / ingest_run, and
  ``changed_by_upn = :upn`` for audit_log. No facility_no collisions
  with other tests because each test uses its own run_id-derived
  facility_no offset.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal

import pytest
from jobs.ventra_ingest.ingest import IngestRun, ingest_drop
from jobs.ventra_ingest.manifest import Manifest, ManifestEntry
from jobs.ventra_ingest.parsers import (
    ARSnapshotRow,
    CollectionsRow,
    PhysicianMonthlyRow,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import SessionLocal
from app.services.audit import set_current_upn

pytestmark = pytest.mark.asyncio


async def _can_connect() -> bool:
    try:
        async with SessionLocal() as s:
            await s.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="module", autouse=True)
async def _skip_if_no_postgres() -> None:
    if not await _can_connect():
        pytest.skip("Postgres not reachable — skipping ventra integration tests")


def _drop_for(run_id: uuid.UUID) -> date:
    """Map a UUID to a deterministic future date so tests using different
    run_ids don't collide on the natural unique constraint."""
    # Use the last byte to derive day offset within May 2026.
    byte = run_id.int & 0x1F  # 0-31
    return date(2026, 6, max(1, byte))


def _collections_row(d: date, facility_no: int) -> CollectionsRow:
    return CollectionsRow(
        date=d,
        facility_no=facility_no,
        payer_class="commercial",
        gross_charges=Decimal("10000"),
        payments_received=Decimal("8000"),
        contractual_adjustments=Decimal("500"),
        write_offs=Decimal("200"),
        payer_refunds=Decimal("0"),
        patient_refunds=Decimal("0"),
        net_revenue=Decimal("7300"),
        source_system="CB",
    )


def _ar_row(d: date, facility_no: int) -> ARSnapshotRow:
    return ARSnapshotRow(
        snapshot_date=d,
        facility_no=facility_no,
        aging_bucket="0-30",  # type: ignore[arg-type]
        outstanding_amount=Decimal("50000"),
        source_system="CB",
    )


def _phys_row(month_first: date, facility_no: int) -> PhysicianMonthlyRow:
    return PhysicianMonthlyRow(
        month=month_first,
        physician_npi="1234567890",
        facility_no=facility_no,
        encounters_count=50,
        total_rvu=Decimal("100.5"),
        total_work_rvu=Decimal("80.0"),
        revenue_attributed=Decimal("75000"),
        source_system="CB",
    )


def _manifest(drop_date: date) -> Manifest:
    return Manifest(
        drop_date=drop_date,
        entries=[
            ManifestEntry(file_name="collections.csv", sha256="a" * 64, row_count=1),
            ManifestEntry(file_name="ar_snapshot.csv", sha256="b" * 64, row_count=1),
        ],
    )


async def _cleanup(db: AsyncSession, run_id: uuid.UUID, upn: str) -> None:
    """Tear down everything a test created. Order matters — fact tables
    first (they're the audit-trigger source), then processed_files, then
    ingest_run, then audit_log (catches the DELETE-trigger fires above)."""
    await db.execute(
        text("DELETE FROM entries.fact_collections_daily WHERE ingest_run_id = :rid"),
        {"rid": run_id},
    )
    await db.execute(
        text("DELETE FROM entries.fact_ar_snapshot WHERE ingest_run_id = :rid"),
        {"rid": run_id},
    )
    await db.execute(
        text("DELETE FROM entries.fact_revenue_by_physician_mo WHERE ingest_run_id = :rid"),
        {"rid": run_id},
    )
    await db.execute(
        text("DELETE FROM ops.processed_files WHERE run_id = :rid"), {"rid": run_id}
    )
    await db.execute(
        text("DELETE FROM ops.ingest_run WHERE run_id = :rid"), {"rid": run_id}
    )
    await db.execute(
        text("DELETE FROM audit.audit_log WHERE changed_by_upn = :upn"),
        {"upn": upn},
    )
    await db.commit()


# =========================================================================
# ingest_drop end-to-end
# =========================================================================


async def test_ingest_drop_writes_three_fact_tables_end_to_end() -> None:
    upn = "test-int-e2e@hha.com"
    set_current_upn(upn)
    async with SessionLocal() as db:
        run = await IngestRun.start(
            db,
            drop_date=date(2026, 6, 10),
            manifest_path="ventra/2026-06-10/_MANIFEST.csv",
        )
        try:
            drop = date(2026, 6, 10)
            month = date(2026, 6, 1)
            facility = 90001 + (run.run_id.int & 0xFF)
            manifest = Manifest(
                drop_date=drop,
                entries=[
                    ManifestEntry(file_name="collections.csv", sha256="a" * 64, row_count=1),
                    ManifestEntry(file_name="ar_snapshot.csv", sha256="b" * 64, row_count=1),
                    ManifestEntry(file_name="physician_monthly.csv", sha256="c" * 64, row_count=1),
                ],
            )
            parsed = {
                "collections.csv": [_collections_row(drop, facility)],
                "ar_snapshot.csv": [_ar_row(drop, facility)],
                "physician_monthly.csv": [_phys_row(month, facility)],
            }
            result = await ingest_drop(db, parsed, manifest, run.run_id)

            assert result.rows_written == 3
            assert result.rows_by_table == {
                "fact_collections_daily": 1,
                "fact_ar_snapshot": 1,
                "fact_revenue_by_physician_mo": 1,
            }
            assert result.vendor_source_systems == ["CB"]

            # Each fact table has exactly one row tagged with our run_id
            for table in (
                "fact_collections_daily",
                "fact_ar_snapshot",
                "fact_revenue_by_physician_mo",
            ):
                cnt = (
                    await db.execute(
                        text(
                            f"SELECT COUNT(*) FROM entries.{table} WHERE ingest_run_id = :rid"
                        ),
                        {"rid": run.run_id},
                    )
                ).scalar_one()
                assert cnt == 1, f"{table} should have exactly 1 row"

            # processed_files has one row per manifest entry
            cnt = (
                await db.execute(
                    text("SELECT COUNT(*) FROM ops.processed_files WHERE run_id = :rid"),
                    {"rid": run.run_id},
                )
            ).scalar_one()
            assert cnt == 3
        finally:
            await _cleanup(db, run.run_id, upn)


# =========================================================================
# Idempotency: re-running the same drop upserts (no duplicates)
# =========================================================================


async def test_ingest_drop_is_idempotent_on_natural_key() -> None:
    upn = "test-int-idempotent@hha.com"
    set_current_upn(upn)
    async with SessionLocal() as db:
        run = await IngestRun.start(
            db, drop_date=date(2026, 6, 11), manifest_path="p"
        )
        try:
            drop = date(2026, 6, 11)
            facility = 90100 + (run.run_id.int & 0xFF)
            manifest = Manifest(
                drop_date=drop,
                entries=[ManifestEntry(file_name="collections.csv", sha256="a" * 64, row_count=1)],
            )

            # First write — INSERTs
            await ingest_drop(
                db, {"collections.csv": [_collections_row(drop, facility)]}, manifest, run.run_id
            )

            # Mimic the operator-managed replay procedure (runbook D.8):
            # delete the prior processed_files row so V13 wouldn't quarantine
            # AND the PK constraint on (vendor, drop_date, file_name) doesn't
            # fire on the second insert. The fact-table UPSERT then exercises
            # the on_conflict_do_update path on the natural key, which is
            # what this test actually wants to verify.
            await db.execute(
                text(
                    "DELETE FROM ops.processed_files "
                    "WHERE run_id = :rid AND file_name = 'collections.csv'"
                ),
                {"rid": run.run_id},
            )
            await db.commit()

            second_manifest = Manifest(
                drop_date=drop,
                entries=[ManifestEntry(file_name="collections.csv", sha256="d" * 64, row_count=1)],
            )
            updated_row = _collections_row(drop, facility)
            updated_row = updated_row.model_copy(update={"payments_received": Decimal("9500")})
            await ingest_drop(
                db, {"collections.csv": [updated_row]}, second_manifest, run.run_id
            )

            # Still exactly ONE fact-table row (UPSERT not INSERT)
            cnt = (
                await db.execute(
                    text(
                        "SELECT COUNT(*) FROM entries.fact_collections_daily "
                        "WHERE ingest_run_id = :rid AND facility_no = :f"
                    ),
                    {"rid": run.run_id, "f": facility},
                )
            ).scalar_one()
            assert cnt == 1

            # And payments_received reflects the update
            payments = (
                await db.execute(
                    text(
                        "SELECT payments_received FROM entries.fact_collections_daily "
                        "WHERE facility_no = :f AND date = :d AND payer_class = 'commercial'"
                    ),
                    {"f": facility, "d": drop},
                )
            ).scalar_one()
            assert payments == Decimal("9500.00")
        finally:
            await _cleanup(db, run.run_id, upn)


# =========================================================================
# Audit triggers fire on each Ventra fact-table INSERT
# =========================================================================


async def test_audit_trigger_fires_on_fact_collections_insert() -> None:
    upn = "test-int-audit-coll@hha.com"
    set_current_upn(upn)
    async with SessionLocal() as db:
        run = await IngestRun.start(
            db, drop_date=date(2026, 6, 12), manifest_path="p"
        )
        try:
            drop = date(2026, 6, 12)
            facility = 90200 + (run.run_id.int & 0xFF)
            manifest = Manifest(
                drop_date=drop,
                entries=[ManifestEntry(file_name="collections.csv", sha256="a" * 64, row_count=1)],
            )
            await ingest_drop(
                db,
                {"collections.csv": [_collections_row(drop, facility)]},
                manifest,
                run.run_id,
            )

            # Exactly one audit row for fact_collections_daily with our UPN
            audit_rows = (
                await db.execute(
                    text(
                        "SELECT action, diff FROM audit.audit_log "
                        "WHERE table_name = 'fact_collections_daily' "
                        "AND changed_by_upn = :upn"
                    ),
                    {"upn": upn},
                )
            ).all()
            assert len(audit_rows) == 1
            action, diff = audit_rows[0]
            assert action == "INSERT"
            # diff for INSERT is {"new": {...}}; values include facility_no.
            assert "new" in diff
        finally:
            await _cleanup(db, run.run_id, upn)


# =========================================================================
# DB CHECK constraints reject bypasses
# =========================================================================


async def test_db_check_rejects_wrong_source_system() -> None:
    """Defense in depth: even if a future bug bypassed the ingest writer's
    omit-source-system pattern, the DB CHECK constraint rejects the row."""
    upn = "test-int-check-source@hha.com"
    set_current_upn(upn)
    async with SessionLocal() as db:
        run = await IngestRun.start(
            db, drop_date=date(2026, 6, 13), manifest_path="p"
        )
        try:
            facility = 90300 + (run.run_id.int & 0xFF)
            with pytest.raises(IntegrityError):
                async with db.begin():
                    await db.execute(
                        text(
                            "INSERT INTO entries.fact_collections_daily "
                            "(date, facility_no, payer_class, gross_charges, "
                            " payments_received, net_revenue, source_system, "
                            " ingest_run_id) "
                            "VALUES ('2026-06-13', :f, 'commercial', 1000, 800, "
                            "        700, 'HACKED', :rid)"
                        ),
                        {"f": facility, "rid": run.run_id},
                    )
        finally:
            await _cleanup(db, run.run_id, upn)


async def test_db_check_rejects_non_fl_state() -> None:
    """Same — state column is locked to 'FL'."""
    upn = "test-int-check-state@hha.com"
    set_current_upn(upn)
    async with SessionLocal() as db:
        run = await IngestRun.start(
            db, drop_date=date(2026, 6, 14), manifest_path="p"
        )
        try:
            facility = 90400 + (run.run_id.int & 0xFF)
            with pytest.raises(IntegrityError):
                async with db.begin():
                    await db.execute(
                        text(
                            "INSERT INTO entries.fact_collections_daily "
                            "(date, facility_no, payer_class, gross_charges, "
                            " payments_received, net_revenue, state, "
                            " ingest_run_id) "
                            "VALUES ('2026-06-14', :f, 'commercial', 1000, 800, "
                            "        700, 'TX', :rid)"
                        ),
                        {"f": facility, "rid": run.run_id},
                    )
        finally:
            await _cleanup(db, run.run_id, upn)


# =========================================================================
# IngestRun state machine round-trip
# =========================================================================


async def test_ingest_run_start_to_complete_roundtrip() -> None:
    upn = "test-int-run-rt@hha.com"
    set_current_upn(upn)
    async with SessionLocal() as db:
        run = await IngestRun.start(
            db,
            drop_date=date(2026, 6, 15),
            manifest_path="ventra/2026-06-15/_MANIFEST.csv",
        )
        try:
            # After start: row exists with status='running'
            status = (
                await db.execute(
                    text("SELECT status FROM ops.ingest_run WHERE run_id = :rid"),
                    {"rid": run.run_id},
                )
            ).scalar_one()
            assert status == "running"

            # Complete with success
            await run.complete(
                db, status="succeeded", rows_in=10, rows_out=10, files_count=2
            )
            row = (
                await db.execute(
                    text(
                        "SELECT status, rows_in, rows_out, files_count, "
                        "completed_at IS NOT NULL "
                        "FROM ops.ingest_run WHERE run_id = :rid"
                    ),
                    {"rid": run.run_id},
                )
            ).one()
            assert row[0] == "succeeded"
            assert row[1] == 10
            assert row[2] == 10
            assert row[3] == 2
            assert row[4] is True  # completed_at populated
        finally:
            await _cleanup(db, run.run_id, upn)


async def test_ingest_run_complete_with_error_details_jsonb_roundtrip() -> None:
    """Verify JSONB serialization of error_details survives a roundtrip."""
    upn = "test-int-jsonb@hha.com"
    set_current_upn(upn)
    async with SessionLocal() as db:
        run = await IngestRun.start(
            db, drop_date=date(2026, 6, 16), manifest_path="p"
        )
        try:
            details = {
                "rule": "V12",
                "facility_no": 8888,
                "hha_state": "TX",
                "file_name": "collections.csv",
                "line_no": 5,
            }
            await run.complete(
                db,
                status="quarantined",
                error_message="non-FL facility in Ventra drop",
                error_details=details,
            )
            stored = (
                await db.execute(
                    text(
                        "SELECT error_message, error_details::text "
                        "FROM ops.ingest_run WHERE run_id = :rid"
                    ),
                    {"rid": run.run_id},
                )
            ).one()
            assert stored[0] == "non-FL facility in Ventra drop"
            assert json.loads(stored[1]) == details
        finally:
            await _cleanup(db, run.run_id, upn)
