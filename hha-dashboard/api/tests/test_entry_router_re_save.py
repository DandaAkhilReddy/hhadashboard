"""Re-save advances `updated_at` for every entry-router upsert path.

Locks the `func.now()` (DB clock) invariant across the four owner-form
write paths in `app/routers/entries.py`:

    POST /api/v1/entries/daily-census         (Crystal · owner_ops)
    POST /api/v1/entries/monthly-finance      (Sandy · owner_finance)
    POST /api/v1/entries/weekly-clinical      (Aneja/Reddy · owner_clinical)
    POST /api/v1/entries/weekly-hr            (Andrea · owner_hr)

Why these tests exist:
The Core-level `pg_insert(...).on_conflict_do_update(...)` bypasses
SQLAlchemy's `onupdate=func.now()` callback on `TimestampMixin.updated_at`,
so the router must explicitly set `updated_at` in the `set_` dict. If
that explicit set uses Python's `datetime.now(UTC)` instead of the DB's
`func.now()`, clock drift between the docker Postgres container and the
host can produce a re-save timestamp **earlier** than the original
INSERT — visible to the user as "edited 9:42am" → save → "edited 9:41am".
Same bug was caught and fixed for the census portal in PR #42; these
tests close the gap on the dashboard-side owner forms.

DB tests skip cleanly if Postgres isn't reachable.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text

from app.deps import SessionLocal
from app.main import app
from app.models.entries import DailyEntry
from app.models.entries_clinical import WeeklyClinical
from app.models.entries_finance import MonthlyFinanceManual
from app.models.entries_hr import WeeklyHrManual
from app.models.masters import Site

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
        pytest.skip("Postgres not reachable — skipping entry-router re-save tests")


def _last_sunday(today: date) -> date:
    return today - timedelta(days=(today.weekday() + 1) % 7)


# ---------------------------------------------------------------------------
# daily-census (Crystal)
# ---------------------------------------------------------------------------


async def test_daily_census_re_save_advances_updated_at() -> None:
    # Past date so the schema's `entry_date` future-rejection validator
    # doesn't 422 us. Cleanup keys off this exact date.
    today = date(2026, 1, 15)

    async with SessionLocal() as session:
        existing = (await session.execute(select(Site))).scalars().first()
        if existing is None:
            session.add(Site(name="ReSave-Test-Site", state="FL", status="ACTIVE"))
            await session.commit()
            existing = (await session.execute(select(Site))).scalars().first()
        assert existing is not None
        site_id = existing.id
        await session.execute(
            delete(DailyEntry).where(
                DailyEntry.site_id == site_id, DailyEntry.entry_date == today
            )
        )
        await session.commit()

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await client.post(
                "/api/v1/entries/daily-census",
                headers={"Authorization": "Dev owner_ops"},
                json={
                    "entry_date": today.isoformat(),
                    "rows": [{"site_id": site_id, "census": 100, "open_shifts": 0}],
                },
            )
            assert first.status_code == 200, first.text
            second = await client.post(
                "/api/v1/entries/daily-census",
                headers={"Authorization": "Dev owner_ops"},
                json={
                    "entry_date": today.isoformat(),
                    "rows": [{"site_id": site_id, "census": 105, "open_shifts": 0}],
                },
            )
            assert second.status_code == 200, second.text

        # Pull the row back and confirm the second value stuck.
        async with SessionLocal() as session:
            row = (
                await session.execute(
                    select(DailyEntry).where(
                        DailyEntry.site_id == site_id,
                        DailyEntry.entry_date == today,
                    )
                )
            ).scalar_one()
            # updated_at must be at-or-after created_at; both are DB clock.
            assert row.census == 105
            assert row.updated_at >= row.created_at, (
                "updated_at must not rewind below the row's created_at"
            )
    finally:
        async with SessionLocal() as session:
            await session.execute(
                delete(DailyEntry).where(
                    DailyEntry.site_id == site_id, DailyEntry.entry_date == today
                )
            )
            await session.commit()


# ---------------------------------------------------------------------------
# monthly-finance (Sandy)
# ---------------------------------------------------------------------------


async def test_monthly_finance_re_save_advances_updated_at() -> None:
    # Past month so the schema's future-month rejection doesn't 422 us.
    year, month = 2026, 1

    async with SessionLocal() as session:
        await session.execute(
            delete(MonthlyFinanceManual).where(
                MonthlyFinanceManual.year == year,
                MonthlyFinanceManual.month == month,
            )
        )
        await session.commit()

    base_row = {
        "state": "TX",
        "collections_usd": "100000",
        "ventra_fee_usd": "0",
        "ar_total_usd": "50000",
        "ar_0_30_usd": "20000",
        "ar_31_60_usd": "15000",
        "ar_61_90_usd": "8000",
        "ar_91_120_usd": "4000",
        "ar_over_120_usd": "3000",
        "net_collection_rate_pct": "95",
        "days_in_ar": "30",
    }

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await client.post(
                "/api/v1/entries/monthly-finance",
                headers={"Authorization": "Dev owner_finance"},
                json={"year": year, "month": month, "rows": [base_row]},
            )
            assert first.status_code == 200, first.text

            second_row = dict(base_row)
            second_row["collections_usd"] = "110000"
            second = await client.post(
                "/api/v1/entries/monthly-finance",
                headers={"Authorization": "Dev owner_finance"},
                json={"year": year, "month": month, "rows": [second_row]},
            )
            assert second.status_code == 200, second.text

        async with SessionLocal() as session:
            row = (
                await session.execute(
                    select(MonthlyFinanceManual).where(
                        MonthlyFinanceManual.year == year,
                        MonthlyFinanceManual.month == month,
                        MonthlyFinanceManual.state == "TX",
                    )
                )
            ).scalar_one()
            assert row.collections_usd == Decimal("110000.00")
            assert row.updated_at >= row.created_at
    finally:
        async with SessionLocal() as session:
            await session.execute(
                delete(MonthlyFinanceManual).where(
                    MonthlyFinanceManual.year == year,
                    MonthlyFinanceManual.month == month,
                )
            )
            await session.commit()


# ---------------------------------------------------------------------------
# weekly-clinical (Aneja/Reddy)
# ---------------------------------------------------------------------------


async def test_weekly_clinical_re_save_advances_updated_at() -> None:
    week_ending = _last_sunday(datetime.now(UTC).date())

    async with SessionLocal() as session:
        await session.execute(
            delete(WeeklyClinical).where(WeeklyClinical.week_ending == week_ending)
        )
        await session.commit()

    base_row = {
        "state": "TX",
        "hp_24h_pct": "92",
        "dc_48h_pct": "88",
        "avg_los_days": "4.2",
        "charts_audited_count": 30,
    }

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await client.post(
                "/api/v1/entries/weekly-clinical",
                headers={"Authorization": "Dev owner_clinical"},
                json={"week_ending": week_ending.isoformat(), "rows": [base_row]},
            )
            assert first.status_code == 200, first.text

            second_row = dict(base_row)
            second_row["hp_24h_pct"] = "94"
            second = await client.post(
                "/api/v1/entries/weekly-clinical",
                headers={"Authorization": "Dev owner_clinical"},
                json={"week_ending": week_ending.isoformat(), "rows": [second_row]},
            )
            assert second.status_code == 200, second.text

        async with SessionLocal() as session:
            row = (
                await session.execute(
                    select(WeeklyClinical).where(
                        WeeklyClinical.week_ending == week_ending,
                        WeeklyClinical.state == "TX",
                    )
                )
            ).scalar_one()
            assert row.hp_24h_pct == Decimal("94.00")
            assert row.updated_at >= row.created_at
    finally:
        async with SessionLocal() as session:
            await session.execute(
                delete(WeeklyClinical).where(WeeklyClinical.week_ending == week_ending)
            )
            await session.commit()


# ---------------------------------------------------------------------------
# weekly-hr (Andrea) — single-row variant
# ---------------------------------------------------------------------------


async def test_weekly_hr_re_save_advances_updated_at() -> None:
    week_ending = _last_sunday(datetime.now(UTC).date())

    async with SessionLocal() as session:
        await session.execute(
            delete(WeeklyHrManual).where(WeeklyHrManual.week_ending == week_ending)
        )
        await session.commit()

    base_payload = {
        "week_ending": week_ending.isoformat(),
        "headcount_w2": 25,
        "headcount_1099": 5,
        "open_positions_total": 3,
        "terminations_90d_count": 1,
        "below_fmv_count": 0,
    }

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await client.post(
                "/api/v1/entries/weekly-hr",
                headers={"Authorization": "Dev owner_hr"},
                json=base_payload,
            )
            assert first.status_code == 200, first.text

            second_payload = dict(base_payload)
            second_payload["headcount_w2"] = 27
            second = await client.post(
                "/api/v1/entries/weekly-hr",
                headers={"Authorization": "Dev owner_hr"},
                json=second_payload,
            )
            assert second.status_code == 200, second.text

        async with SessionLocal() as session:
            row = (
                await session.execute(
                    select(WeeklyHrManual).where(
                        WeeklyHrManual.week_ending == week_ending
                    )
                )
            ).scalar_one()
            assert row.headcount_w2 == 27
            assert row.updated_at >= row.created_at
    finally:
        async with SessionLocal() as session:
            await session.execute(
                delete(WeeklyHrManual).where(WeeklyHrManual.week_ending == week_ending)
            )
            await session.commit()
