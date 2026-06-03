"""Exception hierarchy for the row-level (Standard Spec) Ventra ingest job.

Every exception this pipeline raises descends from ``SafeMessageError``,
which separates two payloads:

  ``safe_message``      — PHI-free text safe to flow into ACS Email,
                          structlog output, App Insights events, the
                          ``_REJECT_REASON.txt`` quarantine sidecar, and
                          the ``ops.ingest_run.error_message`` column.

  ``internal_details``  — structured context including filename, line
                          number, sha256 prefix, etc. Lands in the
                          JSONB ``ops.ingest_run.error_details`` column.
                          Must NEVER contain raw row content; the V15
                          denial layer in ``phi.py`` enforces this at
                          construction time.

The separation exists because the pre-aggregated pipeline's exception
shape (``message`` + ``details``) was designed against the architecture
lock that promised zero PHI on the wire. The row-level pipeline cannot
make that promise — Ventra writes PHI columns into the inbound CSVs;
the V15 strip layer removes them before any DB / log / telemetry hop.
A bare ``message`` on an exception is too easy to populate with raw row
content; ``safe_message`` is a named obligation the caller cannot miss.

Routing in main.py mirrors the pre-aggregated path:

  ADRViolation       -> incident path (V12 only). Page on-call + run
                        SECURITY_INCIDENT_PLAYBOOK. Delete queue
                        message (do not retry a vendor data-quality
                        incident).
  PHILeakError       -> incident path. ANY V15 detection past the strip
                        layer is a HIPAA-reportable event. Quarantine
                        + page on-call + immediate deploy revert.
  ValidationError    -> quarantine path (V1-V11, V13, V14, V15-pre-strip).
                        Email ops; delete queue message.
  DedupSkip          -> success path (V13 idempotent re-delivery).
                        Log only; delete queue message.
  Any other          -> failure path. Do not delete queue message; let
                        KEDA retry up to replicaRetryLimit before DLQ.
"""

from __future__ import annotations

from typing import Any


class SafeMessageError(Exception):
    """Base class for every exception this pipeline raises.

    The ``safe_message`` is the only field that gets written to any
    PHI-sensitive surface (email, telemetry, log, sidecar). It must be
    a string the caller has already verified to be PHI-free — typically
    by referencing only column names, drop dates, file names, sha256
    prefixes, and integer counts (never row values).

    The ``internal_details`` dict is for the JSONB error_details column
    on ``ops.ingest_run``. The same PHI-free obligation applies — the
    DB is in HHA's HIPAA boundary, but every column is still classified
    Tier-A by ADR-001 and must never carry patient identifiers. Defensive
    PHI denial happens at construction time when this base class is
    instantiated; subclasses inherit that protection automatically.
    """

    def __init__(
        self,
        safe_message: str,
        internal_details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message
        self.internal_details = internal_details or {}

    def __str__(self) -> str:
        return self.safe_message


class ValidationError(SafeMessageError):
    """Raised when a V1-V15 validator rejects a drop.

    The ``rule`` attribute names the specific rule that fired. V15 is
    the row-level-specific addition (forbidden-column denial at four
    layers — see ``phi.py``); the rest mirror the pre-aggregated
    catalog.
    """

    def __init__(
        self,
        rule: str,
        safe_message: str,
        internal_details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(safe_message=f"{rule}: {safe_message}", internal_details=internal_details)
        self.rule = rule
        # Plain message without the rule prefix, in case callers want it
        # for an email subject line where the rule is rendered separately.
        self.bare_message = safe_message


class ADRViolation(ValidationError):  # noqa: N818  -- name mirrors PR #54 ventra_ingest module
    """V12 only — non-Florida facility_no in a Ventra drop.

    Same ADR-005 invariant as the pre-aggregated path. Raised before any
    DB write so the incident path can run cleanly.
    """

    def __init__(
        self,
        safe_message: str,
        internal_details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            rule="V12",
            safe_message=safe_message,
            internal_details=internal_details,
        )


class PHILeakError(SafeMessageError):
    """V15 detected PHI past the strip layer.

    Distinguished from ``ValidationError`` because the routing is
    different — a V15 violation past the strip layer is a hard incident
    that triggers on-call paging + immediate deploy revert + 24h
    HIPAA-reportability review. ``ValidationError(rule='V15')`` covers
    the BEFORE-strip case (file is missing the forbidden columns Ventra
    promised — schema drift). ``PHILeakError`` covers the AFTER-strip
    case (forbidden column survived the strip layer — code bug).
    """

    def __init__(
        self,
        layer: str,
        safe_message: str,
        internal_details: dict[str, Any] | None = None,
    ) -> None:
        # ``layer`` names where the leak was caught:
        #   "post_strip"     — V15 layer 2: in-memory record post-strip
        #   "pre_write"      — V15 layer 4: DB-bound aggregate
        #   "telemetry"      — V15 layer 3: App Insights span attr
        #   "log_emit"       — V15 layer (structlog processor)
        super().__init__(
            safe_message=f"V15 PHI leak at layer={layer}: {safe_message}",
            internal_details=internal_details,
        )
        self.layer = layer


class QuarantineError(SafeMessageError):
    """The quarantine copy step itself failed.

    Distinct from ValidationError — the original drop was already rejected
    for some other reason; this exception means we couldn't even move the
    files to the quarantine container. Operator needs to investigate
    blob-storage health before the next ingest can run.
    """


class DedupSkip(Exception):  # noqa: N818  -- name mirrors PR #54 ventra_ingest module
    """V13 idempotent re-delivery — every file's (file_name, sha256) is
    already in ``ops.processed_files`` for this drop. Not an error; the
    orchestrator logs ``ventra_stdspec.dedup_skip``, closes the
    ingest_run row as succeeded with a note, and deletes the queue
    message."""

    def __init__(self, drop_date: str, files: list[str]) -> None:
        super().__init__(
            f"dedup_skip drop_date={drop_date} files={','.join(files)}"
        )
        self.drop_date = drop_date
        self.files = files


__all__ = [
    "ADRViolation",
    "DedupSkip",
    "PHILeakError",
    "QuarantineError",
    "SafeMessageError",
    "ValidationError",
]
