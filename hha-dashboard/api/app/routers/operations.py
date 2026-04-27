from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status

from ..deps import DBDep, UserDep
from ..schemas.operations import (
    DailyEntryHistoryRow,
    OperationsSummary,
    SiteDetail,
    SiteToday,
)
from ..services import entries_history, fake_data

router = APIRouter(prefix="/api/v1/operations", tags=["operations"])


@router.get("/summary", response_model=OperationsSummary)
async def operations_summary(db: DBDep, user: UserDep) -> dict[str, Any]:
    _ = user
    return await fake_data.get_operations_summary(db)


@router.get("/sites-today", response_model=list[SiteToday])
async def sites_today(db: DBDep, user: UserDep) -> list[dict[str, Any]]:
    _ = user
    return await fake_data.get_sites_today(db)


@router.get("/sites/{site_id}", response_model=SiteDetail)
async def site_detail(db: DBDep, user: UserDep, site_id: int) -> dict[str, Any]:
    """Per-facility detail: today's row + 14-day history + entered_today flag."""
    _ = user

    today_row = await fake_data.get_site_today(db, site_id)
    if today_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Site {site_id} not found")

    today = datetime.now(UTC).date()
    entries = await entries_history.get_site_recent_entries(db, site_id, days=14, today=today)
    entered_today = any(e.entry_date == today for e in entries)

    return {
        **today_row,
        "entered_today": entered_today,
        "recent_entries": [
            DailyEntryHistoryRow(
                entry_date=e.entry_date,
                census=e.census,
                open_shifts=e.open_shifts,
                entered_by_upn=e.entered_by_upn,
                source=e.source,
                notes=e.notes,
                updated_at=e.updated_at,
            )
            for e in entries
        ],
    }
