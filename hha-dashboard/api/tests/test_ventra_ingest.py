"""Ingest writer + IngestRun state-machine tests.

Pure unit tests — no DB. AsyncMock session lets us inspect the exact
statements + parameters every `execute()` call receives without paying
the cost of an integration test (those exist for the validators in
test_ventra_validators.py).

Coverage:
  - IngestRun.start: INSERT into ops.ingest_run with correct params
  - IngestRun.complete: terminal-status validation + UPDATE shape
  - ingest_drop: per-file pg_insert.on_conflict_do_update + processed_files
  - ingest_drop: skips empty file sections (physician_monthly omitted)
  - ingest_drop: rolls back on mid-write IntegrityError
  - IngestResult.vendor_source_systems dedups across rows
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from jobs.ventra_ingest.ingest import (
    IngestResult,
    IngestRun,
    ingest_drop,
)
from jobs.ventra_ingest.manifest import Manifest, ManifestEntry
from jobs.ventra_ingest.parsers import (
    ARSnapshotRow,
    CollectionsRow,
    PhysicianMonthlyRow,
)


pytestmark = pytest.mark.asyncio


def _mock_session() -> MagicMock:
    """Build a session whose ``async with .begin()`` is a no-op context
    and whose ``execute`` / ``commit`` are async-mockable."""
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    begin_cm = MagicMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=begin_cm)

    return session


def _collections_row(facility_no: int = 901, tag: str = "CB") -> CollectionsRow:
    return CollectionsRow(
        date=date(2026, 5, 15),
        facility_no=facility_no,
        payer_class="commercial",
        gross_charges=Decimal("10000"),
        payments_received=Decimal("8000"),
        contractual_adjustments=Decimal("500"),
        write_offs=Decimal("200"),
        payer_refunds=Decimal("0"),
        patient_refunds=Decimal("0"),
        net_revenue=Decimal("7300"),
        source_system=tag,
    )


def _ar_row(bucket: str = "0-30", tag: str = "CB") -> ARSnapshotRow:
    return ARSnapshotRow(
        snapshot_date=date(2026, 5, 15),
        facility_no=901,
        aging_bucket=bucket,  # type: ignore[arg-type]
        outstanding_amount=Decimal("50000"),
        source_system=tag,
    )


def _phys_row(tag: str = "CB") -> PhysicianMonthlyRow:
    return PhysicianMonthlyRow(
        month=date(2026, 5, 1),
        physician_npi="1234567890",
        facility_no=901,
        encounters_count=50,
        total_rvu=Decimal("100.5"),
        total_work_rvu=Decimal("80.0"),
        revenue_attributed=Decimal("75000"),
        source_system=tag,
    )


def _manifest() -> Manifest:
    return Manifest(
        drop_date=date(2026, 5, 15),
        entries=[
            ManifestEntry(file_name="collections.csv", sha256="a" * 64, row_count=1),
            ManifestEntry(file_name="ar_snapshot.csv", sha256="b" * 64, row_count=1),
        ],
    )


# =========================================================================
# IngestRun.start / complete
# =========================================================================


async def test_ingest_run_start_inserts_with_running_status() -> None:
    db = _mock_session()
    run = await IngestRun.start(
        db, drop_date=date(2026, 5, 15), manifest_path="ventra/2026-05-15/_MANIFEST.csv"
    )

    assert isinstance(run.run_id, uuid.UUID)
    assert isinstance(run.correlation_id, uuid.UUID)
    assert run.drop_date == date(2026, 5, 15)
    assert run.manifest_path == "ventra/2026-05-15/_MANIFEST.csv"

    # One INSERT issued
    assert db.execute.await_count == 1
    sql_call, params_call = db.execute.await_args_list[0].args
    sql_text = str(sql_call)
    assert "INSERT INTO ops.ingest_run" in sql_text
    assert "status = :status" not in sql_text  # not an UPDATE
    assert params_call["vendor"] == "ventra"
    assert params_call["dd"] == date(2026, 5, 15)
    assert params_call["mp"] == "ventra/2026-05-15/_MANIFEST.csv"
    assert params_call["run_id"] == run.run_id
    assert params_call["cid"] == run.correlation_id

    db.commit.assert_awaited_once()


async def test_ingest_run_start_accepts_explicit_correlation_id() -> None:
    db = _mock_session()
    cid = uuid.uuid4()
    run = await IngestRun.start(
        db, drop_date=date(2026, 5, 15), manifest_path="p", correlation_id=cid
    )
    assert run.correlation_id == cid


@pytest.mark.parametrize("status", ["succeeded", "failed", "quarantined"])
async def test_ingest_run_complete_accepts_each_terminal_status(status: str) -> None:
    db = _mock_session()
    run = IngestRun(
        run_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        drop_date=date(2026, 5, 15),
        manifest_path="p",
    )
    await run.complete(db, status=status, rows_in=100, rows_out=98, files_count=2)

    sql_call, params_call = db.execute.await_args_list[0].args
    sql_text = str(sql_call)
    assert "UPDATE ops.ingest_run" in sql_text
    assert params_call["status"] == status
    assert params_call["rows_in"] == 100
    assert params_call["rows_out"] == 98
    assert params_call["files_count"] == 2
    assert params_call["run_id"] == run.run_id
    db.commit.assert_awaited_once()


async def test_ingest_run_complete_rejects_non_terminal_status() -> None:
    db = _mock_session()
    run = IngestRun(
        run_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        drop_date=date(2026, 5, 15),
        manifest_path="p",
    )
    with pytest.raises(ValueError, match="invalid terminal status"):
        await run.complete(db, status="running")
    db.execute.assert_not_awaited()


async def test_ingest_run_complete_serializes_error_details_to_json() -> None:
    db = _mock_session()
    run = IngestRun(
        run_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        drop_date=date(2026, 5, 15),
        manifest_path="p",
    )
    await run.complete(
        db, status="failed", error_message="boom",
        error_details={"rule": "V12", "facility_no": 999},
    )
    _, params_call = db.execute.await_args_list[0].args
    assert params_call["error_message"] == "boom"
    # JSON string, not dict — verified by parseability.
    import json
    parsed = json.loads(params_call["error_details"])
    assert parsed == {"rule": "V12", "facility_no": 999}


# =========================================================================
# ingest_drop
# =========================================================================


async def test_ingest_drop_writes_all_three_tables_plus_processed_files() -> None:
    db = _mock_session()
    parsed: dict[str, list] = {
        "collections.csv": [_collections_row()],
        "ar_snapshot.csv": [_ar_row()],
        "physician_monthly.csv": [_phys_row()],
    }
    manifest = Manifest(
        drop_date=date(2026, 5, 15),
        entries=[
            ManifestEntry(file_name="collections.csv", sha256="a" * 64, row_count=1),
            ManifestEntry(file_name="ar_snapshot.csv", sha256="b" * 64, row_count=1),
            ManifestEntry(file_name="physician_monthly.csv", sha256="c" * 64, row_count=1),
        ],
    )
    run_id = uuid.uuid4()

    result = await ingest_drop(db, parsed, manifest, run_id)

    # Single transaction
    db.begin.assert_called_once()

    # 3 fact-table upserts + 3 processed_files inserts = 6 executes
    assert db.execute.await_count == 6

    # rows_by_table is populated for all three
    assert result.rows_by_table == {
        "fact_collections_daily": 1,
        "fact_ar_snapshot": 1,
        "fact_revenue_by_physician_mo": 1,
    }
    assert result.rows_written == 3


async def test_ingest_drop_skips_empty_physician_monthly() -> None:
    """Most daily drops have no physician_monthly file — verify the writer
    does not error and does not issue an INSERT for the absent table."""
    db = _mock_session()
    parsed: dict[str, list] = {
        "collections.csv": [_collections_row()],
        "ar_snapshot.csv": [_ar_row()],
    }
    run_id = uuid.uuid4()

    result = await ingest_drop(db, parsed, _manifest(), run_id)

    # 2 fact-table upserts + 2 processed_files inserts = 4 executes
    assert db.execute.await_count == 4
    assert "fact_revenue_by_physician_mo" not in result.rows_by_table
    assert result.rows_written == 2


async def test_ingest_drop_aggregates_vendor_source_systems() -> None:
    db = _mock_session()
    parsed: dict[str, list] = {
        "collections.csv": [
            _collections_row(facility_no=901, tag="CB"),
            _collections_row(facility_no=902, tag="MGS"),
        ],
        "ar_snapshot.csv": [_ar_row(tag="CB"), _ar_row(bucket="31-60", tag="VSQL")],
    }
    run_id = uuid.uuid4()

    result = await ingest_drop(db, parsed, _manifest(), run_id)

    # Dedup + sort
    assert result.vendor_source_systems == ["CB", "MGS", "VSQL"]


async def test_ingest_drop_passes_run_id_in_collections_values() -> None:
    """Verify the run_id is stamped into the upsert values (so every row
    on the fact table traces back to its ops.ingest_run row)."""
    db = _mock_session()
    parsed: dict[str, list] = {
        "collections.csv": [_collections_row()],
    }
    run_id = uuid.uuid4()

    await ingest_drop(db, parsed, _manifest(), run_id)

    # First execute is the collections pg_insert
    stmt = db.execute.await_args_list[0].args[0]
    compiled_params = stmt.compile().params
    assert compiled_params["ingest_run_id_m0"] == run_id


async def test_ingest_drop_emits_processed_files_row_per_manifest_entry() -> None:
    db = _mock_session()
    parsed: dict[str, list] = {
        "collections.csv": [_collections_row()],
        "ar_snapshot.csv": [_ar_row()],
    }
    run_id = uuid.uuid4()

    await ingest_drop(db, parsed, _manifest(), run_id)

    # processed_files inserts are the last 2 executes (after 2 fact-table upserts)
    processed_calls = db.execute.await_args_list[2:]
    assert len(processed_calls) == 2

    for call, expected_file in zip(processed_calls, ["collections.csv", "ar_snapshot.csv"]):
        sql_text = str(call.args[0])
        params = call.args[1]
        assert "INSERT INTO ops.processed_files" in sql_text
        assert params["vendor"] == "ventra"
        assert params["dd"] == date(2026, 5, 15)
        assert params["fn"] == expected_file
        assert params["rid"] == run_id


async def test_ingest_drop_propagates_integrity_error() -> None:
    """If a mid-write IntegrityError fires (e.g. a DB CHECK constraint
    violation slipped past our validators), the exception MUST propagate
    out of ingest_drop so the outer except chain can quarantine + fail
    the run. The ``async with db.begin():`` block rolls back automatically.
    """
    db = _mock_session()
    db.execute = AsyncMock(side_effect=IntegrityError("boom", None, Exception()))

    parsed: dict[str, list] = {"collections.csv": [_collections_row()]}
    run_id = uuid.uuid4()

    with pytest.raises(IntegrityError):
        await ingest_drop(db, parsed, _manifest(), run_id)


async def test_ingest_drop_no_op_on_completely_empty_parsed() -> None:
    """Defensive: if every parsed list is empty, no fact-table writes,
    but the manifest's processed_files rows still go in (V13 should not
    have allowed us here, but the writer should be defensive)."""
    db = _mock_session()
    parsed: dict[str, list] = {}
    run_id = uuid.uuid4()

    result = await ingest_drop(db, parsed, _manifest(), run_id)

    # Only the 2 processed_files inserts ran
    assert db.execute.await_count == 2
    assert result.rows_written == 0
    assert result.rows_by_table == {}
    assert result.vendor_source_systems == []
