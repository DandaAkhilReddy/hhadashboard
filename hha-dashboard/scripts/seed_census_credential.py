"""Seed (or rotate) the single census-portal credential.

Usage (from api/ directory):
    uv run python ../scripts/seed_census_credential.py \\
        --email crystal@hhamedicine.com \\
        --password "$(openssl rand -base64 18)"

Idempotent:
- If no row exists, insert (id=1, email, hash).
- If a row exists with the same email, leave the password alone unless
  --rotate is passed.
- If a row exists with a different email, refuse unless --rotate is passed
  (operator probably typoed; surface it).

The portal table is single-row by design (CHECK id = 1). One credential,
one login. Multi-tenant → follow-up.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add api/ to path so `from app...` works when running from scripts/
API_DIR = Path(__file__).resolve().parent.parent / "api"
sys.path.insert(0, str(API_DIR))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.models.census_credentials import CensusCredential  # noqa: E402
from app.services.census_auth import hash_password  # noqa: E402
from app.settings import settings  # noqa: E402


async def main(email: str, password: str, rotate: bool) -> int:
    engine = create_async_engine(settings.database_url, echo=False)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with SessionLocal() as session:
            existing = (
                await session.execute(select(CensusCredential).where(CensusCredential.id == 1))
            ).scalar_one_or_none()

            if existing is None:
                row = CensusCredential(
                    id=1,
                    email=email,
                    password_hash=hash_password(password),
                    failed_attempts=0,
                )
                session.add(row)
                await session.commit()
                print(f"[ok] seeded census credential for {email}")
                return 0

            if existing.email != email and not rotate:
                print(
                    f"[error] existing credential is for {existing.email!r}, not {email!r}. "
                    "Pass --rotate to overwrite, or fix the email argument.",
                    file=sys.stderr,
                )
                return 2

            if rotate:
                existing.email = email
                existing.password_hash = hash_password(password)
                existing.failed_attempts = 0
                existing.locked_until = None
                existing.active_session_token = None
                existing.active_session_expires_at = None
                await session.commit()
                print(f"[ok] rotated census credential to {email}")
                return 0

            print(f"[info] credential for {email} already exists — left alone (idempotent).")
            return 0
    finally:
        await engine.dispose()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed the census-portal credential.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="Overwrite the existing password / email if a row already exists.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(asyncio.run(main(args.email, args.password, args.rotate)))
