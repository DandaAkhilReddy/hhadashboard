"""Ventra ingest cron entry point.

Local dev / one-off:
    cd hha-dashboard/api
    uv run python -m jobs.ventra_ingest.main ../samples/ventra/ventra-fl-2026-03.csv

Prod: Azure Container Apps Job, monthly cron `0 6 5 * *` (06:00 UTC on the 5th
of each month — gives Ventra a few business days to close the prior month).

For now the file path is passed in as an argv. SFTP wiring lands in a follow-up
session — the parser + ingest service are SFTP-agnostic so swapping is local.
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
from app.services.audit import install_audit_listener, set_current_upn  # noqa: E402

from .ingest import SERVICE_UPN, ingest_ventra_rows  # noqa: E402
from .parser import parse_ventra_csv  # noqa: E402

# Cron jobs don't go through FastAPI's lifespan — install the SQLAlchemy
# audit event listener manually so every upsert produces an audit row.
install_audit_listener()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("jobs.ventra_ingest")


async def run(csv_path: Path) -> int:
    """Read a CSV from disk, parse, ingest. Returns exit code (0 = success)."""
    if not csv_path.exists():
        log.error("File not found: %s", csv_path)
        return 1

    text = csv_path.read_text(encoding="utf-8")
    try:
        rows = parse_ventra_csv(text)
    except Exception as e:
        log.error("Parse failed: %s", e)
        return 2

    if not rows:
        log.warning("No rows parsed from %s", csv_path)
        return 0

    # Service UPN drives the audit attribution
    set_current_upn(SERVICE_UPN)

    async with SessionLocal() as db:
        result = await ingest_ventra_rows(db, rows)

    log.info("Done: upserted=%d skipped=%d", result.rows_upserted, len(result.skipped or []))
    for warning in result.skipped or []:
        log.warning("SKIPPED: %s", warning)
    return 0


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m jobs.ventra_ingest.main <path/to/ventra.csv>", file=sys.stderr)
        sys.exit(64)  # EX_USAGE

    csv_path = Path(sys.argv[1]).resolve()
    exit_code = asyncio.run(run(csv_path))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
