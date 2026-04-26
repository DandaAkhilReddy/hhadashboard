"""alert_digest cron tests.

Skipped if Postgres unreachable. Mocks the email_service so no real ACS calls.

Covers:
  - email_configured=False → exits 0 with no DB writes
  - With seeded variance + subscriber → sends N emails + writes alert_log rows
  - Re-run on same target date → 0 sends (idempotent via alert_log)
  - Empty subscriber list → 0 sends, 0 errors, 0 alert_log writes
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from jobs.alert_digest.main import run
from sqlalchemy import delete, select, text

from app.deps import SessionLocal
from app.models.alerts import AlertLog, AlertSubscription
from app.models.entries_finance import MonthlyFinanceManual

pytestmark = pytest.mark.asyncio


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
        pytest.skip("Postgres not reachable — skipping alert_digest tests")


@pytest.fixture
async def clean_state():
    async with SessionLocal() as session:
        await session.execute(delete(AlertLog))
        await session.execute(delete(AlertSubscription))
        await session.execute(delete(MonthlyFinanceManual))
        await session.commit()
    yield
    async with SessionLocal() as session:
        await session.execute(delete(AlertLog))
        await session.execute(delete(AlertSubscription))
        await session.execute(delete(MonthlyFinanceManual))
        await session.commit()


def _trigger_finance_alert(state: str = "FL") -> MonthlyFinanceManual:
    """A finance row that crosses the FL/TX collections-below-target rule."""
    return MonthlyFinanceManual(
        year=2026,
        month=3,
        period_first=date(2026, 3, 1),
        state=state,
        collections_usd=Decimal("100"),  # massively below the 2.5M target
        ventra_fee_usd=Decimal("5"),
        ar_total_usd=Decimal("500"),
        ar_0_30_usd=Decimal("200"),
        ar_31_60_usd=Decimal("100"),
        ar_61_90_usd=Decimal("75"),
        ar_91_120_usd=Decimal("75"),
        ar_over_120_usd=Decimal("50"),
        net_collection_rate_pct=Decimal("95"),
        days_in_ar=Decimal("40"),
        source_system="VENTRA_FL_FALLBACK" if state == "FL" else "HHA_TX_MANUAL",
        entered_by_upn="test@example.com",
    )


async def test_run_exits_zero_when_email_not_configured(clean_state) -> None:
    _ = clean_state
    with patch("jobs.alert_digest.main.settings") as mock_settings:
        mock_settings.email_configured = False
        exit_code = await run(target_date=date(2026, 4, 25))
    assert exit_code == 0

    # No alert_log rows written
    async with SessionLocal() as db:
        rows = (await db.execute(select(AlertLog))).scalars().all()
    assert rows == []


async def test_run_sends_email_per_alert_and_records_to_log(clean_state) -> None:
    _ = clean_state

    async with SessionLocal() as db:
        db.add(_trigger_finance_alert("FL"))
        db.add(
            AlertSubscription(
                role="exec",
                email="cfo@hha.test",
                categories=[],  # empty = receives all categories
                frequency="daily",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
        await db.commit()

    fake_send = AsyncMock(return_value="msg-abc")
    with (
        patch("jobs.alert_digest.main.settings") as mock_settings,
        patch("jobs.alert_digest.main.email_service") as mock_email,
    ):
        mock_settings.email_configured = True
        mock_email.send_html_email = fake_send
        exit_code = await run(target_date=date(2026, 4, 25))

    assert exit_code == 0
    # At least one alert_log row written.
    async with SessionLocal() as db:
        rows = (await db.execute(select(AlertLog))).scalars().all()
    assert len(rows) >= 1
    assert all(r.recipient_email == "cfo@hha.test" for r in rows)
    assert all(r.acs_message_id == "msg-abc" for r in rows)
    assert fake_send.await_count == len(rows)


async def test_rerun_same_target_date_is_idempotent(clean_state) -> None:
    _ = clean_state
    async with SessionLocal() as db:
        db.add(_trigger_finance_alert("FL"))
        db.add(
            AlertSubscription(
                role="exec",
                email="cfo@hha.test",
                categories=[],
                frequency="daily",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
        await db.commit()

    fake_send = AsyncMock(return_value="msg-abc")
    with (
        patch("jobs.alert_digest.main.settings") as mock_settings,
        patch("jobs.alert_digest.main.email_service") as mock_email,
    ):
        mock_settings.email_configured = True
        mock_email.send_html_email = fake_send
        # First run sends N
        await run(target_date=date(2026, 4, 25))
        first_call_count = fake_send.await_count
        assert first_call_count >= 1

        # Second run on same target_date — must skip everything.
        fake_send.reset_mock()
        await run(target_date=date(2026, 4, 25))

    assert fake_send.await_count == 0


async def test_no_subscribers_means_no_sends(clean_state) -> None:
    _ = clean_state
    async with SessionLocal() as db:
        db.add(_trigger_finance_alert("FL"))
        await db.commit()

    fake_send = AsyncMock(return_value="msg-abc")
    with (
        patch("jobs.alert_digest.main.settings") as mock_settings,
        patch("jobs.alert_digest.main.email_service") as mock_email,
    ):
        mock_settings.email_configured = True
        mock_email.send_html_email = fake_send
        exit_code = await run(target_date=date(2026, 4, 25))

    assert exit_code == 0
    assert fake_send.await_count == 0
    # No alert_log writes either.
    async with SessionLocal() as db:
        rows = (await db.execute(select(AlertLog))).scalars().all()
    assert rows == []


async def test_subscriber_categories_filter(clean_state) -> None:
    """A subscriber with categories=['operations'] should NOT receive a
    finance-category alert."""
    _ = clean_state
    async with SessionLocal() as db:
        db.add(_trigger_finance_alert("FL"))
        db.add(
            AlertSubscription(
                role="owner_ops",
                email="crystal@hha.test",
                categories=["operations"],
                frequency="daily",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
        await db.commit()

    fake_send = AsyncMock(return_value="msg-abc")
    with (
        patch("jobs.alert_digest.main.settings") as mock_settings,
        patch("jobs.alert_digest.main.email_service") as mock_email,
    ):
        mock_settings.email_configured = True
        mock_email.send_html_email = fake_send
        await run(target_date=date(2026, 4, 25))

    # Finance alert exists but ops subscriber filtered out.
    assert fake_send.await_count == 0
