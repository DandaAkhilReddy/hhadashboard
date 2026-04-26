"""Daily credential expiry scan.

Runs once daily (cron: `0 12 * * *` UTC). Scans `masters.credentials` for
items expiring within 90 days, buckets each into the tightest band it has
crossed (90 → 60 → 30), and emails `owner_clinical` subscribers with a
grouped table of physicians whose credentials need attention.

Idempotent via `alerts.credential_alert_log`: one row per (credential_id,
threshold_band). Re-firing requires the credential to roll into a tighter
band — no daily spam.

When `settings.email_configured` is False, exits 0 cleanly.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

API_DIR = Path(__file__).resolve().parent.parent.parent / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from sqlalchemy import select  # noqa: E402

from app.deps import SessionLocal  # noqa: E402
from app.models.alerts import AlertSubscription, CredentialAlertLog  # noqa: E402
from app.models.masters import Credential, Physician  # noqa: E402
from app.services.audit import set_current_upn  # noqa: E402
from app.services.email import email_service, render_email_template  # noqa: E402
from app.settings import settings  # noqa: E402

SERVICE_UPN = "cred-scan@hhamedicine.com"

# Tightest band wins. Days-to-expiry between [60+1, 90] → 90 band, etc.
_BANDS = (30, 60, 90)
_BAND_COLORS = {30: "#dc2626", 60: "#f59e0b", 90: "#2563eb"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("jobs.cred_scan")


def _band_for_days(days_to_expiry: int) -> int | None:
    """Return the tightest band a credential has crossed, or None if > 90 days."""
    if days_to_expiry <= 30:
        return 30
    if days_to_expiry <= 60:
        return 60
    if days_to_expiry <= 90:
        return 90
    return None


async def run(scan_date: date | None = None) -> int:
    if not settings.email_configured:
        log.info("Email not configured — exiting cleanly (no-op).")
        return 0

    today = scan_date or datetime.now(UTC).date()
    set_current_upn(SERVICE_UPN)

    cutoff = today + timedelta(days=90)

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(Credential, Physician)
                .join(Physician, Credential.physician_id == Physician.id)
                .where(
                    Credential.expires_on >= today,
                    Credential.expires_on <= cutoff,
                    Credential.status == "ACTIVE",
                )
                .order_by(Credential.expires_on)
            )
        ).all()

    if not rows:
        log.info("No credentials expiring in 90 days as of %s.", today.isoformat())
        return 0

    items_to_alert: list[dict[str, Any]] = []
    for cred, phys in rows:
        days = (cred.expires_on - today).days
        band = _band_for_days(days)
        if band is None:
            continue

        # Skip if already alerted for this band.
        async with SessionLocal() as db:
            existing = (
                await db.execute(
                    select(CredentialAlertLog.id).where(
                        CredentialAlertLog.credential_id == cred.id,
                        CredentialAlertLog.threshold_band == band,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue

        items_to_alert.append(
            {
                "credential_id": cred.id,
                "physician_name": phys.name,
                "credential_type": cred.type,
                "expires_on": cred.expires_on.isoformat(),
                "threshold_band": band,
            }
        )

    if not items_to_alert:
        log.info("No new band crossings to alert as of %s.", today.isoformat())
        return 0

    async with SessionLocal() as db:
        clinical_subs = (
            await db.execute(
                select(AlertSubscription).where(
                    AlertSubscription.role.in_(("owner_clinical", "admin")),
                    AlertSubscription.frequency != "never",
                )
            )
        ).scalars().all()

    if not clinical_subs:
        log.warning(
            "No owner_clinical/admin subscribers — %d band crossings unrouted.",
            len(items_to_alert),
        )
        return 0

    sent = 0
    errors = 0
    html = render_email_template(
        "cred_scan.html.j2",
        scan_date=today.isoformat(),
        items=items_to_alert,
        band_colors=_BAND_COLORS,
    )

    for sub in clinical_subs:
        try:
            msg_id = await email_service.send_html_email(
                to=sub.email,
                subject=f"[HHA] {len(items_to_alert)} credentials expiring within 90 days",
                html_body=html,
            )
            log.info("Sent cred_scan email to %s (msg=%s)", sub.email, msg_id)
            sent += 1
        except Exception:
            log.exception("Failed sending cred_scan to %s — continuing.", sub.email)
            errors += 1

    # Persist log rows AFTER at least one successful send — if every send fails,
    # we don't poison the band so tomorrow's run can retry.
    if sent > 0:
        async with SessionLocal() as db:
            for item in items_to_alert:
                db.add(
                    CredentialAlertLog(
                        credential_id=item["credential_id"],
                        threshold_band=item["threshold_band"],
                        alerted_on=datetime.now(UTC),
                    )
                )
            await db.commit()

    log.info(
        "Done: scan=%s items=%d sent=%d errors=%d",
        today.isoformat(),
        len(items_to_alert),
        sent,
        errors,
    )
    return 1 if errors > 0 and sent == 0 else 0


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
