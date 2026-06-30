"""DB-dependent validators for the row-level ingest pipeline.

Three checks here, all running against a live AsyncSession before the
single-tx write commits:

  V8  — every facility_no in the drop exists in ``masters.sites``.
        Unknown facility => config drift (ops alert + quarantine).

  V12 — every facility_no in the drop has ``state = 'FL'`` in
        ``masters.sites``. Non-FL facility => ADRViolation (incident
        path + SECURITY_INCIDENT_PLAYBOOK). Same ADR-005 invariant the
        pre-aggregated path enforces.

  V13 — every (file_name, sha256) in the drop's manifest is compared
        against ``ops.processed_files``. Outcomes per entry:
          - not present                   -> process (fresh).
          - present with same sha256      -> already_processed.
          - present with different sha256 -> conflict (V13 quarantine).

The four-layer V15 PHI denial is split across the pipeline:
  Layer 1 (pre-strip sanity) -> parsers/standard_spec.py header check.
  Layer 2 (post-strip)       -> aggregator.process_invoice_row() via
                                phi.assert_no_phi_columns().
  Layer 3 (telemetry export) -> logging.py structlog processors.
  Layer 4 (pre-write)        -> assert_v15_pre_write() in this module,
                                called by main.py before the writer.

Test contract: every code path here has both happy + sad coverage in
``api/tests/test_ventra_stdspec_validators.py`` (lands in H18).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .exceptions import ADRViolation, PHILeakError, ValidationError
from .phi import is_forbidden_column

# Vendor key written to ops.processed_files / ops.ingest_run for the
# stdspec path. The pre-aggregated path uses 'ventra' (or 'ventra-preagg'
# after H14); these two keys are intentionally distinct so dedup
# decisions stay isolated between the pipelines.
VENDOR_STDSPEC = "ventra-stdspec"


# ============================================================================
# V8 + V12 — facility classification via masters.sites
# ============================================================================


async def validate_fl_only(
    db: AsyncSession, ventra_facilities: Iterable[int]
) -> dict[int, int]:
    """V12 + V8 — resolve every Ventra FacilityNo via dims.facility_codes
    and confirm it maps to an ACTIVE Florida site. Returns the facility
    map the aggregator uses.

    Ventra keys its data by FacilityNo (2284-2290); HHA keys by
    masters.sites.id (1-7). The open mappings (effective_through IS NULL)
    in dims.facility_codes (migration 0014) bridge them. Single query:

        SELECT fc.ventra_facility_no, fc.site_id, s.state
        FROM dims.facility_codes fc
        JOIN masters.sites s ON s.id = fc.site_id
        WHERE fc.effective_through IS NULL AND s.status = 'ACTIVE'

    Per Ventra FacilityNo in the drop:
      - mapped to an FL site     -> OK; added to the returned map.
      - mapped to a non-FL site  -> ADRViolation (V12, ADR-005 incident).
      - not mapped at all        -> ValidationError(rule='V8') (config
                                    drift: Ventra sent a facility HHA has
                                    no mapping for; quarantine + ops alert).

    Returns ``{ventra_facility_no: site_id}`` for the FL facilities in the
    drop. Fail-fast — the first non-FL or unmapped facility short-circuits
    and the orchestrator quarantines before the aggregator runs.
    """
    result = await db.execute(
        text(
            "SELECT fc.ventra_facility_no, fc.site_id, s.state "
            "FROM dims.facility_codes fc "
            "JOIN masters.sites s ON s.id = fc.site_id "
            "WHERE fc.effective_through IS NULL AND s.status = 'ACTIVE'"
        )
    )
    mapping: dict[int, tuple[int, str]] = {
        row[0]: (row[1], row[2]) for row in result
    }

    facility_map: dict[int, int] = {}
    for fid in sorted(set(ventra_facilities)):
        entry = mapping.get(fid)
        if entry is None:
            # No mapping row — V8 config drift (fail-closed).
            raise ValidationError(
                rule="V8",
                safe_message=(
                    f"unknown Ventra facility_no={fid} (no active mapping in "
                    f"dims.facility_codes; vendor config drift or HHA missing "
                    f"a mapping row)"
                ),
                internal_details={"ventra_facility_no": fid},
            )
        site_id, state = entry
        if state != "FL":
            # Mapped to a non-FL site — ADR-005 violation.
            raise ADRViolation(
                safe_message=(
                    f"non-FL facility in Ventra stdspec drop: "
                    f"ventra_facility_no={fid} site_id={site_id} hha_state={state}"
                ),
                internal_details={
                    "ventra_facility_no": fid,
                    "site_id": site_id,
                    "hha_state": state,
                },
            )
        facility_map[fid] = site_id

    return facility_map


# ============================================================================
# V13 — dedup against ops.processed_files
# ============================================================================


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """Minimal manifest-entry shape for dedup. The full Manifest model
    lives in ``manifest.py`` (H13); ``check_dedup`` only needs file_name
    + sha256, so we accept this lightweight dataclass to keep this
    module's import surface small."""

    file_name: str
    sha256: str


