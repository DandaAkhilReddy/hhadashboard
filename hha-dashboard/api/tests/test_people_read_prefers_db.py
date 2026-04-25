"""People board read-prefers-DB logic.

Verifies `get_people_summary` uses the most-recent WeeklyHrManual row when
present, falls back to deterministic fake values otherwise, and computes
turnover_90d_pct correctly from the entered numbers.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import fake_data


def _hr_row(
    *,
    week_ending: date = date(2026, 4, 19),
    w2: int = 50,
    contractor: int = 25,
    open_positions: int = 10,
    terminations: int = 5,
    below_fmv: int = 55,
) -> SimpleNamespace:
    return SimpleNamespace(
        week_ending=week_ending,
        headcount_w2=w2,
        headcount_1099=contractor,
        open_positions_total=open_positions,
        terminations_90d_count=terminations,
        below_fmv_count=below_fmv,
    )


def _mock_db(row: SimpleNamespace | None) -> MagicMock:
    """AsyncSession whose execute().scalar_one_or_none() returns `row`."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_people_summary_prefers_db_values() -> None:
    db = _mock_db(_hr_row(w2=52, contractor=24, open_positions=11, terminations=8, below_fmv=58))

    out = await fake_data.get_people_summary(db=db, today=date(2026, 4, 25))

    assert out["headcount_w2"] == 52
    assert out["headcount_1099"] == 24
    assert out["headcount_total"] == 76
    assert out["open_positions_total"] == 11
    assert out["below_fmv_count"] == 58


@pytest.mark.asyncio
async def test_people_summary_computes_turnover_pct_from_db() -> None:
    """turnover_pct = terminations / total_headcount × 100."""
    db = _mock_db(_hr_row(w2=50, contractor=50, terminations=10))  # 10/100 = 10%

    out = await fake_data.get_people_summary(db=db, today=date(2026, 4, 25))

    assert out["turnover_90d_pct"] == 10.0


@pytest.mark.asyncio
async def test_people_summary_falls_back_when_no_entry() -> None:
    db = _mock_db(None)

    out = await fake_data.get_people_summary(db=db, today=date(2026, 4, 25))

    # Defaults from fake_data hardcoded
    assert out["headcount_w2"] == 48
    assert out["headcount_1099"] == 23
    assert out["headcount_total"] == 71
    assert out["below_fmv_count"] == 61


@pytest.mark.asyncio
async def test_people_summary_no_db_is_pure_fake() -> None:
    out = await fake_data.get_people_summary(db=None)
    assert out["headcount_total"] == 71
    assert out["below_fmv_count"] == 61


@pytest.mark.asyncio
async def test_people_summary_zero_headcount_handles_div_by_zero() -> None:
    db = _mock_db(_hr_row(w2=0, contractor=0, terminations=0))

    out = await fake_data.get_people_summary(db=db, today=date(2026, 4, 25))

    assert out["headcount_total"] == 0
    assert out["turnover_90d_pct"] == 0.0
