"""Ventra fact-table writer — single-tx all-or-nothing per ADR-006.

Two layers:

  IngestRun                       — ops.ingest_run state machine
    .start(...)                   — INSERT row with status='running'
    .complete(...)                — UPDATE with terminal status + counts

  ingest_drop(db, parsed,         — orchestrates the actual write
              manifest, run_id)
    - opens a single transaction
    - one pg_insert(...).on_conflict_do_update(...) per file type
    - bulk INSERT into ops.processed_files
    - returns IngestResult with row counts + vendor source_system tags

The caller (main.py in C16) is responsible for:
  - setting audit.upn via set_current_upn before opening a session
  - catching ValidationError / ADRViolation BEFORE invoking ingest_drop
    (validators already ran)
  - calling IngestRun.start() to allocate run_id BEFORE ingest_drop
  - calling IngestRun.complete() AFTER ingest_drop succeeds or in the
    except block of any path

The audit.upn GUC is auto-bound to the session in app.deps.SessionLocal's
after_begin listener; we set it once on the contextvar and every write in
this module gets the right attribution.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Self

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entries_ventra import (
    FactArSnapshot,
    FactCollectionsDaily,
    FactRevenueByPhysicianMo,
)

from .manifest import Manifest

VENDOR = "ventra"


# Mutable column sets for ON CONFLICT DO UPDATE. Natural-key columns,
# source_system, state, and created_at are intentionally excluded:
#   - natural key:  the UNIQUE constraint is the conflict target
#   - source_system + state: DB CHECK / server_default lock them
#   - created_at: preserved across restates (audit trail of first-seen)
_MUTABLE_COLLECTIONS = {
    "gross_charges",
    "payments_received",
    "contractual_adjustments",
    "write_offs",
    "payer_refunds",
    "patient_refunds",
    "net_revenue",
    "ingest_run_id",
}
_MUTABLE_AR_SNAPSHOT = {
    "outstanding_amount",
    "ingest_run_id",
}
_MUTABLE_PHYSICIAN_MO = {
    "encounters_count",
    "total_rvu",
    "total_work_rvu",
    "revenue_attributed",
    "ingest_run_id",
}


@dataclass(slots=True)
class IngestRun:
    """ops.ingest_run row handle. Created by ``start()``, terminated by
    ``complete()``. Carries the run_id and correlation_id that downstream
    fact-table writes and notifications stamp into their rows / events.
    """

    run_id: uuid.UUID
    correlation_id: uuid.UUID
    drop_date: date
    manifest_path: str

    @classmethod
    async def start(
        cls,
        db: AsyncSession,
        *,
        drop_date: date,
        manifest_path: str,
        correlation_id: uuid.UUID | None = None,
    ) -> Self:
        """INSERT an ops.ingest_run row with status='running'.

        Commits immediately so the run is visible to operators even if
        the orchestrator crashes mid-validation. The terminal UPDATE in
        ``complete()`` runs in the same outer transaction context but is
        also committed so the status reflects reality after every step.
        """
        run_id = uuid.uuid4()
        cid = correlation_id or uuid.uuid4()
        await db.execute(
            text(
                "INSERT INTO ops.ingest_run "
                "(run_id, vendor, drop_date, manifest_path, status, "
                " correlation_id, started_at) "
                "VALUES (:run_id, :vendor, :dd, :mp, 'running', :cid, now())"
            ),
            {
                "run_id": run_id,
                "vendor": VENDOR,
                "dd": drop_date,
                "mp": manifest_path,
                "cid": cid,
            },
        )
        await db.commit()
        return cls(
            run_id=run_id,
            correlation_id=cid,
            drop_date=drop_date,
            manifest_path=manifest_path,
        )

    async def complete(
        self,
        db: AsyncSession,
        *,
        status: str,
        rows_in: int | None = None,
        rows_out: int | None = None,
        files_count: int | None = None,
        error_message: str | None = None,
        error_details: dict[str, Any] | None = None,
    ) -> None:
        """UPDATE the run row to a terminal status.

        ``status`` MUST be one of ``'succeeded' | 'failed' | 'quarantined'``
        — the DB CHECK constraint rejects anything else. The empty
        ``running`` / ``queued`` values are starting states only and must
        not appear here.
        """
        if status not in {"succeeded", "failed", "quarantined"}:
            raise ValueError(
                f"IngestRun.complete: invalid terminal status {status!r}"
            )
        await db.execute(
            text(
                "UPDATE ops.ingest_run SET "
                " status = :status, "
                " completed_at = now(), "
                " files_count = :files_count, "
                " rows_in = :rows_in, "
                " rows_out = :rows_out, "
                " error_message = :error_message, "
                " error_details = CAST(:error_details AS JSONB) "
                "WHERE run_id = :run_id"
            ),
            {
                "status": status,
                "files_count": files_count,
                "rows_in": rows_in,
                "rows_out": rows_out,
                "error_message": error_message,
                "error_details": _jsonb_param(error_details),
                "run_id": self.run_id,
            },
        )
        await db.commit()


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Outcome of a successful ``ingest_drop`` call.

    ``rows_by_table`` is the per-table count of rows the upsert affected
    (INSERT or UPDATE — Postgres reports it the same way). Used by C14
    to emit ``ventra.rows_written`` events.

    ``vendor_source_systems`` is the deduped set of Ventra's PM-tag
    values seen across every parsed row in this drop. Captured here for
    the ``ventra.ingest_complete`` event so reconciliation against
    Ventra's monthly client report can split by PM system. Never
    persisted to the fact tables.
    """

    rows_written: int
    rows_by_table: dict[str, int] = field(default_factory=dict)
    vendor_source_systems: list[str] = field(default_factory=list)


