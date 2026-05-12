"""Cross-file validators for the Ventra ingest pipeline.

Per-row validators (V5, V7, V9-per-row, V10, V11) live in the per-file
parsers. This module owns the rules that need either the full parsed
batch, cross-file context, or a database query.

  V6:  drop-date drift — collections + ar_snapshot rows' date columns
       match the drop_date in the folder name.
  V9:  cross-row uniqueness of (snapshot_date, facility_no, aging_bucket)
       within a single drop. Sum-to-total deferred (no anchor in spec).
  V12: FL-only invariant via masters.sites query. Two-stage:
        - facility_no in FL set        -> OK
        - facility_no in sites, !FL    -> ADRViolation (ADR-005 incident)
        - facility_no not in sites     -> ValidationError(rule='V8')
  V13: dedup via ops.processed_files. Three outcomes per file:
        - never seen (vendor, drop_date, file_name)    -> process
        - same sha256 already processed                -> skip
        - same (drop_date, file_name) different sha    -> quarantine

Schema assumption (v1, to be re-confirmed with Ventra):
  Ventra's CSV ``facility_no`` value == ``masters.sites.id``. HHA gives
  Ventra the list of HHA's FL site IDs to use. If Ventra later insists
  on their internal Facility-file IDs, a follow-up commit adds a
  ``ventra_facility_no`` nullable column on ``masters.sites`` and updates
  ``validate_fl_only`` to join through it.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .exceptions import ADRViolation, ValidationError
from .manifest import Manifest


class DedupDecision(BaseModel):
    """Outcome of V13 dedup check.

    ``skip_entirely`` is True when every file in the manifest is an exact
    sha256 match against ``ops.processed_files`` — the main orchestrator
    short-circuits to a success-with-note path (no parsing, no DB writes).

    ``already_processed`` lists file names that match prior content; the
    caller can skip them in a partial-update scenario (not currently used;
    the orchestrator either skips the whole drop or processes it in full
    per the all-or-nothing tx contract).
    """

    model_config = ConfigDict(frozen=True)

    skip_entirely: bool
    already_processed: list[str]


def validate_drop_consistency(
    parsed: dict[str, list], drop_date: date
) -> None:
    """V6 — collections + ar_snapshot date columns match the drop_date.

    physician_monthly intentionally exempt: it carries ``month``
    (first-of-month) which is constrained by V7 in the parser; the vendor
    may emit prior-month or restated months on any drop_date.
    """
    rows = parsed.get("collections.csv", [])
    for line_no, row in enumerate(rows, start=2):
        if row.date != drop_date:
            raise ValidationError(
                rule="V6",
                message=(
                    f"collections.csv line {line_no} date={row.date.isoformat()} "
                    f"does not match drop_date={drop_date.isoformat()}"
                ),
                details={
                    "file_name": "collections.csv",
                    "line_no": line_no,
                    "row_date": row.date.isoformat(),
                    "drop_date": drop_date.isoformat(),
                },
            )

    rows = parsed.get("ar_snapshot.csv", [])
    for line_no, row in enumerate(rows, start=2):
        if row.snapshot_date != drop_date:
            raise ValidationError(
                rule="V6",
                message=(
                    f"ar_snapshot.csv line {line_no} snapshot_date="
                    f"{row.snapshot_date.isoformat()} does not match "
                    f"drop_date={drop_date.isoformat()}"
                ),
                details={
                    "file_name": "ar_snapshot.csv",
                    "line_no": line_no,
                    "row_date": row.snapshot_date.isoformat(),
                    "drop_date": drop_date.isoformat(),
                },
            )


def validate_ar_buckets_sum(ar_rows: list | None) -> None:
    """V9 cross-row — (snapshot_date, facility_no, aging_bucket) tuples
    must be unique within a drop. A duplicate indicates a vendor-side
    aggregation bug.

    The "sum to expected total within $1" interpretation of V9 is deferred
    until HHA has a reconciliation anchor (likely Ventra's monthly client
    report PDF — a P2 follow-up after first real drops).
    """
    if not ar_rows:
        return
    seen: set[tuple[date, int, str]] = set()
    for line_no, row in enumerate(ar_rows, start=2):
        key = (row.snapshot_date, row.facility_no, row.aging_bucket)
        if key in seen:
            raise ValidationError(
                rule="V9",
                message=(
                    f"ar_snapshot.csv line {line_no} duplicates "
                    f"(snapshot_date={key[0].isoformat()}, "
                    f"facility_no={key[1]}, aging_bucket={key[2]!r})"
                ),
                details={
                    "file_name": "ar_snapshot.csv",
                    "line_no": line_no,
                    "snapshot_date": key[0].isoformat(),
                    "facility_no": key[1],
                    "aging_bucket": key[2],
                },
            )
        seen.add(key)


async def validate_fl_only(
    db: AsyncSession, parsed: dict[str, list]
) -> None:
    """V12 + V8 — classify every facility_no against masters.sites.

    Two queries collapsed into one to minimize DB roundtrips:
      SELECT id, state FROM masters.sites WHERE status = 'ACTIVE'

    Per-row classification:
      - state == 'FL'     -> OK
      - state != 'FL'     -> ADRViolation (ADR-005 incident path)
      - not in result set -> ValidationError(rule='V8') (config drift)

    A V12 ADRViolation is fail-fast — the FIRST non-FL facility short-
    circuits the entire validation. The details payload includes the file
    name + line number for triage.
    """
    result = await db.execute(
        text("SELECT id, state FROM masters.sites WHERE status = 'ACTIVE'")
    )
    site_state: dict[int, str] = {row[0]: row[1] for row in result}

    for file_name, rows in parsed.items():
        for line_no, row in enumerate(rows, start=2):
            fid = row.facility_no
            state = site_state.get(fid)
            if state == "FL":
                continue
            if state is not None:
                # Site exists in HHA but is not FL — ADR-005 violation.
                raise ADRViolation(
                    message=(
                        f"non-FL facility in Ventra drop: {file_name} "
                        f"line {line_no} facility_no={fid} hha_state={state}"
                    ),
                    details={
                        "file_name": file_name,
                        "line_no": line_no,
                        "facility_no": fid,
                        "hha_state": state,
                    },
                )
            # Not in masters.sites at all — V8 unknown facility.
            raise ValidationError(
                rule="V8",
                message=(
                    f"unknown facility_no={fid} in {file_name} line {line_no} "
                    f"(not present in masters.sites — vendor config drift "
                    f"or HHA missing a new site row)"
                ),
                details={
                    "file_name": file_name,
                    "line_no": line_no,
                    "facility_no": fid,
                },
            )


async def check_dedup(db: AsyncSession, manifest: Manifest) -> DedupDecision:
    """V13 — compare manifest entries to ops.processed_files.

    Single query against the dedup ledger:
      SELECT file_name, sha256 FROM ops.processed_files
      WHERE vendor = 'ventra' AND drop_date = :drop_date

    Per manifest entry:
      - file_name not seen for this drop_date          -> process (fresh)
      - file_name seen with same sha256                -> already_processed
      - file_name seen with different sha256           -> conflict (V13)

    Returns DedupDecision(skip_entirely, already_processed). Raises
    ValidationError(rule='V13') if any conflict is present — the operator
    must explicitly accept a restated drop via the manual-replay runbook
    (a separate code path adds an ``--allow-restate`` flag in a later
    enhancement).
    """
    result = await db.execute(
        text(
            "SELECT file_name, sha256 FROM ops.processed_files "
            "WHERE vendor = 'ventra' AND drop_date = :dd"
        ),
        {"dd": manifest.drop_date},
    )
    existing: dict[str, str] = {row[0]: row[1] for row in result}

    already_processed: list[str] = []
    conflict_files: list[dict[str, str]] = []

    for entry in manifest.entries:
        prior_sha = existing.get(entry.file_name)
        if prior_sha is None:
            continue
        if prior_sha == entry.sha256:
            already_processed.append(entry.file_name)
        else:
            conflict_files.append(
                {
                    "file_name": entry.file_name,
                    "prior_sha256": prior_sha,
                    "new_sha256": entry.sha256,
                }
            )

    if conflict_files:
        raise ValidationError(
            rule="V13",
            message=(
                f"{len(conflict_files)} file(s) re-sent with changed content "
                f"for drop_date={manifest.drop_date.isoformat()}; manual "
                f"review required (see RUNBOOK -- Ventra restate procedure)"
            ),
            details={
                "drop_date": manifest.drop_date.isoformat(),
                "conflicts": conflict_files,
            },
        )

    skip_entirely = (
        len(already_processed) == len(manifest.entries)
        and len(manifest.entries) > 0
    )
    return DedupDecision(
        skip_entirely=skip_entirely,
        already_processed=already_processed,
    )
