"""Seed 11 sites + FL contracts + named MDs from the HTML prototype.

Usage (from api/ directory):
    uv run python ../scripts/seed_sites.py

Idempotent — skips seeding if sites already exist.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

# Add api/ to path so `from app...` works when running from scripts/
API_DIR = Path(__file__).resolve().parent.parent / "api"
sys.path.insert(0, str(API_DIR))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.models.masters import (  # noqa: E402
    Contract,
    Physician,
    PhysicianStatus,
    Site,
    SiteCoverage,
)
from app.settings import settings  # noqa: E402


FL_SITES = [
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

TX_SITES = [
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


async def seed() -> None:
    engine = create_async_engine(settings.database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionLocal() as db:
        existing = (await db.execute(select(Site.id))).scalars().all()
        if existing:
            print(f"[seed] {len(existing)} sites already exist — skipping.")
            await engine.dispose()
            return

        print("[seed] Inserting sites...")
        all_site_specs = FL_SITES + TX_SITES
        for spec in all_site_specs:
            db.add(Site(name=spec["name"], state=spec["state"], status="ACTIVE"))
        await db.flush()

        sites_by_name = {
            site.name: site for site in (await db.execute(select(Site))).scalars()
        }

        print(f"[seed] Inserting contracts for {len(FL_SITES)} FL sites...")
        for spec in FL_SITES:
            db.add(
                Contract(
                    site_id=sites_by_name[spec["name"]].id,
                    start_date=date(2024, 1, 1),
                    end_date=spec["contract_end"],
                    annual_subsidy_usd=spec["subsidy"],
                )
            )

        print("[seed] Inserting physicians (MDs only; full roster comes from Paycom in P1)...")
        md_by_name: dict[str, Physician] = {}
        for spec in all_site_specs:
            md_name = spec["md"]
            if md_name and md_name not in md_by_name:
                phys = Physician(name=md_name, current_status=spec["md_status"])
                db.add(phys)
                md_by_name[md_name] = phys
        await db.flush()

        print("[seed] Inserting site_coverage (MD assignments)...")
        for spec in all_site_specs:
            if spec["md"]:
                phys = md_by_name[spec["md"]]
                site = sites_by_name[spec["name"]]
                db.add(
                    SiteCoverage(
                        site_id=site.id,
                        physician_id=phys.id,
                        role="MEDICAL_DIRECTOR",
                        start_date=date(2024, 1, 1),
                    )
                )

        await db.commit()
        print(
            f"[seed] ✓ Done: {len(all_site_specs)} sites, {len(FL_SITES)} FL contracts, "
            f"{len(md_by_name)} MDs, {sum(1 for s in all_site_specs if s['md'])} coverage rows."
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
