"""Pydantic schemas for entries.daily_entries (Crystal's daily census form).

Two shapes:
- DailyEntryIn   — one row coming in from the client (site_id + census + shifts)
- DailyEntryOut  — one row going back to the client (adds site name + state so
                    the UI can render the 11-row table without a second fetch)

Batch save uses DailyCensusBatchIn (list of DailyEntryIn + an entry_date).
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

CENSUS_MAX = 2000
OPEN_SHIFTS_MAX = 50


class DailyEntryIn(BaseModel):
    """One site's census for a given date, coming from the UI."""

    site_id: int = Field(..., gt=0, description="masters.sites.id")
    census: int = Field(..., ge=0, le=CENSUS_MAX, description="Patient count for the day")
    open_shifts: int = Field(
        default=0, ge=0, le=OPEN_SHIFTS_MAX, description="Unfilled provider shifts"
    )
    notes: str | None = Field(default=None, max_length=500)


class DailyCensusBatchIn(BaseModel):
    """Full batch for a given date — up to 11 rows, one per site."""

    entry_date: date
    rows: list[DailyEntryIn] = Field(..., min_length=1, max_length=50)

    @field_validator("entry_date")
    @classmethod
    def not_in_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("entry_date cannot be in the future")
        return v


class DailyEntryOut(BaseModel):
    """One row for the daily-census page — joined with site name/state for display.

    `census` is `None` for sites with no entry for the requested date, so the
    form can render a blank input instead of showing zero.
    """

    model_config = ConfigDict(from_attributes=True)

    site_id: int
    site_name: str
    state: str
    entry_date: date
    census: int | None
    open_shifts: int
    entered_by_upn: str | None
    source: str | None
    notes: str | None
    updated_at: datetime | None
