"""Alert engine — DB-backed unit tests.

Skipped when Postgres isn't reachable (mirrors test_audit_triggers.py /
test_census_portal.py pattern). Verifies threshold-crossing produces the
right shape of AlertCandidate.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, text

from app.deps import SessionLocal
from app.models.entries_clinical import WeeklyClinical
from app.models.entries_finance import MonthlyFinanceManual
from app.models.entries_hr import WeeklyHrManual
from app.services import alert_engine

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
        pytest.skip("Postgres not reachable — skipping alert_engine tests")


@pytest.fixture
async def clean_entries():
    async with SessionLocal() as session:
        await session.execute(delete(MonthlyFinanceManual))
        await session.execute(delete(WeeklyClinical))
        await session.execute(delete(WeeklyHrManual))
        await session.commit()
    yield
    async with SessionLocal() as session:
        await session.execute(delete(MonthlyFinanceManual))
        await session.execute(delete(WeeklyClinical))
        await session.execute(delete(WeeklyHrManual))
        await session.commit()


def _finance_row(
    *,
    state: str,
    year: int = 2026,
    month: int = 3,
    collections_usd: Decimal = Decimal("3000000"),
    ar_total_usd: Decimal = Decimal("4000000"),
    ar_over_120_usd: Decimal = Decimal("400000"),
    ncr: Decimal = Decimal("95"),
) -> MonthlyFinanceManual:
    return MonthlyFinanceManual(
        year=year,
        month=month,
        period_first=date(year, month, 1),
        state=state,
        collections_usd=collections_usd,
        ventra_fee_usd=collections_usd * Decimal("0.05"),
        ar_total_usd=ar_total_usd,
        ar_0_30_usd=ar_total_usd * Decimal("0.4"),
        ar_31_60_usd=ar_total_usd * Decimal("0.2"),
        ar_61_90_usd=ar_total_usd * Decimal("0.15"),
        ar_91_120_usd=ar_total_usd * Decimal("0.15"),
        ar_over_120_usd=ar_over_120_usd,
        net_collection_rate_pct=ncr,
        days_in_ar=Decimal("40"),
        source_system="VENTRA_FL_FALLBACK" if state == "FL" else "HHA_TX_MANUAL",
        entered_by_upn="test@example.com",
    )


async def test_empty_db_returns_no_alerts(clean_entries) -> None:
    _ = clean_entries
    async with SessionLocal() as db:
        alerts = await alert_engine.compute_alerts_for_date(db, date(2026, 4, 25))
    assert alerts == []


async def test_fl_below_target_collections_fires_red(clean_entries) -> None:
    """FL collections below the monthly target → red finance alert."""
    _ = clean_entries
    async with SessionLocal() as db:
        # Below the FL monthly target (default $2.5M)
        db.add(_finance_row(state="FL", collections_usd=Decimal("1000000")))
        await db.commit()

    async with SessionLocal() as db:
        alerts = await alert_engine.compute_alerts_for_date(db, date(2026, 4, 25))

    fl_collections_alerts = [
        a for a in alerts if "fl-collections-below-target" in a.id
    ]
    assert len(fl_collections_alerts) == 1
    alert = fl_collections_alerts[0]
    assert alert.severity == "red"
    assert alert.category == "finance"
    assert "FL collections below target" in alert.title


async def test_ar_over_120_above_threshold_fires_yellow(clean_entries) -> None:
    _ = clean_entries
    async with SessionLocal() as db:
        # 50% of AR over 120 days — above the 20% threshold
        db.add(
            _finance_row(
                state="TX",
                ar_total_usd=Decimal("1000000"),
                ar_over_120_usd=Decimal("500000"),
            )
        )
        await db.commit()

    async with SessionLocal() as db:
        alerts = await alert_engine.compute_alerts_for_date(db, date(2026, 4, 25))

    ar_alerts = [a for a in alerts if "ar-over-120" in a.id]
    assert len(ar_alerts) == 1
    assert ar_alerts[0].severity == "yellow"


async def test_clinical_hp24h_below_floor_fires_yellow(clean_entries) -> None:
    _ = clean_entries
    async with SessionLocal() as db:
        db.add(
            WeeklyClinical(
                week_ending=date(2026, 4, 19),
                state="FL",
                hp_24h_pct=Decimal("80"),  # below 90 floor
                dc_48h_pct=Decimal("95"),
                avg_los_days=Decimal("4.5"),
                charts_audited_count=20,
                entered_by_upn="test@example.com",
            )
        )
        await db.commit()

    async with SessionLocal() as db:
        alerts = await alert_engine.compute_alerts_for_date(db, date(2026, 4, 25))

    clinical_alerts = [a for a in alerts if "hp24h-below-floor" in a.id]
    assert len(clinical_alerts) == 1
    assert clinical_alerts[0].severity == "yellow"
    assert clinical_alerts[0].category == "clinical"


async def test_hr_below_fmv_count_fires_yellow(clean_entries) -> None:
    _ = clean_entries
    async with SessionLocal() as db:
        db.add(
            WeeklyHrManual(
                week_ending=date(2026, 4, 19),
                headcount_w2=50,
                headcount_1099=20,
                open_positions_total=3,  # below threshold
                terminations_90d_count=1,
                below_fmv_count=10,  # above threshold of 5
                entered_by_upn="test@example.com",
            )
        )
        await db.commit()

    async with SessionLocal() as db:
        alerts = await alert_engine.compute_alerts_for_date(db, date(2026, 4, 25))

    fmv_alerts = [a for a in alerts if "below-fmv-cluster" in a.id]
    assert len(fmv_alerts) == 1
    assert fmv_alerts[0].severity == "yellow"
    assert fmv_alerts[0].category == "people"


async def test_alert_id_is_stable_across_runs(clean_entries) -> None:
    """Same input → same alert.id, so the cron's idempotency check works."""
    _ = clean_entries
    async with SessionLocal() as db:
        db.add(_finance_row(state="FL", collections_usd=Decimal("1000000")))
        await db.commit()

    async with SessionLocal() as db:
        first = await alert_engine.compute_alerts_for_date(db, date(2026, 4, 25))
    async with SessionLocal() as db:
        second = await alert_engine.compute_alerts_for_date(db, date(2026, 4, 25))

    assert {a.id for a in first} == {a.id for a in second}
