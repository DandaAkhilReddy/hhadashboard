"""Quarantine flow for failed row-level (Standard Spec) drops.

Same shape as ``jobs/ventra_ingest/quarantine.py`` from PR #54 with three
deltas that matter for PHI safety:

  1. The sidecar carries ``reason.safe_message`` + ``reason.internal_details``
     only — both guaranteed PHI-free by the ``SafeMessageError`` discipline
     in ``exceptions.py``. The pre-agg sidecar uses ``reason.message`` +
     ``reason.details`` (also PHI-free, but the row-level path's exceptions
     have the named-field protection).

  2. Inbound files copy to ``vendor-quarantine/ventra/stdspec/<drop_date>/``
     (a deeper subprefix than the pre-agg path's ``vendor-quarantine/ventra/``).
     The infra plan layers a 30-day lifecycle rule on this prefix in a
     follow-up Bicep commit; until then the rows fall under the existing
     90-day vendor-quarantine policy (acceptable interim — files contain
     stripped-PHI columns the inbound CSVs already had, and the lifecycle
     window is the operational ceiling, not a contractual one).

  3. The sidecar prominently flags PHILeakError as a HARD INCIDENT
     distinct from ADRViolation. Both route the orchestrator to the
     incident path, but the response runbooks differ:
       - V12 ADRViolation: ADR-005 escalation, security playbook page.
       - V15 PHILeakError: deploy revert + 24h HIPAA-reportability review.

Inbound files are NOT deleted — the 30-day lifecycle policy on
``vendor-inbound/ventra/stdspec/`` (from H2) reaps them. The operator
can manually re-trigger after Ventra pushes a corrected file by
uploading to ``vendor-inbound/ventra/stdspec/<drop_date>-retry-1/``
(documented in the H19 SFTP-handoff doc).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from app.services import blob

from .exceptions import ADRViolation, PHILeakError, SafeMessageError

VENDOR_INBOUND = "vendor-inbound"
VENDOR_QUARANTINE = "vendor-quarantine"
VENTRA_STDSPEC_PREFIX = "ventra/stdspec"

REJECT_REASON_FILE = "_REJECT_REASON.txt"


def _drop_dir(drop_date: date) -> str:
    """Folder path inside a container for a given drop_date.

    Returns e.g. ``ventra/stdspec/2026-06-03`` — used as a prefix on
    both the inbound (source) and quarantine (destination) containers.
    """
    return f"{VENTRA_STDSPEC_PREFIX}/{drop_date.isoformat()}"


def _incident_label(reason: SafeMessageError) -> str:
    """Return a one-line operator hint about the incident class.

    Operators triaging a quarantine see this at the top of the sidecar
    so they know which playbook to follow without reading the full
    payload first.
    """
    if isinstance(reason, PHILeakError):
        return (
            "V15 PHI LEAK (deploy revert + 24h HIPAA-reportability review required)"
        )
    if isinstance(reason, ADRViolation):
        return "ADR-005 incident (V12 — non-FL facility in Ventra drop)"
    return f"validation failure (rule={getattr(reason, 'rule', 'unknown')})"


def _build_sidecar(
    drop_date: date,
    reason: SafeMessageError,
    run_id: uuid.UUID,
    correlation_id: uuid.UUID,
) -> bytes:
    """Render the plain-text reject-reason sidecar.

    Format mirrors the pre-aggregated path so an operator already
    familiar with the V1-V14 runbook recognizes the layout. The DETAILS
    block dumps ``reason.internal_details`` — PHI-free by SafeMessageError
    contract; the exception's constructor is the only entry point and
    every documented subclass keeps the safe-message discipline.
    """
    timestamp = datetime.now(tz=UTC).isoformat(timespec="seconds")
    incident_label = _incident_label(reason)
    rule = getattr(reason, "rule", "N/A")

    details_block = "\n".join(
        f"  {k}: {v}" for k, v in sorted(reason.internal_details.items())
    ) or "  (none)"

    drop_dir = _drop_dir(drop_date)
    lines = [
        "HHA Ventra ingest (row-level / stdspec) — quarantine reject reason",
        "===================================================================",
        "",
        f"INCIDENT CLASS: {incident_label}",
        "",
        f"RUN_ID:         {run_id}",
        f"CORRELATION_ID: {correlation_id}",
        f"TIMESTAMP:      {timestamp}",
        f"DROP_DATE:      {drop_date.isoformat()}",
        "",
        f"RULE:           {rule}",
        f"SAFE_MESSAGE:   {reason.safe_message}",
        "",
        "INTERNAL_DETAILS (PHI-free by SafeMessageError contract):",
        details_block,
        "",
        f"Original drop folder:   {VENDOR_INBOUND}/{drop_dir}/",
        f"This quarantine folder: {VENDOR_QUARANTINE}/{drop_dir}/",
        "",
        "Operator runbook:       docs/04-operations/RUNBOOK.md#ventra-stdspec-quarantine",
        "",
        (
            "DO NOT delete files from this folder. Lifecycle policy reaps "
            "after the configured window (30 days for vendor-inbound/ventra/"
            "stdspec; vendor-quarantine retention TBD by follow-up Bicep)."
        ),
        "",
    ]
    return "\n".join(lines).encode("utf-8")


async def quarantine_drop(
    drop_date: date,
    reason: SafeMessageError,
    run_id: uuid.UUID,
    correlation_id: uuid.UUID,
) -> None:
    """Copy every file in the inbound drop folder to vendor-quarantine,
    plus the ``_REJECT_REASON.txt`` sidecar.

    Server-side blob copy (not move): the operator might still want to
    re-trigger after Ventra pushes a corrected file. The inbound copy
    is the canonical source of truth until it ages out under the H2
    30-day lifecycle policy.

    PHI-safety contract:
      - The sidecar contains ``reason.safe_message`` + ``reason.internal_details``
        only. Both fields are PHI-free by the ``SafeMessageError`` base
        class's documented constructor obligation.
      - The blob copies preserve the inbound CSV content exactly (which
        contains the PHI columns Ventra sent). The 30-day lifecycle on
        the inbound prefix + the quarantine retention policy together
        constrain PHI residency to the documented window.
      - No raw row content is read or written by this function — only
        blob-level copy + sidecar upload.
    """
    drop_dir = _drop_dir(drop_date)
    listed = await blob.list_by_prefix(
        container_name=VENDOR_INBOUND,
        prefix=f"{drop_dir}/",
        include_metadata=False,
    )
    for entry in listed:
        # e.g. 'ventra/stdspec/2026-06-03/invoice.csv'
        source_name = entry["name"]
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
            "rule": str(getattr(reason, "rule", "N/A")),
            "incident_class": (
                "v15_phi_leak"
                if isinstance(reason, PHILeakError)
                else "adr_005"
                if isinstance(reason, ADRViolation)
                else "validation_failure"
            ),
        },
        overwrite=True,
    )


__all__ = [
    "REJECT_REASON_FILE",
    "VENDOR_INBOUND",
    "VENDOR_QUARANTINE",
    "VENTRA_STDSPEC_PREFIX",
    "quarantine_drop",
]
