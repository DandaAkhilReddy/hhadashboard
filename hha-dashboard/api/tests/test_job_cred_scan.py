"""cred_scan cron tests.

Skipped if Postgres unreachable. Mocks the email_service so no real ACS calls.

Covers:
  - email_configured=False → exits 0 with no DB writes
  - Credentials in 30/60/90 bands → one email + log rows for new bands
  - Re-run same day → idempotent (no new emails, no new log rows)
  - Credential beyond 90 days → no alert
  - All sends fail → no log rows persisted (so tomorrow can retry)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from jobs.cred_scan.main import _band_for_days, run
from sqlalchemy import delete, select, text

from app.deps import SessionLocal
from app.models.alerts import AlertSubscription, CredentialAlertLog
from app.models.masters import Credential, Physician

# pytest's asyncio_mode = "auto" handles async tests; no module-level mark.


async def _can_connect_to_postgres() -> bool:
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="module", autouse=True)
async def _skip_if_no_postgres() -> None:
    if not await _can_connect_to_postgres():
        pytest.skip("Postgres not reachable — skipping cred_scan tests")


@pytest.fixture
async def clean_state():
    async with SessionLocal() as session:
        await session.execute(delete(CredentialAlertLog))
        await session.execute(delete(AlertSubscription))
        await session.execute(delete(Credential))
        await session.execute(delete(Physician))
        await session.commit()
    yield
    async with SessionLocal() as session:
        await session.execute(delete(CredentialAlertLog))
        await session.execute(delete(AlertSubscription))
        await session.execute(delete(Credential))
        await session.execute(delete(Physician))
        await session.commit()


def test_band_for_days_buckets_correctly() -> None:
    assert _band_for_days(0) == 30
    assert _band_for_days(30) == 30
    assert _band_for_days(31) == 60
    assert _band_for_days(60) == 60
    assert _band_for_days(61) == 90
    assert _band_for_days(90) == 90
    assert _band_for_days(91) is None


async def _seed(
    db, expires_in_days: int, *, physician_name: str = "Dr. Test"
) -> tuple[Physician, Credential]:
    today = datetime.now(UTC).date()
    phys = Physician(
        name=physician_name,
        email=f"{physician_name.lower().replace(' ', '.')}@hha.test",
        current_status="ACTIVE",
    )
    db.add(phys)
    await db.flush()
    cred = Credential(
        physician_id=phys.id,
        type="DEA",
        expires_on=today + timedelta(days=expires_in_days),
        status="ACTIVE",
    )
    db.add(cred)
    await db.flush()
    return phys, cred


async def test_run_exits_zero_when_email_not_configured(clean_state) -> None:
    _ = clean_state
    with patch("jobs.cred_scan.main.settings") as mock_settings:
        mock_settings.email_configured = False
        exit_code = await run()
    assert exit_code == 0
    async with SessionLocal() as db:
        rows = (await db.execute(select(CredentialAlertLog))).scalars().all()
    assert rows == []


async def test_credential_in_30_band_emits_one_email_and_one_log(clean_state) -> None:
    _ = clean_state
    async with SessionLocal() as db:
        await _seed(db, expires_in_days=20)
        db.add(
            AlertSubscription(
                role="owner_clinical",
                email="aneja@hha.test",
                categories=["clinical"],
                frequency="daily",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
        await db.commit()

    fake_send = AsyncMock(return_value="msg-x")
    with (
        patch("jobs.cred_scan.main.settings") as mock_settings,
        patch("jobs.cred_scan.main.email_service") as mock_email,
    ):
        mock_settings.email_configured = True
        mock_email.send_html_email = fake_send
        await run()

    assert fake_send.await_count == 1
    async with SessionLocal() as db:
        log_rows = (await db.execute(select(CredentialAlertLog))).scalars().all()
    assert len(log_rows) == 1
    assert log_rows[0].threshold_band == 30


async def test_credential_beyond_90_days_does_not_alert(clean_state) -> None:
    _ = clean_state
    async with SessionLocal() as db:
        await _seed(db, expires_in_days=200)
        db.add(
            AlertSubscription(
                role="owner_clinical",
                email="aneja@hha.test",
                categories=["clinical"],
                frequency="daily",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
        await db.commit()

    fake_send = AsyncMock(return_value="msg-x")
    with (
        patch("jobs.cred_scan.main.settings") as mock_settings,
        patch("jobs.cred_scan.main.email_service") as mock_email,
    ):
        mock_settings.email_configured = True
        mock_email.send_html_email = fake_send
        await run()

    assert fake_send.await_count == 0


async def test_rerun_same_band_is_idempotent(clean_state) -> None:
    _ = clean_state
    async with SessionLocal() as db:
        await _seed(db, expires_in_days=15)
        db.add(
            AlertSubscription(
                role="owner_clinical",
                email="aneja@hha.test",
                categories=["clinical"],
                frequency="daily",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
        await db.commit()

    fake_send = AsyncMock(return_value="msg-x")
    with (
        patch("jobs.cred_scan.main.settings") as mock_settings,
        patch("jobs.cred_scan.main.email_service") as mock_email,
    ):
        mock_settings.email_configured = True
        mock_email.send_html_email = fake_send
        await run()
        first = fake_send.await_count
        fake_send.reset_mock()
        await run()
    assert first == 1
    assert fake_send.await_count == 0


async def test_send_failure_does_not_persist_log(clean_state) -> None:
    """If every recipient send fails, no credential_alert_log rows are
    written so tomorrow's run can retry."""
    _ = clean_state
    async with SessionLocal() as db:
        await _seed(db, expires_in_days=15)
        db.add(
            AlertSubscription(
                role="owner_clinical",
                email="aneja@hha.test",
                categories=[],
                frequency="daily",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
        await db.commit()

    failing_send = AsyncMock(side_effect=RuntimeError("ACS down"))
    with (
        patch("jobs.cred_scan.main.settings") as mock_settings,
        patch("jobs.cred_scan.main.email_service") as mock_email,
    ):
        mock_settings.email_configured = True
        mock_email.send_html_email = failing_send
        exit_code = await run()

    assert exit_code != 0  # nonzero because every send failed
    async with SessionLocal() as db:
        log_rows = (await db.execute(select(CredentialAlertLog))).scalars().all()
    assert log_rows == []
