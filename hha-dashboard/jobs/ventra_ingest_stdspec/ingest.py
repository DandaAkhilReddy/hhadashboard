"""Single-tx upsert writer for the row-level (Standard Spec) path.

Mirrors ``jobs/ventra_ingest/ingest.py`` from PR #54 with the deltas
required by Phase 4 H1's dual-source schema:

  - Every fact-table row carries source_system='VENTRA_FL_STDSPEC_AGG'
    explicitly. H1 dropped the server_default so the writer MUST pass
    the tag — preventing a silent default-wins bug if either pipeline
    is misconfigured.

  - The UNIQUE constraint on each fact table is widened to include
    source_system (H1). The on_conflict_do_update target reflects this:
    the 4-tuple is the conflict key, so the stdspec writer can never
    overwrite a row written by the preagg path and vice versa.

  - VENDOR = 'ventra-stdspec' tags the dedup ledger entries
    (ops.processed_files) so V13 dedup decisions stay isolated between
    pipelines. The pre-agg path uses 'ventra' (or 'ventra-preagg' after
    H14).

  - Input is the three aggregate lists from
    ``aggregator.to_*_rows()`` — frozen dataclasses, not Pydantic
    models. The PHI strip already happened at the parser layer (H8);
    the aggregator's outputs carry only the natural-key tuples + Decimal
    sums + counters that the fact tables accept.

Single-transaction discipline (per ADR-006 + the Phase 4 plan):
  All three fact-table upserts + the ops.processed_files inserts are
  bracketed by one ``async with db.begin():`` block. Any IntegrityError
  rolls back EVERYTHING. Partial publication of a drop is impossible.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Self

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entries_ventra import (
    SOURCE_STDSPEC,
    FactArSnapshot,
    FactCollectionsDaily,
    FactRevenueByPhysicianMo,
)

from .aggregator import (
    ArSnapshotAggregate,
    CollectionsAggregate,
    PhysicianMonthlyAggregate,
)
from .validators import VENDOR_STDSPEC, ManifestEntry

# Mutable column sets for ON CONFLICT DO UPDATE. Natural-key columns,
# source_system, state, and created_at are intentionally excluded:
#   - natural key (incl. source_system): the widened UNIQUE constraint
#     is the conflict target; the 4-tuple match is the dedup criterion.
#   - state: server_default + DB CHECK lock to 'FL'.
#   - created_at: preserved across restates (audit trail of first-seen).
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
    """ops.ingest_run row handle for the stdspec pipeline.

    Same shape + state machine as the pre-aggregated path's IngestRun,
    but vendor='ventra-stdspec' so the two paths' run histories are
    distinguishable by a SQL filter.
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
        """INSERT an ops.ingest_run row with status='running' + commit.

        Committing immediately makes the row visible to operators even
        if the orchestrator crashes mid-validation — they can tell
        whether the job started and which drop it was on.
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
                "vendor": VENDOR_STDSPEC,
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

        ``status`` MUST be one of 'succeeded' / 'failed' / 'quarantined'
        — the DB CHECK rejects anything else. ``error_message`` is the
        PHI-safe one-line summary (from SafeMessageError.safe_message);
        ``error_details`` is the JSONB payload (also PHI-safe by
        construction — see exceptions.py contract).
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

    ``rows_by_table`` is the per-table count of rows the upsert touched.
    ``vendor_source_systems`` reflects Ventra's PM-tag values seen across
    invoice rows (CB / MGS / VSQL / DUVA) — pre-collected by the
    aggregator from the parser layer; emitted in App Insights events
    for forensic queries against Ventra's monthly client report.
    """

    rows_written: int
    rows_by_table: dict[str, int] = field(default_factory=dict)
    vendor_source_systems: list[str] = field(default_factory=list)


