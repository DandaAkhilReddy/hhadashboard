"""Clinical board read-prefers-DB logic.

Verifies `get_clinical_summary` prefers the most-recent WeeklyClinical row
per state over the deterministic fake values.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import fake_data


def _clin_row(
    *,
    week_ending: date,
    state: str,
    hp_pct: float = 96,
    dc_pct: float = 92,
    los_days: float = 4.5,
    charts: int = 50,
) -> SimpleNamespace:
    return SimpleNamespace(
        week_ending=week_ending,
        state=state,
        hp_24h_pct=Decimal(str(hp_pct)),
        dc_48h_pct=Decimal(str(dc_pct)),
        avg_los_days=Decimal(str(los_days)),
        charts_audited_count=charts,
        notes=None,
    )


def _mock_db(rows: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_clinical_summary_prefers_db_for_los() -> None:
    today = date(2026, 4, 25)
    db = _mock_db(
        [
            _clin_row(week_ending=date(2026, 4, 19), state="FL", los_days=4.8),
            _clin_row(week_ending=date(2026, 4, 19), state="TX", los_days=3.5),
        ]
    )

    out = await fake_data.get_clinical_summary(db=db, today=today)

    assert out["los_fl_days"] == 4.8
    assert out["los_tx_days"] == 3.5


@pytest.mark.asyncio
async def test_clinical_summary_averages_hp_dc_across_states() -> None:
    today = date(2026, 4, 25)
    db = _mock_db(
        [
            _clin_row(week_ending=date(2026, 4, 19), state="FL", hp_pct=98, dc_pct=94),
            _clin_row(week_ending=date(2026, 4, 19), state="TX", hp_pct=92, dc_pct=88),
        ]
    )

    out = await fake_data.get_clinical_summary(db=db, today=today)

    # Headline = avg of FL + TX
    assert out["hp_24h_pct"] == 95.0
    assert out["dc_48h_pct"] == 91.0


@pytest.mark.asyncio
async def test_clinical_summary_uses_only_most_recent_per_state() -> None:
    """Older rows are ignored in favor of the most recent week_ending per state."""
    today = date(2026, 4, 25)
    db = _mock_db(
        [
            # Newest (returned first by ORDER BY desc)
            _clin_row(week_ending=date(2026, 4, 19), state="FL", los_days=4.0),
            # Older — should be ignored
            _clin_row(week_ending=date(2026, 4, 12), state="FL", los_days=10.0),
        ]
    )

    out = await fake_data.get_clinical_summary(db=db, today=today)
    assert out["los_fl_days"] == 4.0


@pytest.mark.asyncio
async def test_clinical_summary_falls_back_for_state_with_no_entry() -> None:
    today = date(2026, 4, 25)
    db = _mock_db([_clin_row(week_ending=date(2026, 4, 19), state="FL", los_days=4.5)])

    out = await fake_data.get_clinical_summary(db=db, today=today)

    assert out["los_fl_days"] == 4.5
    # TX falls back to default (3.9)
    assert out["los_tx_days"] == 3.9


@pytest.mark.asyncio
async def test_clinical_summary_no_db_is_pure_fake() -> None:
    out = await fake_data.get_clinical_summary(db=None)
    assert out["hp_24h_target"] == 95
    assert out["los_fl_days"] == 4.2
    assert out["los_tx_days"] == 3.9
