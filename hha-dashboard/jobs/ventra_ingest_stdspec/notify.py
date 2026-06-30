"""Operator notifications for the row-level pipeline.

Four notify functions matching the orchestrator's exit paths. All four
accept PHI-safe inputs only (safe_message + internal_details + the
run/correlation IDs + drop_date) — the SafeMessageError discipline
guarantees nothing PHI-shaped reaches the email body.

For the H13 commit these are **structlog log emitters only**. Real ACS
Email integration follows in a sibling commit alongside the Jinja2
templates (mirrors the pre-aggregated path's notify.py from PR #54).
The orchestrator already imports + calls these, so swapping the log
body for ``email_service.send_html_email(...)`` is a single-file change
once the H15-equivalent templates land.

The log-only path is operationally sufficient for the first
end-to-end dev smoke run — every notification appears in App Insights
under ``ventra_stdspec.notify_*`` events with the same fields the
email would carry. Ops can read App Insights until ACS is wired.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def notify_success(
    drop_date: date,
    rows_written: int,
    rows_by_table: dict[str, int],
    vendor_source_systems: list[str],
    duration_seconds: float,
    run_id: uuid.UUID,
    correlation_id: uuid.UUID,
    recipients: list[str],
) -> None:
    """Successful ingest — Crystal + Akhil get the daily summary."""
    logger.info(
        "ventra_stdspec.notify_success",
        drop_date=drop_date.isoformat(),
        rows_written=rows_written,
        rows_by_table=dict(rows_by_table),
        vendor_source_systems=vendor_source_systems,
        duration_seconds=round(duration_seconds, 2),
        run_id=str(run_id),
        correlation_id=str(correlation_id),
        recipients=recipients,
    )


async def notify_dedup_skip(
    drop_date: date,
    already_processed: list[str],
    run_id: uuid.UUID,
    correlation_id: uuid.UUID,
    recipients: list[str],
) -> None:
    """V13 dedup_skip — idempotent re-delivery, no DB writes happened."""
    logger.info(
        "ventra_stdspec.notify_dedup_skip",
        drop_date=drop_date.isoformat(),
        already_processed=already_processed,
        run_id=str(run_id),
        correlation_id=str(correlation_id),
        recipients=recipients,
    )


async def notify_quarantine(
    drop_date: date,
    rule: str,
    safe_message: str,
    internal_details: dict[str, Any],
    run_id: uuid.UUID,
    correlation_id: uuid.UUID,
    recipients: list[str],
) -> None:
    """V1-V14 / V15-pre-strip quarantine — ops list gets the triage hint."""
    logger.warning(
        "ventra_stdspec.notify_quarantine",
        drop_date=drop_date.isoformat(),
        rule=rule,
        safe_message=safe_message,
        internal_details=internal_details,
        run_id=str(run_id),
        correlation_id=str(correlation_id),
        recipients=recipients,
    )


async def notify_incident(
    drop_date: date,
    incident_class: str,
    safe_message: str,
    internal_details: dict[str, Any],
    run_id: uuid.UUID,
    correlation_id: uuid.UUID,
    recipients: list[str],
) -> None:
    """V12 (ADR-005) or V15 (PHI leak) — on-call + compliance.

    ``incident_class`` is one of:
      - 'adr_005'        — non-FL facility in a Ventra drop
      - 'v15_phi_leak'   — V15 detection past the strip layer

    Both route to the security playbook; the runbook step varies by
    incident_class.
    """
    logger.error(
        "ventra_stdspec.notify_incident",
        drop_date=drop_date.isoformat(),
        incident_class=incident_class,
        safe_message=safe_message,
        internal_details=internal_details,
        run_id=str(run_id),
        correlation_id=str(correlation_id),
        recipients=recipients,
    )


async def notify_failure(
    drop_date: date,
    error_type: str,
    error_message: str,
    run_id: uuid.UUID,
    correlation_id: uuid.UUID,
    recipients: list[str],
) -> None:
    """Unhandled exception — on-call gets the failure ping."""
    logger.error(
        "ventra_stdspec.notify_failure",
        drop_date=drop_date.isoformat(),
        error_type=error_type,
        error_message=error_message,
        run_id=str(run_id),
        correlation_id=str(correlation_id),
        recipients=recipients,
    )


__all__ = [
    "notify_dedup_skip",
    "notify_failure",
    "notify_incident",
    "notify_quarantine",
    "notify_success",
]