@dataclass(frozen=True, slots=True)
class DedupDecision:
    """Outcome of the V13 check.

    ``skip_entirely`` is true when EVERY manifest entry was already
    processed with the same sha256 — the orchestrator short-circuits
    to the dedup_skip path (no writes, no notifications).

    ``already_processed`` lists the file_names that were seen before
    with the same sha256. Partial dedup is allowed: some files fresh,
    others already-processed; the fresh ones still get written.

    ``fresh`` lists the file_names that should be processed (i.e. not
    in already_processed and not in any conflict).
    """

    skip_entirely: bool
    already_processed: list[str]
    fresh: list[str]


async def check_dedup(
    db: AsyncSession,
    drop_date: date,
    entries: Sequence[ManifestEntry],
    vendor: str = VENDOR_STDSPEC,
) -> DedupDecision:
    """V13 — compare manifest entries to ops.processed_files.

    Single query against the dedup ledger:
        SELECT file_name, sha256 FROM ops.processed_files
        WHERE vendor = :vendor AND drop_date = :drop_date

    Raises ``ValidationError(rule='V13')`` if any entry is present in
    the ledger with a DIFFERENT sha256 — vendor restated the data,
    operator must explicitly accept via the manual-replay runbook.

    Returns ``DedupDecision`` describing what to process; never None.
    """
    result = await db.execute(
        text(
            "SELECT file_name, sha256 FROM ops.processed_files "
            "WHERE vendor = :vendor AND drop_date = :dd"
        ),
        {"vendor": vendor, "dd": drop_date},
    )
    existing: dict[str, str] = {row[0]: row[1] for row in result}

    already_processed: list[str] = []
    fresh: list[str] = []
    conflict_files: list[dict[str, str]] = []

    for entry in entries:
        prior_sha = existing.get(entry.file_name)
        if prior_sha is None:
            fresh.append(entry.file_name)
            continue
        if prior_sha == entry.sha256:
            already_processed.append(entry.file_name)
        else:
            conflict_files.append(
                {
                    "file_name": entry.file_name,
                    "prior_sha256_prefix": prior_sha[:8],
                    "new_sha256_prefix": entry.sha256[:8],
                }
            )

    if conflict_files:
        raise ValidationError(
            rule="V13",
            safe_message=(
                f"{len(conflict_files)} file(s) re-sent with changed "
                f"content for drop_date={drop_date.isoformat()}; "
                f"manual review required (see RUNBOOK ventra-stdspec restate)"
            ),
            internal_details={
                "drop_date": drop_date.isoformat(),
                "vendor": vendor,
                # sha256 prefixes only — full hashes can hint at content
                # provenance and are not needed for triage.
                "conflicts": conflict_files,
            },
        )

    skip_entirely = (
        len(already_processed) == len(entries) and len(entries) > 0
    )

    return DedupDecision(
        skip_entirely=skip_entirely,
        already_processed=already_processed,
        fresh=fresh,
    )


