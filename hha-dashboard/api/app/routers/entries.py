"""Daily-census entry endpoints: GET (pre-fill form) + POST (batch upsert).

Crystal's workflow:
    1. Opens /daily-census         → GET /api/v1/entries/daily-census?date=today
                                       → 11 rows, census=null where nothing was entered yet
    2. Types census for each site   → hits Save
    3. Client POSTs the batch      → POST /api/v1/entries/daily-census
                                       → upsert one row per site in the batch
                                       → audit listener writes one row per mutation

The upsert is keyed on (site_id, entry_date), so re-saving the same day is
idempotent — it updates in place rather than inserting duplicates.

PDF-upload path (/uploads → cron) writes the same table with source='pdf_extract'
and re-submitting via this endpoint will overwrite with source='manual'. That's
intentional: the human correction is the source of truth.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..deps import CurrentUser, DBDep, require_role
from ..models.entries import DailyEntry
from ..models.masters import Site
from ..schemas.entries import DailyCensusBatchIn, DailyEntryOut

router = APIRouter(prefix="/api/v1/entries", tags=["entries"])

# Only Crystal (owner_ops) and admins enter census. Finance/clinical/HR owners
# don't write to daily_entries.
CensusOwnerDep = Annotated[CurrentUser, Depends(require_role("admin", "owner_ops"))]


@router.get("/daily-census", response_model=list[DailyEntryOut])
async def get_daily_census(
    db: DBDep,
    user: CensusOwnerDep,
    target_date: Annotated[
        date | None,
        Query(alias="date", description="Defaults to today (server time, UTC)"),
    ] = None,
) -> list[DailyEntryOut]:
    """Return one row per site for the given date, with census=null where no entry exists.

    Stable sort by site name so the UI row order is consistent across reloads.
    """
    _ = user
    the_date = target_date or datetime.now(UTC).date()

    # LEFT OUTER JOIN via two queries (asyncpg-friendly, avoids outerjoin mapping gotchas):
    #   1. Load all sites
    #   2. Load entries for the_date, index by site_id
    #   3. Zip in Python
    sites = (await db.execute(select(Site).order_by(Site.name))).scalars().all()

    entry_rows = (
        await db.execute(
            select(DailyEntry).where(DailyEntry.entry_date == the_date)
        )
    ).scalars().all()
    by_site: dict[int, DailyEntry] = {e.site_id: e for e in entry_rows}

    out: list[DailyEntryOut] = []
    for s in sites:
        entry = by_site.get(s.id)
        out.append(
            DailyEntryOut(
                site_id=s.id,
                site_name=s.name,
                state=s.state,
                entry_date=the_date,
                census=entry.census if entry else None,
                open_shifts=entry.open_shifts if entry else 0,
                entered_by_upn=entry.entered_by_upn if entry else None,
                source=entry.source if entry else None,
                notes=entry.notes if entry else None,
                updated_at=entry.updated_at if entry else None,
            )
        )
    return out


@router.post(
    "/daily-census",
    response_model=list[DailyEntryOut],
    status_code=status.HTTP_200_OK,
)
async def save_daily_census(
    db: DBDep,
    user: CensusOwnerDep,
    batch: DailyCensusBatchIn,
) -> list[DailyEntryOut]:
    """Upsert all rows in the batch. One commit at the end → one audit txn."""

    # Validate site_ids exist before writing (clearer error than a FK violation).
    site_ids_in_batch = {r.site_id for r in batch.rows}
    existing_ids = set(
        (await db.execute(select(Site.id).where(Site.id.in_(site_ids_in_batch)))).scalars().all()
    )
    unknown = site_ids_in_batch - existing_ids
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown site_id(s): {sorted(unknown)}",
        )

    for row in batch.rows:
        stmt = (
            pg_insert(DailyEntry)
            .values(
                site_id=row.site_id,
                entry_date=batch.entry_date,
                census=row.census,
                open_shifts=row.open_shifts,
                entered_by_upn=user.upn,
                source="manual",
                pdf_sha256=None,
                notes=row.notes,
            )
            .on_conflict_do_update(
                index_elements=["site_id", "entry_date"],
                set_={
                    "census": row.census,
                    "open_shifts": row.open_shifts,
                    "entered_by_upn": user.upn,
                    "source": "manual",
                    "notes": row.notes,
                    "updated_at": datetime.now(UTC),
                },
            )
        )
        await db.execute(stmt)
    await db.commit()

    # Re-fetch in the same shape as GET so the client can diff.
    sites = {s.id: s for s in (await db.execute(select(Site))).scalars().all()}
    saved = (
        await db.execute(
            select(DailyEntry).where(
                DailyEntry.entry_date == batch.entry_date,
                DailyEntry.site_id.in_(site_ids_in_batch),
            )
        )
    ).scalars().all()

    return [
        DailyEntryOut(
            site_id=e.site_id,
            site_name=sites[e.site_id].name,
            state=sites[e.site_id].state,
            entry_date=e.entry_date,
            census=e.census,
            open_shifts=e.open_shifts,
            entered_by_upn=e.entered_by_upn,
            source=e.source,
            notes=e.notes,
            updated_at=e.updated_at,
        )
        for e in saved
    ]
