"""Site-detail endpoint + service tests.

`get_site_today` and `get_site_recent_entries` are pure service functions tested
with a MagicMock AsyncSession. The HTTP endpoint that wires them is covered by
the e2e smoke test (manual checklist).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import entries_history, fake_data


def _mock_site(site_id: int = 1, name: str = "Westside Regional", state: str = "FL") -> SimpleNamespace:
    return SimpleNamespace(id=site_id, name=name, state=state)


def _mock_db_for_get_site_today(
    site: SimpleNamespace | None,
    entry: tuple[int, int] | None,
) -> MagicMock:
    """Mock execute() for the two queries inside get_site_today."""
    site_result = MagicMock()
    site_result.scalar_one_or_none.return_value = site

    entry_result = MagicMock()
    entry_result.first.return_value = entry  # (census, open_shifts) or None

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[site_result, entry_result])
    return db


@pytest.mark.asyncio
async def test_get_site_today_returns_db_value_when_entry_exists() -> None:
    db = _mock_db_for_get_site_today(_mock_site(1, "Westside Regional", "FL"), (198, 3))

    row = await fake_data.get_site_today(db, site_id=1, today=date(2026, 4, 25))

    assert row is not None
    assert row["id"] == 1
    assert row["name"] == "Westside Regional"
    assert row["census_today"] == 198
    assert row["open_shifts"] == 3


@pytest.mark.asyncio
async def test_get_site_today_returns_none_fields_when_no_entry() -> None:
    """Phase 1 contract: a site with no DailyEntry today renders census=None
    and open_shifts=None. The frontend renders these as "—". The
    medical-director / liaison / status / contract-end fields are also None
    until masters tables are wired (the in-code SiteSpec is no longer
    surfaced)."""
    db = _mock_db_for_get_site_today(_mock_site(2, "Woodmont Hospital", "FL"), None)

    row = await fake_data.get_site_today(db, site_id=2, today=date(2026, 4, 25))

    assert row is not None
    assert row["name"] == "Woodmont Hospital"
    assert row["census_today"] is None
    assert row["open_shifts"] is None
    # Soft fields are no longer surfaced from the SiteSpec — they read empty.
    assert row["medical_director"] is None
    assert row["md_status"] is None
    assert row["liaison"] is None
    assert row["contract_end"] is None
    # Subsidy is the one exception — kept until masters.contracts is wired.
    assert row["annual_subsidy_usd"] >= 0


@pytest.mark.asyncio
async def test_get_site_today_returns_none_for_unknown_site() -> None:
    db = _mock_db_for_get_site_today(None, None)

    row = await fake_data.get_site_today(db, site_id=9999, today=date(2026, 4, 25))

    assert row is None


@pytest.mark.asyncio
async def test_get_site_today_keeps_only_subsidy_among_soft_fields() -> None:
    """Phase 1: every soft field (MD, liaison, MD status, contract end) reads
    None — they'll be populated from masters tables once an admin UI exists.
    Subsidy is the one exception that still flows through from the SiteSpec
    until masters.contracts is wired."""
    db = _mock_db_for_get_site_today(_mock_site(1, "Westside Regional", "FL"), (200, 0))

    row = await fake_data.get_site_today(db, site_id=1)

    assert row is not None
    # Census flows through from the DB.
    assert row["census_today"] == 200
    # Soft fields all empty.
    assert row["medical_director"] is None
    assert row["md_status"] is None
    assert row["liaison"] is None
    assert row["contract_end"] is None
    # Subsidy is the kept exception.
    assert row["annual_subsidy_usd"] > 0


# ----- entries_history -----


@pytest.mark.asyncio
async def test_get_site_recent_entries_uses_correct_window() -> None:
    """The query should filter to [today - days + 1, today], newest-first."""
    today = date(2026, 4, 25)

    fake_entries = [
        SimpleNamespace(
            site_id=1,
            entry_date=today,
            census=198,
            open_shifts=3,
            entered_by_upn="crystal@hha.com",
            source="manual",
            notes=None,
            updated_at=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
        ),
        SimpleNamespace(
            site_id=1,
            entry_date=date(2026, 4, 24),
            census=195,
            open_shifts=3,
            entered_by_upn="crystal@hha.com",
            source="manual",
            notes=None,
            updated_at=datetime(2026, 4, 24, 9, 0, tzinfo=UTC),
        ),
    ]
    scalars = MagicMock()
    scalars.all.return_value = fake_entries
    result = MagicMock()
    result.scalars.return_value = scalars
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    out = await entries_history.get_site_recent_entries(db, site_id=1, days=14, today=today)

    assert len(out) == 2
    assert out[0].entry_date == today
    assert out[1].entry_date == date(2026, 4, 24)


@pytest.mark.asyncio
async def test_get_site_recent_entries_empty_returns_empty_list() -> None:
    scalars = MagicMock()
    scalars.all.return_value = []
    result = MagicMock()
    result.scalars.return_value = scalars
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    out = await entries_history.get_site_recent_entries(db, site_id=42)

    assert out == []
