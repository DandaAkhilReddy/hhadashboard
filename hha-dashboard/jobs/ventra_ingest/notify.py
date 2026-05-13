"""ACS Email notification wrappers for the Ventra ingest pipeline.

Four thin wrappers over ``app.services.email.email_service.send_html_email``
plus the four Jinja2 templates under
``api/app/services/email_templates/ventra_*.html.j2``. Each wrapper:

  1. Renders the appropriate template with the call-site context.
  2. Fans out to every recipient address (ACS Email's per-call API
     takes one ``to``; we call once per recipient).
  3. Returns the list of ACS message IDs (``[]`` when email isn't
     configured — short-circuit via ``email_service.is_configured``).

Recipient list comes from the ``ALERT_EMAIL_TO_OPS`` env var wired by
``infra/modules/containerjobs.bicep`` (C7). Main.py parses the env value
into a list and passes it here; we don't read env in this module so the
function is unit-testable without mocking ``os.environ``.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from app.services.email import email_service, render_email_template


def parse_recipients(value: str | None) -> list[str]:
    """Split a comma-separated recipient string from env into a clean list.

    Handles None / empty / whitespace. Used by main.py once at startup;
    exported so tests can exercise the same parsing.
    """
    if not value:
        return []
    return [r.strip() for r in value.split(",") if r.strip()]


async def _send_to_all(
    template: str,
    subject: str,
    context: dict[str, Any],
    recipients: list[str],
) -> list[str]:
    """Render once, send to every recipient. Returns the list of ACS
    message IDs (filtered to non-None — None means email not
    configured, which is a no-op log on email.py's side)."""
    if not recipients:
        return []
    html = render_email_template(template, **context)
    message_ids: list[str] = []
    for to in recipients:
        msg_id = await email_service.send_html_email(
            to=to, subject=subject, html_body=html
        )
        if msg_id:
            message_ids.append(msg_id)
    return message_ids


# =========================================================================
# Public notify_* functions — one per main-orchestrator outcome path
# =========================================================================


async def notify_success(
    *,
    drop_date: date,
    rows_written: int,
    rows_by_table: dict[str, int],
    vendor_source_systems: list[str],
    duration_seconds: float,
    run_id: uuid.UUID,
    correlation_id: uuid.UUID,
    recipients: list[str],
) -> list[str]:
    """Send the success summary email after ingest_drop returns cleanly."""
    return await _send_to_all(
        template="ventra_success.html.j2",
        subject=f"Ventra drop processed — {drop_date.isoformat()}",
        context={
            "drop_date": drop_date.isoformat(),
            "rows_written": rows_written,
            "rows_by_table": rows_by_table,
            "vendor_source_systems": vendor_source_systems,
            "duration_seconds": f"{duration_seconds:.1f}",
            "run_id": str(run_id),
            "correlation_id": str(correlation_id),
        },
        recipients=recipients,
    )


async def notify_quarantine(
    *,
    drop_date: date,
    rule: str,
    message: str,
    details: dict[str, Any],
    run_id: uuid.UUID,
    correlation_id: uuid.UUID,
    recipients: list[str],
) -> list[str]:
    """Send the quarantine email for any V1-V11 / V13 validation failure.

    For V12 (ADR-005), call ``notify_incident`` instead — distinct
    subject + body emphasizing the incident posture.
    """
    return await _send_to_all(
        template="ventra_quarantine.html.j2",
        subject=f"[ACTION REQUIRED] Ventra drop quarantined — {drop_date.isoformat()} (rule {rule})",
        context={
            "drop_date": drop_date.isoformat(),
            "rule": rule,
            "message": message,
            "details": details,
            "run_id": str(run_id),
            "correlation_id": str(correlation_id),
        },
        recipients=recipients,
    )


async def notify_failure(
    *,
    drop_date: date,
    error_type: str,
    error_message: str,
    run_id: uuid.UUID,
    correlation_id: uuid.UUID,
    recipients: list[str],
) -> list[str]:
    """Send the unhandled-failure email — distinct from quarantine. Used
    when ingest_drop raises something other than ValidationError /
    ADRViolation (e.g. DB connection failure, code bug)."""
    return await _send_to_all(
        template="ventra_failure.html.j2",
        subject=f"[URGENT] Ventra ingest failed — {drop_date.isoformat()}",
        context={
            "drop_date": drop_date.isoformat(),
            "error_type": error_type,
            "error_message": error_message,
            "run_id": str(run_id),
            "correlation_id": str(correlation_id),
        },
        recipients=recipients,
    )


async def notify_incident(
    *,
    drop_date: date,
    message: str,
    details: dict[str, Any],
    run_id: uuid.UUID,
    correlation_id: uuid.UUID,
    recipients: list[str],
) -> list[str]:
    """Send the V12 / ADR-005 incident email. Distinguished from a
    standard quarantine by the INCIDENT badge + security-playbook link
    in the body. Caller routes here from the ``except ADRViolation``
    branch BEFORE the generic ``except ValidationError`` branch (Python
    MRO catches the subclass first)."""
    return await _send_to_all(
        template="ventra_incident.html.j2",
        subject=f"[INCIDENT] ADR-005 violation — non-FL facility in Ventra drop {drop_date.isoformat()}",
        context={
            "drop_date": drop_date.isoformat(),
            "message": message,
            "details": details,
            "run_id": str(run_id),
            "correlation_id": str(correlation_id),
        },
        recipients=recipients,
    )
