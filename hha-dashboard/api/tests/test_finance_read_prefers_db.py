"""Finance board read-prefers-DB logic.

Verifies that `get_finance_today`, `get_ar_aging`, and `get_finance_kpis`
prefer the most-recent MonthlyFinanceManual row per state when one exists,
and fall back to deterministic-fake values otherwise.

Mocks the AsyncSession so the test runs without Postgres.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import fake_data


def _fin_row(
    *,
    year: int,
    month: int,
    state: str,
    collections: float = 2_280_000,
    ventra_fee: float = 114_000,
    ar_total: float = 5_600_000,
    ar_buckets: tuple[float, float, float, float, float] = (
        1_568_000,
        1_120_000,
        784_000,
        728_000,
        1_400_000,
    ),
    ncr: float = 43,
    days_in_ar: float = 39.9,
) -> SimpleNamespace:
    """Build a MonthlyFinanceManual-shaped object."""
    source = "VENTRA_FL_FALLBACK" if state == "FL" else "HHA_TX_MANUAL"
    return SimpleNamespace(
        year=year,
        month=month,
        period_first=date(year, month, 1),
        state=state,
        collections_usd=Decimal(str(collections)),
        ventra_fee_usd=Decimal(str(ventra_fee)),
        ar_total_usd=Decimal(str(ar_total)),
        ar_0_30_usd=Decimal(str(ar_buckets[0])),
        ar_31_60_usd=Decimal(str(ar_buckets[1])),
        ar_61_90_usd=Decimal(str(ar_buckets[2])),
        ar_91_120_usd=Decimal(str(ar_buckets[3])),
        ar_over_120_usd=Decimal(str(ar_buckets[4])),
        net_collection_rate_pct=Decimal(str(ncr)),
        days_in_ar=Decimal(str(days_in_ar)),
        source_system=source,
    )


def _mock_db(rows: list) -> MagicMock:
    """AsyncSession whose execute().scalars().all() returns `rows`."""
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


# ----- get_finance_today -----


@pytest.mark.asyncio
async def test_finance_today_prefers_db_mtd_for_current_month() -> None:
    today = date(2026, 4, 15)
    db = _mock_db([_fin_row(year=2026, month=4, state="FL", collections=2_500_000)])

    out = await fake_data.get_finance_today(db=db, today=today)

    assert out["fl_mtd_actual"] == 2_500_000
    assert out["fl_source_system"] == "VENTRA_FL_FALLBACK"


@pytest.mark.asyncio
async def test_finance_today_falls_back_when_only_older_month_in_db() -> None:
    """If the latest entry is for a previous month, MTD stays synthetic for the current month."""
    today = date(2026, 4, 15)
    db = _mock_db([_fin_row(year=2026, month=3, state="FL")])

    out = await fake_data.get_finance_today(db=db, today=today)

    # Synthetic value, not the 2_280_000 from March
    assert out["fl_mtd_actual"] != 2_280_000


@pytest.mark.asyncio
async def test_finance_today_no_db_is_pure_fake() -> None:
    today = date(2026, 4, 15)
    out = await fake_data.get_finance_today(db=None, today=today)

    assert out["fl_daily_actual"] >= 0
    assert out["fl_source_system"] == "VENTRA_FL_FALLBACK"


# ----- get_ar_aging -----


@pytest.mark.asyncio
async def test_ar_aging_uses_db_for_fl_when_entry_exists() -> None:
    today = date(2026, 4, 15)
    db = _mock_db(
        [
            _fin_row(
                year=2026,
                month=3,
                state="FL",
                ar_total=4_000_000,
                ar_buckets=(1_000_000, 800_000, 700_000, 500_000, 1_000_000),
            )
        ]
    )

    out = await fake_data.get_ar_aging(db=db, today=today)

    assert out["fl_total_usd"] == 4_000_000
    assert out["fl_buckets"]["0-30"] == 1_000_000
    assert out["fl_buckets"][">120"] == 1_000_000
    assert out["fl_over_120_pct"] == 25.0


@pytest.mark.asyncio
async def test_ar_aging_uses_db_for_both_states() -> None:
    today = date(2026, 4, 15)
    db = _mock_db(
        [
            _fin_row(year=2026, month=3, state="FL", ar_total=4_000_000),
            _fin_row(year=2026, month=3, state="TX", ar_total=900_000),
        ]
    )

    out = await fake_data.get_ar_aging(db=db, today=today)

    assert out["fl_total_usd"] == 4_000_000
    assert out["tx_total_usd"] == 900_000


@pytest.mark.asyncio
async def test_ar_aging_falls_back_for_state_with_no_entry() -> None:
    today = date(2026, 4, 15)
    db = _mock_db([_fin_row(year=2026, month=3, state="FL", ar_total=4_000_000)])

    out = await fake_data.get_ar_aging(db=db, today=today)

    # FL = real, TX = synthetic (no row)
    assert out["fl_total_usd"] == 4_000_000
    assert out["tx_total_usd"] != 900_000  # would be ~1.24M synthetic


# ----- get_finance_kpis -----


@pytest.mark.asyncio
async def test_finance_kpis_prefer_db_values() -> None:
    today = date(2026, 4, 15)
    db = _mock_db(
        [
            _fin_row(year=2026, month=3, state="FL", ncr=48, days_in_ar=42.5),
            _fin_row(year=2026, month=3, state="TX", ncr=39, days_in_ar=33.0),
        ]
    )

    out = await fake_data.get_finance_kpis(db=db, today=today)

    assert out["fl_ncr_pct"] == 48
    assert out["fl_days_in_ar"] == 42.5
    assert out["tx_ncr_pct"] == 39
    assert out["tx_days_in_ar"] == 33.0


@pytest.mark.asyncio
async def test_finance_kpis_no_db_is_pure_fake() -> None:
    out = await fake_data.get_finance_kpis(db=None)
    assert out["fl_days_in_ar"] == 39.9  # the hardcoded fallback
    assert out["days_in_ar_target"] == 45