async def ingest_drop(
    db: AsyncSession,
    parsed: dict[str, list[BaseModel]],
    manifest: Manifest,
    run_id: uuid.UUID,
) -> IngestResult:
    """All-or-nothing single-transaction upsert.

    Caller has already:
      - allocated an ``ops.ingest_run`` row via ``IngestRun.start()``
      - run V1-V14 validators against ``parsed``
      - confirmed V13 dedup did not say ``skip_entirely`` (this call
        always writes; the dedup short-circuit lives in main.py)

    On any IntegrityError or DB error, the surrounding ``async with
    db.begin():`` block rolls back ALL fact-table writes AND the
    processed_files inserts — partial publication of a drop is
    impossible by construction.
    """
    rows_by_table: dict[str, int] = {}
    vendor_tags: set[str] = set()

    async with db.begin():
        # ----- collections.csv -----
        rows = parsed.get("collections.csv", [])
        if rows:
            values = [
                {
                    "date": r.date,
                    "facility_no": r.facility_no,
                    "payer_class": r.payer_class,
                    "gross_charges": r.gross_charges,
                    "payments_received": r.payments_received,
                    "contractual_adjustments": r.contractual_adjustments,
                    "write_offs": r.write_offs,
                    "payer_refunds": r.payer_refunds,
                    "patient_refunds": r.patient_refunds,
                    "net_revenue": r.net_revenue,
                    "ingest_run_id": run_id,
                }
                for r in rows
            ]
            stmt = pg_insert(FactCollectionsDaily).values(values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["date", "facility_no", "payer_class"],
                set_={col: stmt.excluded[col] for col in _MUTABLE_COLLECTIONS},
            )
            await db.execute(stmt)
            rows_by_table["fact_collections_daily"] = len(values)
            vendor_tags.update(_tags(rows))

        # ----- ar_snapshot.csv -----
        rows = parsed.get("ar_snapshot.csv", [])
        if rows:
            values = [
                {
                    "snapshot_date": r.snapshot_date,
                    "facility_no": r.facility_no,
                    "aging_bucket": r.aging_bucket,
                    "outstanding_amount": r.outstanding_amount,
                    "ingest_run_id": run_id,
                }
                for r in rows
            ]
            stmt = pg_insert(FactArSnapshot).values(values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["snapshot_date", "facility_no", "aging_bucket"],
                set_={col: stmt.excluded[col] for col in _MUTABLE_AR_SNAPSHOT},
            )
            await db.execute(stmt)
            rows_by_table["fact_ar_snapshot"] = len(values)
            vendor_tags.update(_tags(rows))

        # ----- physician_monthly.csv (only present on month-close drops) -----
        rows = parsed.get("physician_monthly.csv", [])
        if rows:
            values = [
                {
                    "month": r.month,
                    "physician_npi": r.physician_npi,
                    "facility_no": r.facility_no,
                    "encounters_count": r.encounters_count,
                    "total_rvu": r.total_rvu,
                    "total_work_rvu": r.total_work_rvu,
                    "revenue_attributed": r.revenue_attributed,
                    "ingest_run_id": run_id,
                }
                for r in rows
            ]
            stmt = pg_insert(FactRevenueByPhysicianMo).values(values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["month", "physician_npi", "facility_no"],
                set_={col: stmt.excluded[col] for col in _MUTABLE_PHYSICIAN_MO},
            )
            await db.execute(stmt)
            rows_by_table["fact_revenue_by_physician_mo"] = len(values)
            vendor_tags.update(_tags(rows))

        # ----- ops.processed_files dedup ledger -----
        # One row per manifest entry. UNIQUE(vendor, sha256) raises
        # IntegrityError on a logic bug (V13 should have caught it).
        for entry in manifest.entries:
            await db.execute(
                text(
                    "INSERT INTO ops.processed_files "
                    "(vendor, drop_date, file_name, blob_path, "
                    " sha256, row_count, run_id) "
                    "VALUES (:vendor, :dd, :fn, :bp, :sha, :rc, :rid)"
                ),
                {
                    "vendor": VENDOR,
                    "dd": manifest.drop_date,
                    "fn": entry.file_name,
                    "bp": f"{VENDOR}/{manifest.drop_date.isoformat()}/{entry.file_name}",
                    "sha": entry.sha256,
                    "rc": entry.row_count,
                    "rid": run_id,
                },
            )

    return IngestResult(
        rows_written=sum(rows_by_table.values()),
        rows_by_table=rows_by_table,
        vendor_source_systems=sorted(vendor_tags),
    )


def _tags(rows: list[BaseModel]) -> set[str]:
    """Pull Ventra's source_system tag (CB/MGS/VSQL/DUVA) off every row."""
    return {getattr(r, "source_system", "") for r in rows if getattr(r, "source_system", "")}


def _jsonb_param(value: dict[str, Any] | None) -> str | None:
    """SQLAlchemy text() doesn't auto-serialize dicts to JSONB on Postgres.
    Encode to JSON string here; CAST is in the SQL."""
    if value is None:
        return None
    import json
    return json.dumps(value, default=str)
