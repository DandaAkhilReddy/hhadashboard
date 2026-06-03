"""Event-name catalog + structlog contextvar bindings for the row-level job.

Same shape as ``jobs/ventra_ingest/observability.py`` from PR #54 but
with a distinct event namespace (``ventra_stdspec.*``) so dashboards
can split metrics by pipeline. Adds two events that don't exist on the
pre-aggregated path:

  ``ventra_stdspec.phi_leak_detected``  — V15 layer 2/3/4 fired. Routes
                                           to the deploy-revert playbook.

  ``ventra_stdspec.phi_columns_stripped`` — Per-drop counter from the
                                            parser layer. Surfaces in
                                            the ingest_complete event;
                                            non-zero is the expected
                                            steady state.

All events flow through the PHI-safe structlog pipeline (H7's
``logging.py``) — keys are denylist-filtered and values are
SSN/DOB/phone/email-scrubbed before the JSON renderer. Callers cannot
accidentally leak PHI into telemetry through an event.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from datetime import date
from typing import Any

import structlog

# Event-name catalog. Pin the strings so dashboards + alert rules can
# reference them without string typos.
EVENT_VENTRA_STDSPEC_MANIFEST_RECEIVED = "ventra_stdspec.manifest_received"
EVENT_VENTRA_STDSPEC_VALIDATION_PASSED = "ventra_stdspec.validation_passed"
EVENT_VENTRA_STDSPEC_VALIDATION_FAILED = "ventra_stdspec.validation_failed"
EVENT_VENTRA_STDSPEC_DEDUP_SKIP = "ventra_stdspec.dedup_skip"
EVENT_VENTRA_STDSPEC_ROWS_WRITTEN = "ventra_stdspec.rows_written"
EVENT_VENTRA_STDSPEC_INGEST_COMPLETE = "ventra_stdspec.ingest_complete"
EVENT_VENTRA_STDSPEC_INGEST_FAILED = "ventra_stdspec.ingest_failed"
EVENT_VENTRA_STDSPEC_FILE_QUARANTINED = "ventra_stdspec.file_quarantined"
EVENT_VENTRA_STDSPEC_ADR005_VIOLATION = "ventra_stdspec.adr005_violation"
EVENT_VENTRA_STDSPEC_PHI_LEAK_DETECTED = "ventra_stdspec.phi_leak_detected"
EVENT_VENTRA_STDSPEC_PHI_COLUMNS_STRIPPED = "ventra_stdspec.phi_columns_stripped"

# All locked event names — used by tests + the observability dashboard
# to confirm the catalog is stable across releases.
KNOWN_EVENTS: frozenset[str] = frozenset(
    {
        EVENT_VENTRA_STDSPEC_MANIFEST_RECEIVED,
        EVENT_VENTRA_STDSPEC_VALIDATION_PASSED,
        EVENT_VENTRA_STDSPEC_VALIDATION_FAILED,
        EVENT_VENTRA_STDSPEC_DEDUP_SKIP,
        EVENT_VENTRA_STDSPEC_ROWS_WRITTEN,
        EVENT_VENTRA_STDSPEC_INGEST_COMPLETE,
        EVENT_VENTRA_STDSPEC_INGEST_FAILED,
        EVENT_VENTRA_STDSPEC_FILE_QUARANTINED,
        EVENT_VENTRA_STDSPEC_ADR005_VIOLATION,
        EVENT_VENTRA_STDSPEC_PHI_LEAK_DETECTED,
        EVENT_VENTRA_STDSPEC_PHI_COLUMNS_STRIPPED,
    }
)


# Run-scoped contextvars bound to every log line + emitted event via the
# structlog contextvar merge processor (already in app.core.logging).
# Bound at the start of process_one_message, cleared at the end.
_run_id: ContextVar[str | None] = ContextVar("ventra_stdspec_run_id", default=None)
_correlation_id: ContextVar[str | None] = ContextVar(
    "ventra_stdspec_correlation_id", default=None
)
_drop_date: ContextVar[str | None] = ContextVar(
    "ventra_stdspec_drop_date", default=None
)


def bind_run(
    run_id: uuid.UUID | None,
    correlation_id: uuid.UUID | None,
    drop_date: date | None,
) -> None:
    """Bind run-scoped context for all subsequent log lines + events.

    Called twice in the orchestrator: once before IngestRun.start() with
    run_id=None (correlation_id + drop_date only), and once after with
    the allocated run_id so it appears in every downstream log line.
    """
    structlog.contextvars.bind_contextvars(
        run_id=str(run_id) if run_id else None,
        correlation_id=str(correlation_id) if correlation_id else None,
        drop_date=drop_date.isoformat() if drop_date else None,
        ingest_path="stdspec",
    )
    if run_id is not None:
        _run_id.set(str(run_id))
    if correlation_id is not None:
        _correlation_id.set(str(correlation_id))
    if drop_date is not None:
        _drop_date.set(drop_date.isoformat())


def clear_run() -> None:
    """Clear the contextvars at the end of a processing cycle."""
    structlog.contextvars.unbind_contextvars(
        "run_id", "correlation_id", "drop_date", "ingest_path"
    )
    _run_id.set(None)
    _correlation_id.set(None)
    _drop_date.set(None)


def emit_event(name: str, **fields: Any) -> None:
    """Log a structured event.

    The structlog PHI processors (H7's logging.py) scrub the rendered
    output, so callers can pass through values that MIGHT contain
    PHI-shaped substrings without worrying about leakage in the
    rendered JSON. That said: don't deliberately pass PHI — the
    scrubber is defense in depth, not the primary contract.
    """
    if name not in KNOWN_EVENTS:
        # Don't reject — just log a warning so unknown event names
        # surface in operator review without blocking the job.
        structlog.get_logger(__name__).warning(
            "ventra_stdspec.unknown_event_name", attempted_name=name
        )
    structlog.get_logger(name).info(name, **fields)


__all__ = [
    "EVENT_VENTRA_STDSPEC_ADR005_VIOLATION",
    "EVENT_VENTRA_STDSPEC_DEDUP_SKIP",
    "EVENT_VENTRA_STDSPEC_FILE_QUARANTINED",
    "EVENT_VENTRA_STDSPEC_INGEST_COMPLETE",
    "EVENT_VENTRA_STDSPEC_INGEST_FAILED",
    "EVENT_VENTRA_STDSPEC_MANIFEST_RECEIVED",
    "EVENT_VENTRA_STDSPEC_PHI_COLUMNS_STRIPPED",
    "EVENT_VENTRA_STDSPEC_PHI_LEAK_DETECTED",
    "EVENT_VENTRA_STDSPEC_ROWS_WRITTEN",
    "EVENT_VENTRA_STDSPEC_VALIDATION_FAILED",
    "EVENT_VENTRA_STDSPEC_VALIDATION_PASSED",
    "KNOWN_EVENTS",
    "bind_run",
    "clear_run",
    "emit_event",
]
