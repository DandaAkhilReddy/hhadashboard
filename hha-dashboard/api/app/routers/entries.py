"""Entry endpoints — daily census (Crystal) + monthly finance (Sandy).

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

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..deps import CurrentUser, DBDep, require_role
from ..models.entries import DailyEntry
from ..models.entries_clinical import WeeklyClinical
from ..models.entries_finance import MonthlyFinanceManual
from ..models.entries_hr import WeeklyHrManual
from ..models.masters import Site
from ..schemas.entries import DailyCensusBatchIn, DailyEntryOut
from ..schemas.monthly_finance import (
    MonthlyFinanceBatchIn,
    MonthlyFinanceRowOut,
    SourceSystem,
    StateCode,
)
from ..schemas.weekly_clinical import WeeklyClinicalBatchIn, WeeklyClinicalRowOut
from ..schemas.weekly_hr import WeeklyHrIn, WeeklyHrOut

router = APIRouter(prefix="/api/v1/entries", tags=["entries"])

# Only Crystal (owner_ops) and admins enter census. Finance/clinical/HR owners
# don't write to daily_entries.
CensusOwnerDep = Annotated[CurrentUser, Depends(require_role("admin", "owner_ops"))]

# Sandy (owner_finance) + admin enter monthly finance.
FinanceOwnerDep = Annotated[CurrentUser, Depends(require_role("admin", "owner_finance"))]

# Aneja / Reddy (owner_clinical) + admin enter weekly clinical audits.
ClinicalOwnerDep = Annotated[CurrentUser, Depends(require_role("admin", "owner_clinical"))]

# Andrea (owner_hr) + admin enter weekly HR rollup.
HrOwnerDep = Annotated[CurrentUser, Depends(require_role("admin", "owner_hr"))]


def _source_for_state(state: StateCode) -> SourceSystem:
    """Map state to its provenance tag. Hard-coded by the FL-only Ventra scope decision."""
    return SourceSystem.VENTRA_FL_FALLBACK if state == StateCode.FL else SourceSystem.HHA_TX_MANUAL


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


# ---------- Monthly finance ----------


@router.get("/monthly-finance", response_model=list[MonthlyFinanceRowOut])
async def get_monthly_finance(
    db: DBDep,
    user: FinanceOwnerDep,
    year: Annotated[int | None, Query(ge=2020, le=2100)] = None,
    month: Annotated[int | None, Query(ge=1, le=12)] = None,
) -> list[MonthlyFinanceManual]:
    """Return rows for a given (year, month). Defaults to the most recent
    completed month so the form pre-fills sensible values.
    """
    _ = user
    if year is None or month is None:
        today = datetime.now(UTC).date()
        # Default to last month
        year = today.year if today.month > 1 else today.year - 1
        month = today.month - 1 if today.month > 1 else 12

    stmt = select(MonthlyFinanceManual).where(
        MonthlyFinanceManual.year == year,
        MonthlyFinanceManual.month == month,
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/monthly-finance",
    response_model=list[MonthlyFinanceRowOut],
    status_code=status.HTTP_200_OK,
)
async def save_monthly_finance(
    db: DBDep,
    user: FinanceOwnerDep,
    batch: MonthlyFinanceBatchIn,
) -> list[MonthlyFinanceManual]:
    """Upsert each (year, month, state) row in the batch."""
    period_first = date(batch.year, batch.month, 1)

    for row in batch.rows:
        source = _source_for_state(row.state).value
        stmt = (
            pg_insert(MonthlyFinanceManual)
            .values(
                year=batch.year,
                month=batch.month,
                period_first=period_first,
                state=row.state.value,
                collections_usd=row.collections_usd,
                ventra_fee_usd=row.ventra_fee_usd,
                ar_total_usd=row.ar_total_usd,
                ar_0_30_usd=row.ar_0_30_usd,
                ar_31_60_usd=row.ar_31_60_usd,
                ar_61_90_usd=row.ar_61_90_usd,
                ar_91_120_usd=row.ar_91_120_usd,
                ar_over_120_usd=row.ar_over_120_usd,
                net_collection_rate_pct=row.net_collection_rate_pct,
                days_in_ar=row.days_in_ar,
                source_system=source,
                entered_by_upn=user.upn,
                notes=row.notes,
            )
            .on_conflict_do_update(
                index_elements=["year", "month", "state"],
                set_={
                    "collections_usd": row.collections_usd,
                    "ventra_fee_usd": row.ventra_fee_usd,
                    "ar_total_usd": row.ar_total_usd,
                    "ar_0_30_usd": row.ar_0_30_usd,
                    "ar_31_60_usd": row.ar_31_60_usd,
                    "ar_61_90_usd": row.ar_61_90_usd,
                    "ar_91_120_usd": row.ar_91_120_usd,
                    "ar_over_120_usd": row.ar_over_120_usd,
                    "net_collection_rate_pct": row.net_collection_rate_pct,
                    "days_in_ar": row.days_in_ar,
                    "source_system": source,
                    "entered_by_upn": user.upn,
                    "notes": row.notes,
                    "updated_at": datetime.now(UTC),
                },
            )
        )
        await db.execute(stmt)
    await db.commit()

    saved = (
        await db.execute(
            select(MonthlyFinanceManual).where(
                MonthlyFinanceManual.year == batch.year,
                MonthlyFinanceManual.month == batch.month,
                MonthlyFinanceManual.state.in_([r.state.value for r in batch.rows]),
            )
        )
    ).scalars().all()
    return list(saved)


# ---------- Weekly clinical ----------


def _last_sunday(today: date) -> date:
    """Return the most recent Sunday on or before `today`."""
    return today - timedelta(days=(today.weekday() + 1) % 7)


@router.get("/weekly-clinical", response_model=list[WeeklyClinicalRowOut])
async def get_weekly_clinical(
    db: DBDep,
    user: ClinicalOwnerDep,
    week_ending: Annotated[date | None, Query()] = None,
) -> list[WeeklyClinical]:
    """Return both states' rows for a given week_ending. Defaults to last Sunday."""
    _ = user
    target = week_ending or _last_sunday(datetime.now(UTC).date())

    stmt = select(WeeklyClinical).where(WeeklyClinical.week_ending == target)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/weekly-clinical",
    response_model=list[WeeklyClinicalRowOut],
    status_code=status.HTTP_200_OK,
)
async def save_weekly_clinical(
    db: DBDep,
    user: ClinicalOwnerDep,
    batch: WeeklyClinicalBatchIn,
) -> list[WeeklyClinical]:
    """Upsert each (week_ending, state) row in the batch."""
    for row in batch.rows:
        stmt = (
            pg_insert(WeeklyClinical)
            .values(
                week_ending=batch.week_ending,
                state=row.state.value,
                hp_24h_pct=row.hp_24h_pct,
                dc_48h_pct=row.dc_48h_pct,
                avg_los_days=row.avg_los_days,
                charts_audited_count=row.charts_audited_count,
                notes=row.notes,
                entered_by_upn=user.upn,
            )
            .on_conflict_do_update(
                index_elements=["week_ending", "state"],
                set_={
                    "hp_24h_pct": row.hp_24h_pct,
                    "dc_48h_pct": row.dc_48h_pct,
                    "avg_los_days": row.avg_los_days,
                    "charts_audited_count": row.charts_audited_count,
                    "notes": row.notes,
                    "entered_by_upn": user.upn,
                    "updated_at": datetime.now(UTC),
                },
            )
        )
        await db.execute(stmt)
    await db.commit()

    saved = (
        await db.execute(
            select(WeeklyClinical).where(
                WeeklyClinical.week_ending == batch.week_ending,
                WeeklyClinical.state.in_([r.state.value for r in batch.rows]),
            )
        )
    ).scalars().all()
    return list(saved)


