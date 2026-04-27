"""Seed 11 sites + FL contracts + named MDs from the HTML prototype.

Usage (from api/ directory):
    uv run python ../scripts/seed_sites.py

Idempotent. Safe to re-run; converges to the canonical 11 sites + FL contracts
+ MDs + coverage assignments. Does NOT delete unknown rows (e.g. a stray test
row gets left alone — operator removes manually).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent / "api"
sys.path.insert(0, str(API_DIR))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.models.masters import (  # noqa: E402
    Contract,
    CoverageRole,
    Physician,
    PhysicianStatus,
    Site,
    SiteCoverage,
    SiteStatus,
)
from app.settings import settings  # noqa: E402


FL_SITES: list[dict] = [
    {
        "name": "Westside Regional",
        "state": "FL",
        "md": None,
        "md_status": PhysicianStatus.VACANT.value,
        "contract_end": date(2027, 12, 31),
        "subsidy": 2_061_326,
    },
    {
        "name": "Woodmont Hospital",
        "state": "FL",
        "md": "Dr. Franklyn",
        "md_status": PhysicianStatus.PIP.value,
        "contract_end": date(2027, 12, 31),
        "subsidy": 2_208_849,
    },
    {
        "name": "JFK Main Med Ctr",
        "state": "FL",
        "md": "Dr. Susan Hanson",
        "md_status": PhysicianStatus.ACTIVE.value,
        "contract_end": date(2027, 8, 31),
        "subsidy": 3_024_261,
    },
    {
        "name": "JFK North Med Ctr",
        "state": "FL",
        "md": "Dr. Dario Martinez",
        "md_status": PhysicianStatus.ACTIVE.value,
        "contract_end": date(2027, 8, 31),
        "subsidy": 1_131_138,
    },
    {
        "name": "Palms West Hospital",
        "state": "FL",
        "md": "Dr. Thomas Abraham",
        "md_status": PhysicianStatus.ACTIVE.value,
        "contract_end": date(2027, 8, 31),
        "subsidy": 1_190_175,
    },
    {
        "name": "University Hospital",
        "state": "FL",
        "md": "Dr. Ashkan Jafarbay",
        "md_status": PhysicianStatus.ACTIVE.value,
        "contract_end": date(2027, 12, 31),
        "subsidy": 1_055_488,
    },
    {
        "name": "Jackson Memorial",
        "state": "FL",
        "md": "Dr. Esam Khalifa",
        "md_status": PhysicianStatus.ACTIVE.value,
        "contract_end": date(2027, 4, 4),
        "subsidy": 971_328,
    },
]

TX_SITES: list[dict] = [
    {
        "name": "Bay",
        "state": "TX",
        "md": "Dr. Manzoor Bevinal",
        "md_status": PhysicianStatus.ACTIVE.value,
    },
    {
        "name": "Doctors",
        "state": "TX",
        "md": "Dr. Manzoor Bevinal",
        "md_status": PhysicianStatus.ACTIVE.value,
    },
    {
        "name": "Huntsville",
        "state": "TX",
        "md": "Dr. Manzoor Bevinal",
        "md_status": PhysicianStatus.ACTIVE.value,
    },
    {
        "name": "Corpus",
        "state": "TX",
        "md": None,
        "md_status": PhysicianStatus.VACANT.value,
    },
]


async def _ensure_site(db: AsyncSession, spec: dict) -> Site:
    """Return existing Site by name, or create if absent."""
    existing = await db.scalar(select(Site).where(Site.name == spec["name"]))
    if existing is not None:
        return existing
    site = Site(name=spec["name"], state=spec["state"], status=SiteStatus.ACTIVE.value)
    db.add(site)
    await db.flush()
    return site


async def _ensure_contract(db: AsyncSession, site_id: int, spec: dict) -> None:
    """Insert a Contract row for site_id if no contract for that site exists."""
    existing = await db.scalar(select(Contract).where(Contract.site_id == site_id))
    if existing is not None:
        return
    db.add(
        Contract(
            site_id=site_id,
            start_date=date(2024, 1, 1),
            end_date=spec["contract_end"],
            annual_subsidy_usd=spec["subsidy"],
        )
    )


async def _ensure_physician(db: AsyncSession, name: str, status: str) -> Physician:
    """Return existing Physician by name, or create if absent."""
    existing = await db.scalar(select(Physician).where(Physician.name == name))
    if existing is not None:
        return existing
    phys = Physician(name=name, current_status=status)
    db.add(phys)
    await db.flush()
    return phys


async def _ensure_coverage(
    db: AsyncSession, site_id: int, physician_id: int
) -> None:
    """Insert SiteCoverage row for (site, physician, MEDICAL_DIRECTOR) if absent."""
    existing = await db.scalar(
        select(SiteCoverage).where(
            SiteCoverage.site_id == site_id,
            SiteCoverage.physician_id == physician_id,
            SiteCoverage.role == CoverageRole.MEDICAL_DIRECTOR.value,
        )
    )
    if existing is not None:
        return
    db.add(
        SiteCoverage(
            site_id=site_id,
            physician_id=physician_id,
            role=CoverageRole.MEDICAL_DIRECTOR.value,
            start_date=date(2024, 1, 1),
        )
    )


async def seed() -> None:
    engine = create_async_engine(settings.database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionLocal() as db:
        all_specs = FL_SITES + TX_SITES
        sites_inserted = 0
        contracts_inserted = 0
        mds_inserted = 0
        coverage_inserted = 0

        for spec in all_specs:
            before_site = await db.scalar(
                select(Site.id).where(Site.name == spec["name"])
            )
            site = await _ensure_site(db, spec)
            if before_site is None:
                sites_inserted += 1

            if spec["state"] == "FL":
                before_contract = await db.scalar(
                    select(Contract.id).where(Contract.site_id == site.id)
                )
                await _ensure_contract(db, site.id, spec)
                if before_contract is None:
                    contracts_inserted += 1

            if spec["md"]:
                before_md = await db.scalar(
                    select(Physician.id).where(Physician.name == spec["md"])
                )
                phys = await _ensure_physician(db, spec["md"], spec["md_status"])
                if before_md is None:
                    mds_inserted += 1

                before_cov = await db.scalar(
                    select(SiteCoverage.id).where(
                        SiteCoverage.site_id == site.id,
                        SiteCoverage.physician_id == phys.id,
                        SiteCoverage.role == CoverageRole.MEDICAL_DIRECTOR.value,
                    )
                )
                await _ensure_coverage(db, site.id, phys.id)
                if before_cov is None:
                    coverage_inserted += 1

        await db.commit()

        total_sites = await db.scalar(select(Site.id).order_by(Site.id.desc()))
        total_count = len((await db.execute(select(Site.id))).scalars().all())

        print(
            f"[seed] +{sites_inserted} sites, +{contracts_inserted} contracts, "
            f"+{mds_inserted} MDs, +{coverage_inserted} coverage rows. "
            f"DB now has {total_count} total sites."
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
