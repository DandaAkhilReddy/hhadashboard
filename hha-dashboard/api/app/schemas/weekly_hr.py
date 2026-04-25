"""Pydantic schemas for entries.weekly_hr_manual.

One row per week_ending — Andrea enters HHA-wide HR snapshot.
`week_ending` must be a Sunday for stable keying.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WeeklyHrIn(BaseModel):
    week_ending: date
    headcount_w2: int = Field(..., ge=0, le=10000)
    headcount_1099: int = Field(..., ge=0, le=10000)
    open_positions_total: int = Field(default=0, ge=0, le=1000)
    terminations_90d_count: int = Field(default=0, ge=0, le=1000)
    below_fmv_count: int = Field(default=0, ge=0, le=10000)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("week_ending")
    @classmethod
    def must_be_sunday_and_not_future(cls, v: date) -> date:
        if v.weekday() != 6:
            raise ValueError("week_ending must be a Sunday")
        if v > date.today() + timedelta(days=6):
            raise ValueError("week_ending cannot be more than 6 days in the future")
        return v


class WeeklyHrOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    week_ending: date
    headcount_w2: int
    headcount_1099: int
    open_positions_total: int
    terminations_90d_count: int
    below_fmv_count: int
    notes: str | None
    entered_by_upn: str
    updated_at: datetime
