"""Operations board read-prefers-DB logic.

Unit-tests `fake_data.get_sites_today()` by injecting a fake AsyncSession
whose `execute()` returns canned DailyEntry rows. Verifies:

1. When a site has a DailyEntry row for today, the ops board uses that value.
2. When a site has no entry, the fallback fake value is used.
3. When `db=None`, behavior is pure-fake (matches Session 3 semantics).

We don't go through the HTTP router here — that path requires Postgres to
resolve the DBDep. The read-prefer logic is a pure service function, so the
cheapest test is to unit-test it directly.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import fake_data


def _mock_db_with_rows(rows: list[tuple[str, int, int]]) -> MagicMock:
    """Return a MagicMock AsyncSession whose .execute().all() returns `rows`.

    Each row is (site_name, census, open_shifts) — matches the shape of the
    join select in get_sites_today.
    """
    result = MagicMock()
    result.all.return_value = rows
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_get_sites_today_prefers_db_value() -> None:
    db = _mock_db_with_rows([("Westside Regional", 198, 3)])
    today = date(2026, 4, 23)

    rows = await fake_data.get_sites_today(db=db, today=today)
    by_name = {r["name"]: r for r in rows}

    assert by_name["Westside Regional"]["census_today"] == 198
    assert by_name["Westside Regional"]["open_shifts"] == 3


@pytest.mark.asyncio
async def test_get_sites_today_falls_back_when_no_entry() -> None:
    """Sites without a DailyEntry row still render, using the fake value."""
    db = _mock_db_with_rows([("Westside Regional", 198, 3)])
    today = date(2026, 4, 23)

    rows = await fake_data.get_sites_today(db=db, today=today)
    by_name = {r["name"]: r for r in rows}

    # Woodmont has no entry in the mock — should come from _fake_site_row
    assert by_name["Woodmont Hospital"]["census_today"] > 0
    assert by_name["Woodmont Hospital"]["census_today"] != 198


@pytest.mark.asyncio
async def test_get_sites_today_no_db_is_pure_fake() -> None:
    """Backward-compat: db=None returns the old fake-only shape."""
    today = date(2026, 4, 23)
    rows = await fake_data.get_sites_today(db=None, today=today)

    # All 11 sites returned, census > 0 everywhere except intentionally tiny TX sites
    assert len(rows) == 11
    for r in rows:
        assert r["census_today"] >= 0
        assert r["name"]
        assert r["state"] in {"FL", "TX"}


@pytest.mark.asyncio
async def test_get_sites_today_variance_uses_db_value() -> None:
    """Variance_pct is computed from the chosen census — confirm the DB value feeds it."""
    # Westside 3mo avg is 265. If DB says 265, variance should be ~0.
    db = _mock_db_with_rows([("Westside Regional", 265, 0)])

    rows = await fake_data.get_sites_today(db=db)
    westside = next(r for r in rows if r["name"] == "Westside Regional")

    assert westside["census_today"] == 265
    assert abs(westside["variance_pct"]) < 0.5  # ~0