# ---------- Weekly HR ----------


@router.get("/weekly-hr", response_model=WeeklyHrOut | None)
async def get_weekly_hr(
    db: DBDep,
    user: HrOwnerDep,
    week_ending: Annotated[date | None, Query()] = None,
) -> WeeklyHrManual | None:
    """Return the row for a given week_ending. Defaults to last Sunday.

    Returns null if no entry exists yet for that week — the form treats null
    as a fresh form.
    """
    _ = user
    target = week_ending or _last_sunday(datetime.now(UTC).date())

    stmt = select(WeeklyHrManual).where(WeeklyHrManual.week_ending == target)
    return (await db.execute(stmt)).scalar_one_or_none()


@router.post(
    "/weekly-hr",
    response_model=WeeklyHrOut,
    status_code=status.HTTP_200_OK,
)
async def save_weekly_hr(
    db: DBDep,
    user: HrOwnerDep,
    payload: WeeklyHrIn,
) -> WeeklyHrManual:
    """Upsert one (week_ending) row."""
    stmt = (
        pg_insert(WeeklyHrManual)
        .values(
            week_ending=payload.week_ending,
            headcount_w2=payload.headcount_w2,
            headcount_1099=payload.headcount_1099,
            open_positions_total=payload.open_positions_total,
            terminations_90d_count=payload.terminations_90d_count,
            below_fmv_count=payload.below_fmv_count,
            notes=payload.notes,
            entered_by_upn=user.upn,
        )
        .on_conflict_do_update(
            index_elements=["week_ending"],
            set_={
                "headcount_w2": payload.headcount_w2,
                "headcount_1099": payload.headcount_1099,
                "open_positions_total": payload.open_positions_total,
                "terminations_90d_count": payload.terminations_90d_count,
                "below_fmv_count": payload.below_fmv_count,
                "notes": payload.notes,
                "entered_by_upn": user.upn,
                "updated_at": datetime.now(UTC),
            },
        )
    )
    await db.execute(stmt)
    await db.commit()

    saved = (
        await db.execute(
            select(WeeklyHrManual).where(WeeklyHrManual.week_ending == payload.week_ending)
        )
    ).scalar_one()
    return saved
