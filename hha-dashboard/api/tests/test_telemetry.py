"""App Insights / OTel wiring + request-id correlation tests.

Audit ticket T6 lock-in:
- `setup_telemetry` is a no-op when `applicationinsights_connection_string`
  is empty (default state for dev / test).
- `setup_telemetry` calls `configure_azure_monitor` exactly once when the
  connection string is set.
- The request-id middleware tags every response with `X-Correlation-Id`,
  generates a uuid when no caller header is supplied, and echoes the
  caller-supplied value when present.
- Exception handlers prefer the bound `request_id` over generating a new
  uuid — so the same id appears in logs, response body, and response
  header for any single request.
"""

from __future__ import annotations

import re
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

from app.core import telemetry
from app.main import app

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def test_setup_telemetry_no_op_when_unset() -> None:
    """When the connection string is empty (default), setup_telemetry returns
    cleanly and does NOT import or call configure_azure_monitor."""
    with (
        patch.object(telemetry.settings, "applicationinsights_connection_string", ""),
        patch("azure.monitor.opentelemetry.configure_azure_monitor") as mock_cfg,
    ):
        telemetry.setup_telemetry(app)
    mock_cfg.assert_not_called()


def test_setup_telemetry_calls_azure_monitor_when_set() -> None:
    """When the connection string is set, configure_azure_monitor is called
    with that exact value, and FastAPIInstrumentor wires the app."""
    fake_conn = (
        "InstrumentationKey=00000000-0000-0000-0000-000000000000;"
        "IngestionEndpoint=https://eastus2-0.in.applicationinsights.azure.com/"
    )
    with (
        patch.object(
            telemetry.settings,
            "applicationinsights_connection_string",
            fake_conn,
        ),
        patch("azure.monitor.opentelemetry.configure_azure_monitor") as mock_cfg,
        patch(
            "opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app"
        ) as mock_instr,
    ):
        telemetry.setup_telemetry(app)
    mock_cfg.assert_called_once_with(connection_string=fake_conn)
    mock_instr.assert_called_once()


def test_request_id_middleware_generates_uuid_when_no_header() -> None:
    """A caller that doesn't send X-Correlation-Id gets a server-generated
    uuid back in the response header."""
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert "x-correlation-id" in resp.headers
    # Must be a parseable uuid4
    UUID(resp.headers["x-correlation-id"])
    assert UUID_RE.match(resp.headers["x-correlation-id"])


def test_request_id_middleware_echoes_caller_header() -> None:
    """A caller that pins X-Correlation-Id gets that exact value back —
    enables cross-service tracing where an upstream gateway picks the id
    once and threads it through every hop."""
    pinned = "test-correlation-id-2026-04-27"
    with TestClient(app) as client:
        resp = client.get("/health", headers={"X-Correlation-Id": pinned})
    assert resp.status_code == 200
    assert resp.headers["x-correlation-id"] == pinned


def test_request_id_propagates_to_exception_handler() -> None:
    """Triggers a 404 (HTTPException raised by routers/operations.py:36 when
    a site_id doesn't exist) with a pinned correlation id and asserts the
    response body's `correlation_id` matches what the middleware bound.
    Confirms the exception handler reads the bound id rather than
    generating a fresh one."""
    pinned = "exception-handler-correlation-id"
    with TestClient(app) as client:
        # site_id 999999 doesn't exist → operations router raises
        # HTTPException(404), which flows through the HTTPException handler
        # we updated.
        resp = client.get(
            "/api/v1/operations/sites/999999",
            headers={"X-Correlation-Id": pinned},
        )
    assert resp.status_code == 404
    body = resp.json()
    assert body["correlation_id"] == pinned
    assert resp.headers["x-correlation-id"] == pinned


# ----- setup_telemetry ImportError fallback (Phase 3 gap-fill) -----


def test_setup_telemetry_handles_missing_optional_deps() -> None:
    """If a dev forgot ``uv sync`` and azure-monitor-opentelemetry is not
    installed, the app must still start — setup_telemetry catches
    ImportError, logs telemetry.import_failed, and returns. Without this
    guard, ``uvicorn app.main:app`` would crash on import."""
    fake_conn = "InstrumentationKey=00000000-0000-0000-0000-000000000000"

    # Patch the import-machinery so the lazy import inside setup_telemetry
    # raises ImportError. Patching builtins.__import__ is the standard way
    # to fault-inject a missing dependency.
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _raising_import(
        name: str, globals_: object = None, locals_: object = None, fromlist: object = (), level: int = 0
    ) -> object:
        if name.startswith("azure.monitor.opentelemetry"):
            raise ImportError("simulated missing dep")
        return real_import(name, globals_, locals_, fromlist, level)

    with (
        patch.object(
            telemetry.settings, "applicationinsights_connection_string", fake_conn
        ),
        patch("builtins.__import__", side_effect=_raising_import),
    ):
        # No raise; logs the warning and returns.
        telemetry.setup_telemetry(app)


# ----- setup_telemetry_for_job (Phase 1B C14 job-mode entrypoint) -----


def test_setup_telemetry_for_job_no_op_when_unset() -> None:
    """Same no-op contract as setup_telemetry, but the log carries
    mode='job' so operators can distinguish web vs job startup events."""
    with (
        patch.object(telemetry.settings, "applicationinsights_connection_string", ""),
        patch("azure.monitor.opentelemetry.configure_azure_monitor") as mock_cfg,
    ):
        telemetry.setup_telemetry_for_job()
    mock_cfg.assert_not_called()


def test_setup_telemetry_for_job_calls_configure_when_set() -> None:
    """When connection string is set, configure_azure_monitor is called.
    Critically, FastAPIInstrumentor is NOT called (jobs have no FastAPI
    app to instrument)."""
    fake_conn = (
        "InstrumentationKey=00000000-0000-0000-0000-000000000000;"
        "IngestionEndpoint=https://eastus2-0.in.applicationinsights.azure.com/"
    )
    with (
        patch.object(
            telemetry.settings,
            "applicationinsights_connection_string",
            fake_conn,
        ),
        patch("azure.monitor.opentelemetry.configure_azure_monitor") as mock_cfg,
        patch(
            "opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app"
        ) as mock_instr,
    ):
        telemetry.setup_telemetry_for_job()

    mock_cfg.assert_called_once_with(connection_string=fake_conn)
    # Critical: NO FastAPI instrumentation in job mode
    mock_instr.assert_not_called()


def test_setup_telemetry_for_job_handles_missing_optional_deps() -> None:
    """Container Apps Job with missing azure-monitor-opentelemetry must
    not crash on startup — same import-fault tolerance as the web variant."""
    fake_conn = "InstrumentationKey=00000000-0000-0000-0000-000000000000"
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _raising_import(
        name: str, globals_: object = None, locals_: object = None, fromlist: object = (), level: int = 0
    ) -> object:
        if name.startswith("azure.monitor.opentelemetry"):
            raise ImportError("simulated missing dep")
        return real_import(name, globals_, locals_, fromlist, level)

    with (
        patch.object(
            telemetry.settings, "applicationinsights_connection_string", fake_conn
        ),
        patch("builtins.__import__", side_effect=_raising_import),
    ):
        # No raise.
        telemetry.setup_telemetry_for_job()
