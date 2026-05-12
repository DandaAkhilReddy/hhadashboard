"""Observability wiring for the Ventra ingest Container Apps Job.

Thin layer over ``app.core.telemetry.setup_telemetry_for_job`` and
``app.core.logging.configure_logging``. Provides:

  - ``init_telemetry()`` — one-call startup that wires both
    structlog (JSON + PII redaction) and Azure Monitor OTel (when the
    connection string is set; no-op otherwise).
  - ``bind_run(run_id, correlation_id, drop_date)`` — binds the
    canonical job-scoped contextvars so every subsequent log line and
    custom event carries them automatically.
  - ``EVENT_VENTRA_*`` constants — the App Insights custom-event names
    per Phase 1A.A9 of the plan. Locked here so the C8 alert rules
    (vendor_alerts.bicep) and the orchestrator (C16) share one source
    of truth.
  - ``emit_event(name, **kwargs)`` — thin wrapper over
    ``logger.info(name, ...)``. structlog → OTel bridge ingests INFO
    logs as custom events when telemetry is enabled.

Why a separate module (not just import structlog directly): the bind /
emit / event-name constants want to live near each other. A future
upload_ingest revamp can adopt the same pattern.
"""

from __future__ import annotations

import uuid
from datetime import date

import structlog

from app.core.logging import configure_logging, get_logger
from app.core.telemetry import setup_telemetry_for_job


# =========================================================================
# Custom event names — must match the KQL alert rules in
# infra/modules/vendor_alerts.bicep (C8). Adding a new event = update both.
# =========================================================================

EVENT_VENTRA_MANIFEST_RECEIVED = "ventra.manifest_received"
EVENT_VENTRA_VALIDATION_PASSED = "ventra.validation_passed"
EVENT_VENTRA_VALIDATION_FAILED = "ventra.validation_failed"
EVENT_VENTRA_ADR005_VIOLATION = "ventra.adr005_violation"
EVENT_VENTRA_DEDUP_SKIP = "ventra.dedup_skip"
EVENT_VENTRA_ROWS_WRITTEN = "ventra.rows_written"
EVENT_VENTRA_INGEST_COMPLETE = "ventra.ingest_complete"
EVENT_VENTRA_INGEST_FAILED = "ventra.ingest_failed"
EVENT_VENTRA_FILE_QUARANTINED = "ventra.file_quarantined"

ALL_EVENT_NAMES: frozenset[str] = frozenset(
    {
        EVENT_VENTRA_MANIFEST_RECEIVED,
        EVENT_VENTRA_VALIDATION_PASSED,
        EVENT_VENTRA_VALIDATION_FAILED,
        EVENT_VENTRA_ADR005_VIOLATION,
        EVENT_VENTRA_DEDUP_SKIP,
        EVENT_VENTRA_ROWS_WRITTEN,
        EVENT_VENTRA_INGEST_COMPLETE,
        EVENT_VENTRA_INGEST_FAILED,
        EVENT_VENTRA_FILE_QUARANTINED,
    }
)


# Module-scoped logger. Bind on import so even early failures (before
# init_telemetry()) still carry vendor='ventra'.
_log = get_logger("jobs.ventra_ingest").bind(vendor="ventra")


def init_telemetry(log_level: str = "INFO") -> None:
    """One-call startup for the job: structlog JSON config + Azure
    Monitor OTel exporter (no-op when the connection string is empty).

    Call this exactly once from ``jobs.ventra_ingest.main:main`` before
    any other work. Idempotent within a process.
    """
    configure_logging(log_level)
    setup_telemetry_for_job()


def bind_run(
    *,
    run_id: uuid.UUID | None,
    correlation_id: uuid.UUID,
    drop_date: date,
) -> None:
    """Bind job-scoped context onto structlog so every subsequent log
    line carries (run_id, correlation_id, drop_date) automatically.

    Call this twice per drop:
      1. Right after parsing the Event Grid payload, with ``run_id=None``
         + a fresh ``correlation_id`` so any failure before ``IngestRun.start()``
         is still traceable.
      2. After ``IngestRun.start()`` returns, with the allocated ``run_id``.

    ``contextvars.bind_contextvars()`` merges on top of any existing
    bindings — calling twice with the same key overwrites.
    """
    bindings: dict[str, str] = {
        "correlation_id": str(correlation_id),
        "drop_date": drop_date.isoformat(),
    }
    if run_id is not None:
        bindings["run_id"] = str(run_id)
    structlog.contextvars.bind_contextvars(**bindings)


def clear_run() -> None:
    """Tear down all contextvars at the end of a job execution. Safe to
    call from a ``finally:`` block; idempotent on an unbound context."""
    structlog.contextvars.clear_contextvars()


def emit_event(name: str, **kwargs: object) -> None:
    """Emit a Ventra custom event.

    structlog INFO logs are auto-ingested into App Insights as custom
    events via the OTel logs bridge wired by ``configure_azure_monitor``.
    No explicit ``track_event()`` call needed.

    ``name`` must be one of the ``EVENT_VENTRA_*`` constants — asserted
    so a typo in C16 fails fast in tests rather than emitting a
    silently-orphaned event the C8 KQL alerts will never match.

    Keys bound by ``bind_run`` (run_id, correlation_id, drop_date) are
    automatically merged onto every event via the structlog
    contextvars processor.
    """
    if name not in ALL_EVENT_NAMES:
        raise ValueError(
            f"emit_event: unknown event name {name!r}; "
            f"add it to ALL_EVENT_NAMES + vendor_alerts.bicep if it's a new rule"
        )
    _log.info(name, **kwargs)
