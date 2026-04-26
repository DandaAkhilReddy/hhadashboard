"""Census-portal authentication service.

Implements the F2 contract:
- Email + password (argon2id) against the single `auth.census_credentials` row.
- Single-session lock via the `active_session_token` column. New login
  overwrites the token; any prior browser's cookie no longer matches.
- Lockout policy from rules/security.md: 10 consecutive failures → 15-min lock.

This module is intentionally NOT used by the Entra-gated dashboard. The
dashboard authenticates via app/services/entra_jwt.py + app/deps.py.
"""

from __future__ import annotations

import contextlib
import secrets
from datetime import UTC, datetime, timedelta

import structlog
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.census_credentials import CensusCredential

logger = structlog.get_logger(__name__)

# argon2id with library defaults: time_cost=3, memory_cost=64MB, parallelism=4.
# These match OWASP 2023 minimums and rules/security.md ("argon2id" mandate).
_HASHER = PasswordHasher()

# Lockout policy
LOCKOUT_AFTER_FAILURES = 10
LOCKOUT_DURATION = timedelta(minutes=15)

# Session lifetime — single workday. Rotate on every login.
SESSION_DURATION = timedelta(hours=8)


class AuthError(Exception):
    """Base for portal auth failures."""


class InvalidCredentialsError(AuthError):
    """Email + password did not verify."""


class AccountLockedError(AuthError):
    """Too many failed attempts; locked until `locked_until`."""

    def __init__(self, locked_until: datetime) -> None:
        super().__init__(f"locked until {locked_until.isoformat()}")
        self.locked_until = locked_until


def hash_password(plain: str) -> str:
    """Hash a plain-text password with argon2id."""
    return _HASHER.hash(plain)


async def verify_credentials(
    db: AsyncSession, email: str, password: str
) -> CensusCredential:
    """Verify email + password against the stored credential.

    Raises:
        AccountLockedError: row is currently locked (returns lock-until time).
        InvalidCredentialsError: email mismatch or password mismatch (no row vs wrong
            password are indistinguishable from the caller's POV — same error).
    """
    now = datetime.now(UTC)

    row = (
        await db.execute(
            select(CensusCredential).where(CensusCredential.email == email)
        )
    ).scalar_one_or_none()

    if row is None:
        # Don't leak whether the email exists. Run argon2 against a dummy
        # hash so this branch's wall-time roughly matches the real-verify
        # path; the dummy hash is unguessable so verify always fails.
        with contextlib.suppress(VerifyMismatchError):
            _HASHER.verify(_DUMMY_HASH, password)
        raise InvalidCredentialsError

    if row.locked_until is not None and row.locked_until > now:
        raise AccountLockedError(row.locked_until)

    try:
        _HASHER.verify(row.password_hash, password)
    except VerifyMismatchError:
        row.failed_attempts += 1
        if row.failed_attempts >= LOCKOUT_AFTER_FAILURES:
            row.locked_until = now + LOCKOUT_DURATION
            row.failed_attempts = 0
            await db.flush()
            logger.warning(
                "census_portal.locked",
                email=email,
                locked_until=row.locked_until.isoformat(),
            )
            raise AccountLockedError(row.locked_until) from None
        await db.flush()
        raise InvalidCredentialsError from None

    # Success — clear failure state, but DON'T issue session here. That's
    # issue_session()'s job (called from the router after this returns).
    row.failed_attempts = 0
    row.locked_until = None
    await db.flush()
    return row


async def issue_session(db: AsyncSession, credential: CensusCredential) -> str:
    """Generate a fresh session token, store it, return it.

    Overwrites any prior token so the previous browser is logged out on its
    next request. This is the single-session lock.
    """
    token = secrets.token_urlsafe(32)
    credential.active_session_token = token
    credential.active_session_expires_at = datetime.now(UTC) + SESSION_DURATION
    await db.flush()
    return token


async def validate_session(
    db: AsyncSession, token: str
) -> CensusCredential | None:
    """Look up the credential by token. Returns None if invalid/expired/missing."""
    if not token:
        return None
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(CensusCredential).where(
                CensusCredential.active_session_token == token
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.active_session_expires_at is None or row.active_session_expires_at <= now:
        return None
    return row


async def clear_session(db: AsyncSession, credential: CensusCredential) -> None:
    """Logout — wipe the active token. Cookie must also be cleared by caller."""
    credential.active_session_token = None
    credential.active_session_expires_at = None
    await db.flush()


# Pre-computed argon2 hash of an unguessable random string. Used to make the
# "no such email" path spend roughly the same wall time as the real-verify
# path. Generated once at module import.
_DUMMY_HASH = _HASHER.hash(secrets.token_urlsafe(32))
