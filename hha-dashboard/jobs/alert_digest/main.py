"""Daily alert digest cron.

Runs once per weekday morning (cron: `0 11 * * 1-5` UTC ≈ 07:00 ET).
Computes yesterday's variance flags from `services.alert_engine`, looks up
who's subscribed at `frequency='daily'`, sends one HTML email per
(alert × recipient) pair, persists to `alerts.alert_log` for idempotency.

Re-running on the same target date is a no-op for already-sent rows.

When `settings.email_configured` is False (no ACS env), the job exits 0
cleanly with a single log line — same pattern as `paycom_sync`.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent.parent / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from sqlalchemy import select  # noqa: E402

from app.deps import SessionLocal  # noqa: E402
from app.models.alerts import AlertLog, AlertSubscription  # noqa: E402
from app.services import alert_engine  # noqa: E402
from app.services.audit import set_current_upn  # noqa: E402
from app.services.email import email_service, render_email_template  # noqa: E402
from app.settings import settings  # noqa: E402

SERVICE_UPN = "alert-digest@hhamedicine.com"

# Color map matches the in-app `<AlertBanner>` palette.
_SEVERITY_COLORS = {
    "red": "#dc2626",
    "yellow": "#f59e0b",
    "blue": "#2563eb",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("jobs.alert_digest")


async def run(target_date: date | None = None) -> int:
    """Returns exit code (0 = success, non-zero = error).

    `target_date` defaults to yesterday so the 07:00 ET / 11:00 UTC cron
    summarizes the prior business day.
    """
    if not settings.email_configured:
        log.info(
            "Email not configured — exiting cleanly (no-op). "
            "Set AZURE_COMMUNICATION_SENDER + AZURE_COMMUNICATION_ENDPOINT "
            "(or _CONNECTION_STRING) to enable.",
        )
        return 0

    target = target_date or (datetime.now(UTC).date() - timedelta(days=1))
    set_current_upn(SERVICE_UPN)

    async with SessionLocal() as db:
        candidates = await alert_engine.compute_alerts_for_date(db, target)

    if not candidates:
        log.info("No alerts for %s — nothing to send.", target.isoformat())
        return 0

    async with SessionLocal() as db:
        subscribers = (
            await db.execute(
                select(AlertSubscription).where(AlertSubscription.frequency == "daily")
            )
        ).scalars().all()

    if not subscribers:
        log.warning(
            "No daily-frequency subscribers — %d alerts unrouted. "
            "Run scripts/seed_alert_subscriptions.py to add recipients.",
            len(candidates),
        )
        return 0

    sent_count = 0
    skipped_count = 0
    error_count = 0

    for alert in candidates:
        # Subscribers with empty `categories` get every category;
        # otherwise only the matching ones.
        for sub in subscribers:
            if sub.categories and alert.category not in sub.categories:
                continue

            already_sent = await _check_already_sent(
                alert_id=alert.id,
                target_date=target,
                recipient_email=sub.email,
            )
            if already_sent:
                skipped_count += 1
                continue

            try:
                html = render_email_template(
                    "alert_digest.html.j2",
                    target_date=target.isoformat(),
                    alerts=[alert.as_dict()],
                    severity_colors=_SEVERITY_COLORS,
                )
                msg_id = await email_service.send_html_email(
                    to=sub.email,
                    subject=f"[HHA] {alert.title}",
                    html_body=html,
                )
                await _record_sent(
                    alert=alert,
                    target_date=target,
                    recipient_email=sub.email,
                    acs_message_id=msg_id,
                )
                sent_count += 1
            except Exception:
                log.exception(
                    "Failed sending alert %s to %s — continuing.",
                    alert.id,
                    sub.email,
                )
                error_count += 1

    log.info(
        "Done: target=%s sent=%d skipped=%d errors=%d",
        target.isoformat(),
        sent_count,
        skipped_count,
        error_count,
    )
    return 1 if error_count > 0 and sent_count == 0 else 0


async def _check_already_sent(
    *, alert_id: str, target_date: date, recipient_email: str
) -> bool:
    async with SessionLocal() as db:
        existing = (
            await db.execute(
                select(AlertLog.id).where(
                    AlertLog.alert_id == alert_id,
                    AlertLog.target_date == target_date,
                    AlertLog.recipient_email == recipient_email,
                )
            )
        ).scalar_one_or_none()
        return existing is not None


async def _record_sent(
    *,
    alert: alert_engine.AlertCandidate,
    target_date: date,
    recipient_email: str,
    acs_message_id: str | None,
) -> None:
    async with SessionLocal() as db:
        db.add(
            AlertLog(
                alert_id=alert.id,
                target_date=target_date,
                severity=alert.severity,
                category=alert.category,
                recipient_email=recipient_email,
                sent_at=datetime.now(UTC),
                acs_message_id=acs_message_id,
            )
        )
        await db.commit()


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
