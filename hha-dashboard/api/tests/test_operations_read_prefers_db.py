"""Operations board read-prefers-DB logic.

Unit-tests `fake_data.get_sites_today()` by injecting a fake AsyncSession
whose `execute()` returns canned rows. Verifies:

1. When a site has a DailyEntry row for today, the ops board uses that value.
2. When a site has no entry, the fallback fake value is used.
3. When `db=None`, behavior is pure-fake (matches Session 3 semantics).
4. Site `id` is included in every row.

`get_sites_today` makes two SQL calls:
  Call 1: `select(Site.id, Site.name)` → rows of (id, name)
  Call 2: `select(Site.name, DailyEntry.census, DailyEntry.open_shifts)` joined → rows of (name, census, open_shifts)

The mock helper here returns canned data for each call in order.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import fake_data


def _mock_db(
    site_rows: list[tuple[int, str]],
    entry_rows: list[tuple[str, int, int]],
) -> MagicMock:
    """Build a MagicMock AsyncSession that returns site_rows then entry_rows."""
    site_result = MagicMock()
    site_result.all.return_value = site_rows
    entry_result = MagicMock()
    entry_result.all.return_value = entry_rows

    session = MagicMock()
    # First call → sites; second call → entries; reused thereafter
    session.execute = AsyncMock(side_effect=[site_result, entry_result])
    return session


# Default site roster matching ALL_SITES order, ids 1..11
_DEFAULT_SITES = [
    (1, "Westside Regional"),
    (2, "Woodmont Hospital"),
    (3, "JFK Main Med Ctr"),
    (4, "JFK North Med Ctr"),
    (5, "Palms West Hospital"),
    (6, "University Hospital"),
    (7, "Jackson Memorial"),
    (8, "Bay"),
    (9, "Doctors"),
    (10, "Huntsville"),
    (11, "Corpus"),
]


@pytest.mark.asyncio
async def test_get_sites_today_prefers_db_value() -> None:
    db = _mock_db(_DEFAULT_SITES, [("Westside Regional", 198, 3)])
    today = date(2026, 4, 23)

    rows = await fake_data.get_sites_today(db=db, today=today)
    by_name = {r["name"]: r for r in rows}

    assert by_name["Westside Regional"]["census_today"] == 198
    assert by_name["Westside Regional"]["open_shifts"] == 3


@pytest.mark.asyncio
async def test_get_sites_today_falls_back_to_zero_when_no_entry() -> None:
    """Sites without a DailyEntry row render with census=0 (Phase 1 contract).

    The pre-Phase-1 deterministic fake fallback was reverted to (0, 0) so the
    Operations Board only reflects real census submissions. See
    `_fake_site_row` in app/services/fake_data.py.
    """
    db = _mock_db(_DEFAULT_SITES, [("Westside Regional", 198, 3)])
    today = date(2026, 4, 23)

    rows = await fake_data.get_sites_today(db=db, today=today)
    by_name = {r["name"]: r for r in rows}

    # Westside has a real entry — keeps its DB value.
    assert by_name["Westside Regional"]["census_today"] == 198
    # Woodmont has no entry — now zero, not a deterministic fake.
    assert by_name["Woodmont Hospital"]["census_today"] == 0
    assert by_name["Woodmont Hospital"]["open_shifts"] == 0


@pytest.mark.asyncio
async def test_get_sites_today_no_db_is_pure_fake() -> None:
    """Backward-compat: db=None returns rows with positional fallback ids."""
    today = date(2026, 4, 23)
    rows = await fake_data.get_sites_today(db=None, today=today)

    assert len(rows) == 11
    for r in rows:
        assert r["id"] >= 1  # positional fallback
        assert r["census_today"] >= 0
        assert r["name"]
        assert r["state"] in {"FL", "TX"}


@pytest.mark.asyncio
async def test_get_sites_today_variance_uses_db_value() -> None:
    """Variance_pct is computed from the chosen census — confirm the DB value feeds it."""
    db = _mock_db(_DEFAULT_SITES, [("Westside Regional", 265, 0)])

    rows = await fake_data.get_sites_today(db=db)
    westside = next(r for r in rows if r["name"] == "Westside Regional")

    assert westside["census_today"] == 265
    assert abs(westside["variance_pct"]) < 0.5  # ~0


@pytest.mark.asyncio
async def test_get_sites_today_includes_site_id() -> None:
    """Every row carries the site id from the DB so the FE can build links."""
    db = _mock_db(_DEFAULT_SITES, [])

    rows = await fake_data.get_sites_today(db=db)
    by_name = {r["name"]: r for r in rows}

    assert by_name["Westside Regional"]["id"] == 1
    assert by_name["Corpus"]["id"] == 11
