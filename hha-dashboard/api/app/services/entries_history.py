"""History queries for entries.daily_entries — feeds the per-site detail page."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.entries import DailyEntry


async def get_site_recent_entries(
    db: AsyncSession,
    site_id: int,
    days: int = 14,
    today: date | None = None,
) -> list[DailyEntry]:
    """Return DailyEntry rows for a single site over the trailing `days` days.

    Newest first. Used to render the per-facility 14-day trend + history table.
    """
    today = today or date.today()
    earliest = today - timedelta(days=days - 1)

    stmt = (
        select(DailyEntry)
        .where(
            DailyEntry.site_id == site_id,
            DailyEntry.entry_date >= earliest,
            DailyEntry.entry_date <= today,
        )
        .order_by(desc(DailyEntry.entry_date))
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