# ============================================================================
# V15 layer 4 — pre-write PHI denial on the aggregates
# ============================================================================


class _AggregateLike(Protocol):
    """Structural type for the three Aggregate dataclasses produced by
    ``aggregator.to_*_rows()``. Each one is a frozen dataclass; we need
    only its ``__dataclass_fields__`` for introspection."""

    __dataclass_fields__: dict[str, Any]


def assert_v15_pre_write(aggregates: Iterable[_AggregateLike]) -> None:
    """V15 layer 4 — DB-bound aggregate has zero forbidden keys.

    Walks the dataclass field names of each aggregate (one of
    CollectionsAggregate, ArSnapshotAggregate, PhysicianMonthlyAggregate).
    Any field name matching the denylist raises ``PHILeakError`` —
    routes the orchestrator to the incident path because it means a code
    change accidentally added a PHI-named field to one of the aggregate
    types, which would only be possible by editing aggregator.py.

    Cheap to run (field names are static per class), but the assertion
    is here as a tripwire: H1 migration's CI test_schema_classification.py
    catches schema-side, this catches Python-side.
    """
    if not aggregates:
        return
    # Sample one aggregate per type (all rows of the same type share field
    # names). Iterate the first row only.
    seen_types: set[type] = set()
    for agg in aggregates:
        cls = type(agg)
        if cls in seen_types:
            continue
        seen_types.add(cls)
        for field_name in cls.__dataclass_fields__:
            if is_forbidden_column(field_name):
                raise PHILeakError(
                    layer="pre_write",
                    safe_message=(
                        f"aggregate type {cls.__name__} has forbidden "
                        f"field {field_name!r}"
                    ),
                    internal_details={
                        "aggregate_type": cls.__name__,
                        "offending_field": field_name,
                    },
                )


# ============================================================================
# AR bucket sanity (cross-aggregate consistency)
# ============================================================================


def validate_ar_buckets(ar_rows: Sequence[Any]) -> None:
    """Pin V9-style invariants on the AR snapshot aggregates.

    Two checks:
      - Uniqueness: every (snapshot_date, facility_no, aging_bucket)
        tuple appears at most once. The aggregator's defaultdict
        guarantees this by construction, but we double-check before
        the writer sees the rows.
      - Sign discipline: outstanding_amount is non-negative for every
        bucket EXCEPT 'credit'.

    Raises ``ValidationError(rule='V9')`` on either violation. Never
    raises on an empty input.
    """
    seen: set[tuple[date, int, str]] = set()
    for row in ar_rows:
        key = (row.snapshot_date, row.facility_no, row.aging_bucket)
        if key in seen:
            raise ValidationError(
                rule="V9",
                safe_message=(
                    f"duplicate AR bucket: snapshot_date={key[0]} "
                    f"facility_no={key[1]} aging_bucket={key[2]}"
                ),
                internal_details={
                    "snapshot_date": key[0].isoformat(),
                    "facility_no": key[1],
                    "aging_bucket": key[2],
                },
            )
        seen.add(key)
        if row.aging_bucket != "credit" and row.outstanding_amount < Decimal(0):
            raise ValidationError(
                rule="V9",
                safe_message=(
                    f"negative outstanding in non-credit bucket: "
                    f"facility_no={row.facility_no} "
                    f"aging_bucket={row.aging_bucket}"
                ),
                internal_details={
                    "snapshot_date": row.snapshot_date.isoformat(),
                    "facility_no": row.facility_no,
                    "aging_bucket": row.aging_bucket,
                },
            )


__all__ = [
    "VENDOR_STDSPEC",
    "DedupDecision",
    "ManifestEntry",
    "assert_v15_pre_write",
    "check_dedup",
    "validate_ar_buckets",
    "validate_fl_only",
]
