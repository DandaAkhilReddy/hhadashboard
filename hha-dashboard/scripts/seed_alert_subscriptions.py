"""Seed (or upsert) one alert_subscriptions row.

Usage (from api/ directory):
    uv run python ../scripts/seed_alert_subscriptions.py \\
        --role exec --email cfo@hhamedicine.com \\
        --categories finance,clinical \\
        --frequency daily

Idempotent — UNIQUE(role, email) so re-running with the same role/email is a
no-op (categories/frequency are NOT updated unless `--update` is passed).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add api/ to path
API_DIR = Path(__file__).resolve().parent.parent / "api"
sys.path.insert(0, str(API_DIR))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.models.alerts import AlertSubscription  # noqa: E402
from app.settings import settings  # noqa: E402

VALID_ROLES = {
    "admin",
    "exec",
    "owner_finance",
    "owner_ops",
    "owner_clinical",
    "owner_hr",
}
VALID_FREQUENCIES = {"immediate", "daily", "weekly", "never"}


async def main(
    role: str,
    email: str,
    categories: list[str],
    frequency: str,
    update_if_exists: bool,
) -> int:
    if role not in VALID_ROLES:
        print(f"[error] role must be one of {sorted(VALID_ROLES)}", file=sys.stderr)
        return 2
    if frequency not in VALID_FREQUENCIES:
        print(f"[error] frequency must be one of {sorted(VALID_FREQUENCIES)}", file=sys.stderr)
        return 2

    engine = create_async_engine(settings.database_url, echo=False)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with SessionLocal() as session:
            existing = (
                await session.execute(
                    select(AlertSubscription).where(
                        AlertSubscription.role == role,
                        AlertSubscription.email == email,
                    )
                )
            ).scalar_one_or_none()

            now = datetime.now(UTC)
            if existing is None:
                row = AlertSubscription(
                    role=role,
                    email=email,
                    categories=categories,
                    frequency=frequency,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                await session.commit()
                print(f"[ok] inserted ({role}, {email})")
                return 0

            if update_if_exists:
                existing.categories = categories
                existing.frequency = frequency
                existing.updated_at = now
                await session.commit()
                print(f"[ok] updated ({role}, {email}) — frequency={frequency}, categories={categories}")
                return 0

            print(
                f"[info] ({role}, {email}) already exists — left alone "
                "(idempotent). Pass --update to overwrite."
            )
            return 0
    finally:
        await engine.dispose()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed an alerts.alert_subscriptions row.")
    parser.add_argument("--role", required=True, help=f"One of: {sorted(VALID_ROLES)}")
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--categories",
        default="",
        help="Comma-separated category list (finance,operations,clinical,people). "
        "Empty = receive every category.",
    )
    parser.add_argument("--frequency", default="daily", help=f"One of: {sorted(VALID_FREQUENCIES)}")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Overwrite categories+frequency on an existing (role, email) row.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    cats = [c.strip() for c in args.categories.split(",") if c.strip()]
    sys.exit(
        asyncio.run(
            main(
                role=args.role,
                email=args.email,
                categories=cats,
                frequency=args.frequency,
                update_if_exists=args.update,
            )
        )
    )
