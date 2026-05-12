"""Exception hierarchy for the Ventra ingest job.

The ``rule`` attribute on ValidationError matches the V1-V14 catalog in
docs/03-engineering/INGESTION_VENTRA.md and the architecture lock in
``so-now-we-are-nested-grove.md`` §Phase 1A.A5. The main orchestrator
routes by exception type:

  ADRViolation  -> incident path (V12 only), emits ventra.adr005_violation
                   custom event, sends incident email, deletes queue
                   message (do not retry an ADR-005 violation — it is a
                   vendor data-quality incident, not a transient failure).
  ValidationError (non-ADR)
                -> quarantine path (V1-V11, V13), emits
                   ventra.validation_failed, sends quarantine email,
                   deletes queue message.
  DedupSkip     -> success path (V13 idempotent re-delivery), emits
                   ventra.dedup_skip, no email, deletes queue message.
  Exception (any other)
                -> failure path, emits ventra.ingest_failed, sends failure
                   email, does NOT delete queue message (let KEDA retry up
                   to replicaRetryLimit before dead-lettering).

The ``details`` dict is JSON-serialized into ``ops.ingest_run.error_details``
(JSONB column from migration 0012). Keep it PHI-free — the pre-aggregated
file shape has no PHI, but a future bug could leak a row in here if we are
not careful. Defensive scrubbing of unknown keys is not done; callers must
only pass known-safe fields.
"""

from __future__ import annotations

from typing import Any


class ValidationError(Exception):
    """Raised when a V1-V14 validator rejects a drop.

    The ``rule`` attribute names the specific rule that fired (e.g. ``"V5"``,
    ``"V12"``). The ``details`` dict carries structured context for the
    operator alert and the ``ops.ingest_run.error_details`` audit row.
    """

    def __init__(
        self,
        rule: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{rule}: {message}")
        self.rule = rule
        self.message = message
        self.details = details or {}


class ADRViolation(ValidationError):
    """V12 only — non-Florida facility_no in a Ventra drop.

    Per ADR-005, the Ventra contract is FL-only. Any TX facility appearing
    in a drop is treated as an incident (not just a quarantine) because it
    indicates either (a) Ventra's source-side FL filter is broken, or
    (b) HHA's contract scope drifted without an ADR amendment. Either way,
    immediate triage via SECURITY_INCIDENT_PLAYBOOK.

    Carries the same shape as ValidationError so the main orchestrator's
    except chain catches the subclass first (Python MRO).
    """

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(rule="V12", message=message, details=details)


class DedupSkip(Exception):
    """V13 idempotent re-delivery — every file's (file_name, sha256) is
    already in ``ops.processed_files`` for this drop. Not an error; the
    orchestrator logs ``ventra.dedup_skip``, closes the ingest_run row as
    succeeded with a note, and deletes the queue message."""

    def __init__(self, drop_date: str, files: list[str]) -> None:
        super().__init__(
            f"dedup_skip drop_date={drop_date} files={','.join(files)}"
        )
        self.drop_date = drop_date
        self.files = files