async def ingest_drop(
    db: AsyncSession,
    collections_rows: Sequence[CollectionsAggregate],
    ar_rows: Sequence[ArSnapshotAggregate],
    physician_rows: Sequence[PhysicianMonthlyAggregate],
    manifest_entries: Sequence[ManifestEntry],
    drop_date: date,
    run_id: uuid.UUID,
    vendor_source_systems: Sequence[str] = (),
) -> IngestResult:
    """All-or-nothing single-transaction write of the stdspec aggregates.

    Caller has already:
      - allocated an ops.ingest_run via IngestRun.start()
      - run validators V8 / V12 / V13 / V15 layer 4 / V9
      - confirmed V13 said skip_entirely=False (the dedup short-circuit
        lives in main.py — this call always writes)

    Single ``async with db.begin():`` block brackets all writes. Any
    failure rolls back every fact-table upsert AND every processed_files
    insert atomically.
    """
    rows_by_table: dict[str, int] = {}

    async with db.begin():
        # ----- fact_collections_daily -----
        if collections_rows:
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
                    "source_system": SOURCE_STDSPEC,
                    "ingest_run_id": run_id,
                }
                for r in collections_rows
            ]
            stmt = pg_insert(FactCollectionsDaily).values(values)
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    "date",
                    "facility_no",
                    "payer_class",
                    "source_system",
                ],
                set_={col: stmt.excluded[col] for col in _MUTABLE_COLLECTIONS},
            )
            await db.execute(stmt)
            rows_by_table["fact_collections_daily"] = len(values)

        # ----- fact_ar_snapshot -----
        if ar_rows:
            values = [
                {
                    "snapshot_date": r.snapshot_date,
                    "facility_no": r.facility_no,
                    "aging_bucket": r.aging_bucket,
                    "outstanding_amount": r.outstanding_amount,
                    "source_system": SOURCE_STDSPEC,
                    "ingest_run_id": run_id,
                }
                for r in ar_rows
            ]
            stmt = pg_insert(FactArSnapshot).values(values)
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    "snapshot_date",
                    "facility_no",
                    "aging_bucket",
                    "source_system",
                ],
                set_={col: stmt.excluded[col] for col in _MUTABLE_AR_SNAPSHOT},
            )
            await db.execute(stmt)
            rows_by_table["fact_ar_snapshot"] = len(values)

        # ----- fact_revenue_by_physician_mo -----
        if physician_rows:
            values = [
                {
                    "month": r.month,
                    "physician_npi": r.physician_npi,
                    "facility_no": r.facility_no,
                    "encounters_count": r.encounters_count,
                    "total_rvu": r.total_rvu,
                    "total_work_rvu": r.total_work_rvu,
                    "revenue_attributed": r.revenue_attributed,
                    "source_system": SOURCE_STDSPEC,
                    "ingest_run_id": run_id,
                }
                for r in physician_rows
            ]
            stmt = pg_insert(FactRevenueByPhysicianMo).values(values)
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    "month",
                    "physician_npi",
                    "facility_no",
                    "source_system",
                ],
                set_={col: stmt.excluded[col] for col in _MUTABLE_PHYSICIAN_MO},
            )
            await db.execute(stmt)
            rows_by_table["fact_revenue_by_physician_mo"] = len(values)

        # ----- ops.processed_files dedup ledger -----
        # One row per manifest entry. UNIQUE(vendor, sha256) would raise
        # IntegrityError on a logic bug — V13 should have caught it.
        for entry in manifest_entries:
            await db.execute(
                text(
                    "INSERT INTO ops.processed_files "
                    "(vendor, drop_date, file_name, blob_path, "
                    " sha256, row_count, run_id) "
                    "VALUES (:vendor, :dd, :fn, :bp, :sha, :rc, :rid)"
                ),
                {
                    "vendor": VENDOR_STDSPEC,
                    "dd": drop_date,
                    "fn": entry.file_name,
                    "bp": (
                        f"vendor-inbound/ventra/stdspec/"
                        f"{drop_date.isoformat()}/{entry.file_name}"
                    ),
                    "sha": entry.sha256,
                    # The row_count from the manifest, not from the
                    # aggregator — the manifest count is what Ventra
                    # promised; the aggregator count is what we read.
                    # Storing the manifest count makes V4 (count match)
                    # forensically reproducible.
                    "rc": getattr(entry, "row_count", 0),
                    "rid": run_id,
                },
            )

    return IngestResult(
        rows_written=sum(rows_by_table.values()),
        rows_by_table=rows_by_table,
        vendor_source_systems=sorted(set(vendor_source_systems)),
    )


def _jsonb_param(value: dict[str, Any] | None) -> str | None:
    """SQLAlchemy text() doesn't auto-serialize dicts to JSONB on Postgres.
    Encode to JSON string here; the surrounding SQL contains the CAST."""
    if value is None:
        return None
    return json.dumps(value, default=str)


__all__ = [
    "IngestResult",
    "IngestRun",
    "ingest_drop",
]
