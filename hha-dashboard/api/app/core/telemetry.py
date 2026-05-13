"""OpenTelemetry / Application Insights wiring for the HHA Dashboard API.

When `settings.applicationinsights_connection_string` is set, this module
calls `configure_azure_monitor()` once at lifespan startup. That single
call sets up the Azure Monitor OTel exporter and triggers auto-
instrumentation for FastAPI (incoming HTTP), SQLAlchemy / asyncpg
(outgoing DB queries), and the structlog → OTel logs bridge.

When the connection string is empty, every dashboard / cron read still
works — telemetry is just a no-op. Mirrors the `email_configured` /
`paycom_configured` short-circuit pattern.

Audit ticket T6.

Why pin the connection string in `settings` (not just env): the existing
codebase reads everything else through `settings.*`. Tests and main.py
benefit from a single source of truth that respects the .env file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..settings import settings
from .logging import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI

log = get_logger(__name__)


def setup_telemetry(app: FastAPI) -> None:
    """Initialize Azure Monitor OTel exporter + FastAPI auto-instrumentation.

    No-op when `settings.applicationinsights_connection_string` is empty.
    Logs a single info-level event ("telemetry.disabled" / "telemetry.enabled")
    so operators can confirm what mode the api is running in by grepping
    App Service stdout.

    Idempotent within a process — calling twice is harmless because both
    `configure_azure_monitor` and `FastAPIInstrumentor.instrument_app`
    detect their own prior wiring.
    """
    if not settings.telemetry_configured:
        log.info(
            "telemetry.disabled",
            reason="applicationinsights_connection_string unset",
        )
        return

    # Lazy import. The deps are pinned in pyproject.toml but a dev who
    # installed without `uv sync` would otherwise see this module fail to
    # import on app startup. Lazy-import + fallback log gives a clear
    # remediation path.
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError as exc:
        log.warning(
            "telemetry.import_failed",
            reason="azure-monitor-opentelemetry not installed; run `uv sync`",
            exc_type=type(exc).__name__,
        )
        return

    configure_azure_monitor(
        connection_string=settings.applicationinsights_connection_string,
    )
    FastAPIInstrumentor.instrument_app(app)

    log.info("telemetry.enabled")


def setup_telemetry_for_job() -> None:
    """Initialize Azure Monitor OTel exporter for a Container Apps Job.

    Same as ``setup_telemetry()`` but without the FastAPI instrumentation
    hook — jobs do not have a FastAPI app to instrument. SQLAlchemy /
    asyncpg / structlog → logs bridge are still auto-instrumented via
    ``configure_azure_monitor()``.

    Idempotent within a process. No-op when
    ``settings.applicationinsights_connection_string`` is empty.
    """
    if not settings.telemetry_configured:
        log.info(
            "telemetry.disabled",
            reason="applicationinsights_connection_string unset",
            mode="job",
        )
        return

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError as exc:
        log.warning(
            "telemetry.import_failed",
            reason="azure-monitor-opentelemetry not installed; run `uv sync`",
            exc_type=type(exc).__name__,
        )
        return

    configure_azure_monitor(
        connection_string=settings.applicationinsights_connection_string,
    )
    log.info("telemetry.enabled", mode="job")
