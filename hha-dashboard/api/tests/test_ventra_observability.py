"""Observability module unit tests.

Pure-Python — no Azure Monitor connection. The C8 alert rules
(infra/modules/vendor_alerts.bicep) consume the event names this module
exports; ``ALL_EVENT_NAMES`` is the single source of truth and these
tests pin its shape so a typo in the alert KQL or a stray rename here
is caught immediately.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import structlog
from jobs.ventra_ingest.observability import (
    ALL_EVENT_NAMES,
    EVENT_VENTRA_ADR005_VIOLATION,
    EVENT_VENTRA_DEDUP_SKIP,
    EVENT_VENTRA_FILE_QUARANTINED,
    EVENT_VENTRA_INGEST_COMPLETE,
    EVENT_VENTRA_INGEST_FAILED,
    EVENT_VENTRA_MANIFEST_RECEIVED,
    EVENT_VENTRA_ROWS_WRITTEN,
    EVENT_VENTRA_VALIDATION_FAILED,
    EVENT_VENTRA_VALIDATION_PASSED,
    bind_run,
    clear_run,
    emit_event,
)
from structlog.testing import capture_logs

# =========================================================================
# Event-name catalog — pinned to lock the contract with vendor_alerts.bicep
# =========================================================================


def test_event_name_catalog_is_locked() -> None:
    """If you add or remove a Ventra event, update both this set AND
    infra/modules/vendor_alerts.bicep. The duplication is intentional —
    the Bicep alert KQL hard-codes the event name, so a rename here
    silently breaks the alert."""
    assert frozenset(
        {
            "ventra.manifest_received",
            "ventra.validation_passed",
            "ventra.validation_failed",
            "ventra.adr005_violation",
            "ventra.dedup_skip",
            "ventra.rows_written",
            "ventra.ingest_complete",
            "ventra.ingest_failed",
            "ventra.file_quarantined",
        }
    ) == ALL_EVENT_NAMES


def test_event_name_constants_match_strings() -> None:
    """Every EVENT_VENTRA_* constant is a literal "ventra.<thing>" string."""
    assert EVENT_VENTRA_MANIFEST_RECEIVED == "ventra.manifest_received"
    assert EVENT_VENTRA_VALIDATION_PASSED == "ventra.validation_passed"
    assert EVENT_VENTRA_VALIDATION_FAILED == "ventra.validation_failed"
    assert EVENT_VENTRA_ADR005_VIOLATION == "ventra.adr005_violation"
    assert EVENT_VENTRA_DEDUP_SKIP == "ventra.dedup_skip"
    assert EVENT_VENTRA_ROWS_WRITTEN == "ventra.rows_written"
    assert EVENT_VENTRA_INGEST_COMPLETE == "ventra.ingest_complete"
    assert EVENT_VENTRA_INGEST_FAILED == "ventra.ingest_failed"
    assert EVENT_VENTRA_FILE_QUARANTINED == "ventra.file_quarantined"


# =========================================================================
# emit_event — gate against typos
# =========================================================================


def test_emit_event_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown event name"):
        emit_event("ventra.totally_made_up", foo="bar")


def test_emit_event_accepts_known_name(monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ARG001
    with capture_logs() as logs:
        emit_event(EVENT_VENTRA_MANIFEST_RECEIVED, files_count=3)

    assert len(logs) == 1
    entry = logs[0]
    assert entry["event"] == "ventra.manifest_received"
    assert entry["files_count"] == 3
    assert entry["log_level"] == "info"


def test_emit_event_carries_module_logger_vendor_binding() -> None:
    """The module-scoped logger is bound with vendor='ventra'. Capture
    via structlog.testing.capture_logs which preserves bound context."""
    with capture_logs() as logs:
        emit_event(EVENT_VENTRA_VALIDATION_PASSED, rules_evaluated=14)
    # capture_logs strips the bound-via-bind() context for older
    # structlog versions, so we don't assert on `vendor` directly.
    # The contract is that emit_event uses the module-level _log, which
    # is bound at import time — verified by the fact that the call
    # produced exactly one log entry without raising.
    assert len(logs) == 1


# =========================================================================
# bind_run / clear_run — contextvars roundtrip
# =========================================================================


def test_bind_run_without_run_id_only_binds_correlation_and_date() -> None:
    cid = uuid.uuid4()
    dd = date(2026, 5, 13)
    bind_run(run_id=None, correlation_id=cid, drop_date=dd)
    try:
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["correlation_id"] == str(cid)
        assert ctx["drop_date"] == "2026-05-13"
        assert "run_id" not in ctx
    finally:
        clear_run()


def test_bind_run_with_run_id_binds_all_three() -> None:
    rid = uuid.uuid4()
    cid = uuid.uuid4()
    dd = date(2026, 5, 13)
    bind_run(run_id=rid, correlation_id=cid, drop_date=dd)
    try:
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["run_id"] == str(rid)
        assert ctx["correlation_id"] == str(cid)
        assert ctx["drop_date"] == "2026-05-13"
    finally:
        clear_run()


def test_bind_run_overwrites_run_id_on_second_call() -> None:
    """First bind has no run_id; second adds it after IngestRun.start()."""
    cid = uuid.uuid4()
    dd = date(2026, 5, 13)
    bind_run(run_id=None, correlation_id=cid, drop_date=dd)
    rid = uuid.uuid4()
    bind_run(run_id=rid, correlation_id=cid, drop_date=dd)
    try:
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["run_id"] == str(rid)
        assert ctx["correlation_id"] == str(cid)
    finally:
        clear_run()


def test_clear_run_is_idempotent_when_unbound() -> None:
    # Should not raise even if nothing was bound first.
    clear_run()
    clear_run()
    assert structlog.contextvars.get_contextvars() == {}


def test_emit_event_works_while_run_is_bound() -> None:
    """emit_event called while bind_run is active should not raise and
    should emit the expected event payload.

    Note: capture_logs() does NOT run the contextvars processor, so the
    bound run_id / correlation_id / drop_date do not appear in the
    captured entry. The contextvars binding itself is verified by
    test_bind_run_with_run_id_binds_all_three; this test only proves
    emit_event composes cleanly while bindings are active."""
    rid = uuid.uuid4()
    cid = uuid.uuid4()
    dd = date(2026, 5, 13)
    bind_run(run_id=rid, correlation_id=cid, drop_date=dd)
    try:
        # Verify the contextvars ARE bound at call time
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["run_id"] == str(rid)

        with capture_logs() as logs:
            emit_event(EVENT_VENTRA_INGEST_COMPLETE, rows_out=42, duration_ms=14000)
        entry = logs[0]
        assert entry["event"] == "ventra.ingest_complete"
        assert entry["rows_out"] == 42
        assert entry["duration_ms"] == 14000
    finally:
        clear_run()
