"""Unit tests for ``app.services.census_auth`` — the portal-only auth
layer that lives parallel to Entra.

Covers every public function + every branch of ``verify_credentials``
without a real database:

- ``hash_password`` produces verifiable argon2id output
- ``verify_credentials``:
    - email not found  → InvalidCredentialsError (constant-time path)
    - locked row (locked_until > now) → AccountLockedError
    - locked row, lock expired → falls through to verify
    - wrong password, failures < threshold → increments + InvalidCredentialsError
    - wrong password, failures == threshold-1 → locks + AccountLockedError
    - correct password → clears failure state + returns row
- ``issue_session`` → fresh url-safe token + 8-hour expiry
- ``validate_session``:
    - empty token → None
    - no row matching the token → None
    - expired session → None
    - valid → returns row
- ``clear_session`` → wipes token + expiry
- Constants are locked at their security-policy values
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from argon2 import PasswordHasher

from app.services.census_auth import (
    LOCKOUT_AFTER_FAILURES,
    LOCKOUT_DURATION,
    SESSION_DURATION,
    AccountLockedError,
    AuthError,
    InvalidCredentialsError,
    clear_session,
    hash_password,
    issue_session,
    validate_session,
    verify_credentials,
)


def _credential(**overrides) -> MagicMock:
    """Build a stand-in CensusCredential row that supports attribute set
    (the service mutates `failed_attempts` / `locked_until` in place)."""
    row = MagicMock()
    row.email = overrides.get("email", "portal@hha.com")
    row.password_hash = overrides.get("password_hash", hash_password("hunter2"))
    row.failed_attempts = overrides.get("failed_attempts", 0)
    row.locked_until = overrides.get("locked_until")
    row.active_session_token = overrides.get("active_session_token")
    row.active_session_expires_at = overrides.get("active_session_expires_at")
    return row


def _db_returning(row: MagicMock | None) -> MagicMock:
    """Mock AsyncSession whose execute() returns a result yielding
    `.scalar_one_or_none() -> row`."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    return db


# ============================================================================
# Constants
# ============================================================================


class TestConstants:
    def test_lockout_threshold_is_10(self) -> None:
        # rules/security.md mandates "Lock after 10 failures".
        assert LOCKOUT_AFTER_FAILURES == 10

    def test_lockout_duration_is_15_minutes(self) -> None:
        assert timedelta(minutes=15) == LOCKOUT_DURATION

    def test_session_lifetime_is_8_hours(self) -> None:
        # Single workday per the module docstring.
        assert timedelta(hours=8) == SESSION_DURATION

    def test_exception_hierarchy(self) -> None:
        # All portal auth failures share AuthError so callers can do one
        # except-clause if they want to.
        assert issubclass(InvalidCredentialsError, AuthError)
        assert issubclass(AccountLockedError, AuthError)


# ============================================================================
# hash_password
# ============================================================================


class TestHashPassword:
    def test_hash_is_argon2id_format(self) -> None:
        h = hash_password("hunter2")
        assert h.startswith("$argon2id$"), "Expected argon2id prefix"

    def test_hash_round_trip_verifies(self) -> None:
        h = hash_password("hunter2")
        # External verify — proves the hash is real argon2id, not a stub.
        PasswordHasher().verify(h, "hunter2")

    def test_two_hashes_of_same_password_differ_due_to_salt(self) -> None:
        # Different salt every call — defensive check against accidental
        # deterministic-hash regressions.
        assert hash_password("x") != hash_password("x")


# ============================================================================
# verify_credentials — branches
# ============================================================================


