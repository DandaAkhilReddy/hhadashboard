"""Pydantic schemas for entries.weekly_clinical.

One batch covers a given (week_ending) for FL and/or TX. Aneja/Reddy enter
H&P% / DC% / avg LOS / charts audited per state.

`week_ending` is required to be a Sunday — gives a stable, predictable key.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StateCode(StrEnum):
    FL = "FL"
    TX = "TX"


LOS_MAX = Decimal(60)


class WeeklyClinicalRowIn(BaseModel):
    """One state's clinical row inside a weekly batch."""

    state: StateCode
    hp_24h_pct: Decimal = Field(..., ge=0, le=100, decimal_places=2)
    dc_48h_pct: Decimal = Field(..., ge=0, le=100, decimal_places=2)
    avg_los_days: Decimal = Field(..., ge=0, le=LOS_MAX, decimal_places=2)
    charts_audited_count: int = Field(default=0, ge=0, le=10000)
    notes: str | None = Field(default=None, max_length=1000)


class WeeklyClinicalBatchIn(BaseModel):
    week_ending: date
    rows: list[WeeklyClinicalRowIn] = Field(..., min_length=1, max_length=2)

    @field_validator("week_ending")
    @classmethod
    def must_be_sunday_and_not_future(cls, v: date) -> date:
        # Sunday = weekday() == 6 in Python (Mon=0 ... Sun=6)
        if v.weekday() != 6:
            raise ValueError("week_ending must be a Sunday")
        if v > date.today() + timedelta(days=6):
            raise ValueError("week_ending cannot be more than 6 days in the future")
        return v

    @model_validator(mode="after")
    def _unique_states(self) -> "WeeklyClinicalBatchIn":
        seen: set[StateCode] = set()
        for r in self.rows:
            if r.state in seen:
                raise ValueError(f"Duplicate state in batch: {r.state}")
            seen.add(r.state)
        return self


class WeeklyClinicalRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    week_ending: date
    state: str
    hp_24h_pct: Decimal
    dc_48h_pct: Decimal
    avg_los_days: Decimal
    charts_audited_count: int
    notes: str | None
    entered_by_upn: str
    updated_at: datetime
