"""Seed-script integration test.

`scripts/seed_sites.py` lands the canonical 11 sites + 7 FL contracts + named
medical directors + coverage assignments. The seed used to bail when ANY row
already existed, which let a stray "Test Site" row block the canonical 11
from ever landing. The fix is per-row fetch-or-create idempotency.

Asserts:
  - Fresh DB → seed lands 11 sites (7 FL + 4 TX).
  - Re-running on a populated DB → no duplicates, exit clean.
  - All 7 FL sites have a Contract row.
  - All non-vacant sites have a SiteCoverage MEDICAL_DIRECTOR row.

Skipped automatically if Postgres isn't reachable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.deps import SessionLocal
from app.models.masters import Contract, Physician, Site, SiteCoverage

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from seed_sites import seed  # noqa: E402

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
        pytest.skip("Postgres not reachable; skipping seed integration test")


@pytest.fixture
async def _clean_masters() -> None:
    """Truncate masters tables in FK-safe order so each test starts fresh."""
    async with SessionLocal() as db:
        await db.execute(text("TRUNCATE masters.site_coverage RESTART IDENTITY CASCADE"))
        await db.execute(text("TRUNCATE masters.contracts RESTART IDENTITY CASCADE"))
        await db.execute(text("TRUNCATE masters.sites RESTART IDENTITY CASCADE"))
        await db.execute(text("TRUNCATE masters.physicians RESTART IDENTITY CASCADE"))
        await db.commit()


@pytest.mark.usefixtures("_clean_masters")
async def test_seed_lands_eleven_sites_on_clean_db() -> None:
    await seed()
    async with SessionLocal() as db:
        rows = (await db.execute(select(Site.state))).scalars().all()
    assert len(rows) == 11
    assert sum(1 for s in rows if s == "FL") == 7
    assert sum(1 for s in rows if s == "TX") == 4


@pytest.mark.usefixtures("_clean_masters")
async def test_seed_is_idempotent() -> None:
    await seed()
    await seed()
    async with SessionLocal() as db:
        count = len((await db.execute(select(Site.id))).scalars().all())
    assert count == 11


@pytest.mark.usefixtures("_clean_masters")
async def test_seed_creates_fl_contracts() -> None:
    await seed()
    async with SessionLocal() as db:
        result = await db.execute(
            select(Contract.id).join(Site, Contract.site_id == Site.id).where(Site.state == "FL")
        )
        fl_contract_count = len(result.scalars().all())
    assert fl_contract_count == 7


@pytest.mark.usefixtures("_clean_masters")
async def test_seed_creates_md_coverage_rows() -> None:
    await seed()
    async with SessionLocal() as db:
        coverage_count = len((await db.execute(select(SiteCoverage.id))).scalars().all())
    # 6 FL sites have an MD (Westside is VACANT) + 3 TX sites (Corpus is VACANT)
    assert coverage_count == 9


@pytest.mark.usefixtures("_clean_masters")
async def test_seed_dedups_shared_md() -> None:
    """Dr. Manzoor Bevinal covers Bay, Doctors, and Huntsville — one Physician
    row should be created, not three."""
    await seed()
    async with SessionLocal() as db:
        bevinals = (
            (await db.execute(select(Physician.id).where(Physician.name == "Dr. Manzoor Bevinal")))
            .scalars()
            .all()
        )
    assert len(bevinals) == 1