class TestVerifyCredentialsBranches:
    async def test_missing_email_raises_invalid_credentials(self) -> None:
        db = _db_returning(None)
        with pytest.raises(InvalidCredentialsError):
            await verify_credentials(db, "no-such@hha.com", "anything")

    async def test_locked_row_raises_account_locked(self) -> None:
        # locked_until is in the future
        row = _credential(
            locked_until=datetime.now(UTC) + timedelta(minutes=5),
        )
        db = _db_returning(row)

        with pytest.raises(AccountLockedError) as exc:
            await verify_credentials(db, "portal@hha.com", "wrong")
        assert exc.value.locked_until == row.locked_until

    async def test_lock_expired_falls_through_to_verify(self) -> None:
        # locked_until in the past → not actually locked
        row = _credential(
            password_hash=hash_password("hunter2"),
            locked_until=datetime.now(UTC) - timedelta(minutes=1),
        )
        db = _db_returning(row)

        out = await verify_credentials(db, "portal@hha.com", "hunter2")

        assert out is row
        # Success path clears failure state
        assert row.failed_attempts == 0
        assert row.locked_until is None

    async def test_wrong_password_increments_failed_attempts(self) -> None:
        row = _credential(
            password_hash=hash_password("hunter2"),
            failed_attempts=2,
        )
        db = _db_returning(row)

        with pytest.raises(InvalidCredentialsError):
            await verify_credentials(db, "portal@hha.com", "wrong")
        assert row.failed_attempts == 3
        # No lockout yet — under the threshold
        assert row.locked_until is None

    async def test_wrong_password_at_threshold_locks_and_resets_counter(self) -> None:
        """The 10th consecutive failure locks the account."""
        row = _credential(
            password_hash=hash_password("hunter2"),
            failed_attempts=LOCKOUT_AFTER_FAILURES - 1,
        )
        db = _db_returning(row)

        with pytest.raises(AccountLockedError) as exc:
            await verify_credentials(db, "portal@hha.com", "wrong")

        # Lockout fired
        assert row.locked_until is not None
        # Counter resets so the next 10 misses re-arm the lockout cleanly
        assert row.failed_attempts == 0
        # Returned lock-until matches what got stored on the row
        assert exc.value.locked_until == row.locked_until

    async def test_correct_password_clears_failure_state(self) -> None:
        row = _credential(
            password_hash=hash_password("hunter2"),
            failed_attempts=4,
            locked_until=None,
        )
        db = _db_returning(row)

        out = await verify_credentials(db, "portal@hha.com", "hunter2")

        assert out is row
        assert row.failed_attempts == 0
        assert row.locked_until is None
        db.flush.assert_awaited()


# ============================================================================
# issue_session
# ============================================================================


class TestIssueSession:
    async def test_returns_url_safe_token(self) -> None:
        row = _credential()
        db = MagicMock()
        db.flush = AsyncMock()

        tok = await issue_session(db, row)

        # secrets.token_urlsafe(32) produces ~43 base64url chars
        assert isinstance(tok, str)
        assert len(tok) >= 32
        # Stored on the row
        assert row.active_session_token == tok
        assert row.active_session_expires_at is not None

    async def test_expiry_is_8_hours_in_future(self) -> None:
        row = _credential()
        db = MagicMock()
        db.flush = AsyncMock()

        before = datetime.now(UTC)
        await issue_session(db, row)
        after = datetime.now(UTC)

        # Expiry must be ~SESSION_DURATION from now
        assert row.active_session_expires_at >= before + SESSION_DURATION - timedelta(seconds=1)
        assert row.active_session_expires_at <= after + SESSION_DURATION + timedelta(seconds=1)

    async def test_overwrites_prior_token(self) -> None:
        """Single-session lock: a new login invalidates the prior one."""
        row = _credential(active_session_token="old-token")
        db = MagicMock()
        db.flush = AsyncMock()

        new_tok = await issue_session(db, row)

        assert new_tok != "old-token"
        assert row.active_session_token == new_tok


# ============================================================================
# validate_session
# ============================================================================


class TestValidateSession:
    async def test_empty_token_returns_none_without_db_hit(self) -> None:
        db = MagicMock()
        db.execute = AsyncMock()

        result = await validate_session(db, "")
        assert result is None
        # Defensive: the empty-token short-circuit must not query the DB
        db.execute.assert_not_awaited()

    async def test_no_row_returns_none(self) -> None:
        db = _db_returning(None)
        result = await validate_session(db, "some-stale-token")
        assert result is None

    async def test_expired_session_returns_none(self) -> None:
        row = _credential(
            active_session_token="valid-token",
            active_session_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        db = _db_returning(row)
        assert await validate_session(db, "valid-token") is None

    async def test_null_expiry_returns_none(self) -> None:
        # Defensive: cleared session (token still in DB, expiry=NULL).
        row = _credential(
            active_session_token="valid-token",
            active_session_expires_at=None,
        )
        db = _db_returning(row)
        assert await validate_session(db, "valid-token") is None

    async def test_valid_session_returns_row(self) -> None:
        row = _credential(
            active_session_token="valid-token",
            active_session_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db = _db_returning(row)
        assert await validate_session(db, "valid-token") is row


# ============================================================================
# clear_session
# ============================================================================


class TestClearSession:
    async def test_wipes_token_and_expiry(self) -> None:
        row = _credential(
            active_session_token="some-token",
            active_session_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db = MagicMock()
        db.flush = AsyncMock()

        await clear_session(db, row)

        assert row.active_session_token is None
        assert row.active_session_expires_at is None
        db.flush.assert_awaited()
