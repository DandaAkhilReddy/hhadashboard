"""Paycom workforce sync — cron entry point (currently a stub).

Local dev / one-off:
    cd hha-dashboard/api
    uv run python -m jobs.paycom_sync.main

Prod: Azure Container Apps Job, nightly cron `0 7 * * *` (07:00 UTC). Runs
all registered extractors in order; each is idempotent so re-running on
the same day is safe.

When `settings.paycom_configured` is False (no PAYCOM_API_BASE_URL /
PAYCOM_CLIENT_ID / PAYCOM_CLIENT_SECRET in env), the job exits 0 with an
"API access not configured" log line and does no work. This is the expected
state today — Paycom enablement is in flight (4–6 wk window from
2026-04-26). When the credential lands, drop it in Key Vault and the cron
starts consuming it on the next scheduled run.

Per F1 in the standing facts: don't write speculative extractors. The
stubs in `extractors/` exist purely so the registry + cron + tests have
something to point at.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add api/ to sys.path so `from app...` works when running from hha-dashboard/
API_DIR = Path(__file__).resolve().parent.parent.parent / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.deps import SessionLocal  # noqa: E402
from app.services.audit import set_current_upn  # noqa: E402
from app.settings import settings  # noqa: E402

from .extractors import ROUTES  # noqa: E402

SERVICE_UPN = "paycom-sync@hhamedicine.com"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("jobs.paycom_sync")


async def run() -> int:
    """Run all registered extractors. Returns exit code (0 = success).

    Today this is a no-op when Paycom isn't configured. When it is, each
    extractor in ROUTES runs against a fresh DB session (so a failure in one
    doesn't roll back the others).
    """
    if not settings.paycom_configured:
        log.info(
            "Paycom API access not yet configured — exiting cleanly (no-op). "
            "Set PAYCOM_API_BASE_URL + PAYCOM_CLIENT_ID + PAYCOM_CLIENT_SECRET "
            "to enable.",
        )
        return 0

    set_current_upn(SERVICE_UPN)

    total_rows = 0
    all_warnings: list[str] = []
    for name, extractor in ROUTES.items():
        log.info("Running extractor: %s", name)
        async with SessionLocal() as db:
            result = await extractor(db)
            await db.commit()
        total_rows += result.rows_written
        all_warnings.extend(f"{name}: {w}" for w in result.warnings)

    log.info("Done: rows_written=%d warnings=%d", total_rows, len(all_warnings))
    for warning in all_warnings:
        log.warning(warning)
    return 0


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
