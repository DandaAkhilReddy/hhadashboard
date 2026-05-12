"""Quarantine flow for failed Ventra drops.

When any of V1-V14 fails, the main orchestrator (C16) catches the
ValidationError, calls ``quarantine_drop()`` here, then notifies ops via
ACS email (C15). The blob copies + sidecar persist enough state for an
operator to triage the rejection without needing to recover the original
inbound files (which the 90-day lifecycle policy will eventually reap).

Why server-side copy (not move): the operator might still want to
re-trigger the original drop after Ventra pushes a corrected file. Moving
would destroy the canonical source of truth. The 90-day lifecycle on
vendor-inbound reaps the original when it ages out naturally.

PHI safety: the pre-aggregated Ventra file shape carries zero PHI by
construction (ADR-006). The sidecar's DETAILS section dumps
``reason.details`` directly — all values there are Tier-A scalars
(line_no, file_name, facility_no, sha256 hex, etc.) per V1-V13 design.
No row payloads are written.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from app.services import blob

from .exceptions import ADRViolation, ValidationError

VENDOR_INBOUND = "vendor-inbound"
VENDOR_QUARANTINE = "vendor-quarantine"
VENTRA_PREFIX = "ventra"

REJECT_REASON_FILE = "_REJECT_REASON.txt"


def _drop_dir(drop_date: date) -> str:
    """Folder path inside a container for a given drop_date."""
    return f"{VENTRA_PREFIX}/{drop_date.isoformat()}"


def _build_sidecar(
    drop_date: date,
    reason: ValidationError,
    run_id: uuid.UUID,
    correlation_id: uuid.UUID,
) -> bytes:
    """Render the plain-text reject-reason sidecar.

    Format is locked in the plan (Phase 1B C13). Operators read this
    directly via Azure Storage Explorer; not JSON.
    """
    timestamp = datetime.now(tz=UTC).isoformat(timespec="seconds")
    is_adr = isinstance(reason, ADRViolation)
    adr_line = "ADR-005 incident?       YES (V12 — non-FL facility in Ventra drop)" if is_adr else "ADR-005 incident?       no"

    details_block = "\n".join(
        f"  {k}: {v}" for k, v in sorted(reason.details.items())
    ) or "  (none)"

    drop_dir = _drop_dir(drop_date)
    lines = [
        "HHA Ventra ingest — quarantine reject reason",
        "============================================",
        "",
        f"RUN_ID:         {run_id}",
        f"CORRELATION_ID: {correlation_id}",
        f"TIMESTAMP:      {timestamp}",
        f"DROP_DATE:      {drop_date.isoformat()}",
        "",
        f"RULE:    {reason.rule}",
        f"MESSAGE: {reason.message}",
        "",
        "DETAILS:",
        details_block,
        "",
        f"Original drop folder:   {VENDOR_INBOUND}/{drop_dir}/",
        f"This quarantine folder: {VENDOR_QUARANTINE}/{drop_dir}/",
        "",
        adr_line,
        "Operator runbook:       docs/04-operations/RUNBOOK.md#ventra-quarantine",
        "",
        "DO NOT delete files from this folder. Lifecycle policy reaps after 90 days.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


async def quarantine_drop(
    drop_date: date,
    reason: ValidationError,
    run_id: uuid.UUID,
    correlation_id: uuid.UUID,
) -> None:
    """Copy every file in the inbound drop folder to vendor-quarantine,
    plus the ``_REJECT_REASON.txt`` sidecar.

    Inbound files are NOT deleted — the 90-day lifecycle policy on
    vendor-inbound reaps them. An operator can re-trigger the original
    drop after Ventra pushes a corrected file by uploading to
    ``vendor-inbound/ventra/YYYY-MM-DD-retry-1/`` (manual replay path
    documented in the runbook).
    """
    drop_dir = _drop_dir(drop_date)
    listed = await blob.list_by_prefix(
        container_name=VENDOR_INBOUND,
        prefix=f"{drop_dir}/",
        include_metadata=False,
    )
    for entry in listed:
        source_name = entry["name"]                       # e.g. ventra/2026-05-15/collections.csv
        await blob.copy_blob(
            source_container=VENDOR_INBOUND,
            source_blob=source_name,
            dest_container=VENDOR_QUARANTINE,
            dest_blob=source_name,
        )

    sidecar = _build_sidecar(drop_date, reason, run_id, correlation_id)
    await blob.upload_bytes(
        container_name=VENDOR_QUARANTINE,
        blob_name=f"{drop_dir}/{REJECT_REASON_FILE}",
        data=sidecar,
        content_type="text/plain; charset=utf-8",
        metadata={
            "run_id": str(run_id),
            "correlation_id": str(correlation_id),
            "rule": reason.rule,
            "adr_005_incident": "true" if isinstance(reason, ADRViolation) else "false",
        },
        overwrite=True,
    )
