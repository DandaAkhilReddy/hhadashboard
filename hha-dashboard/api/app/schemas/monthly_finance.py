"""Pydantic schemas for entries.monthly_finance_manual.

Sandy's monthly entry form sends one batch covering both states (FL + TX) for
a given (year, month). The router upserts each row keyed on (year, month,
state). FL rows tag source_system='VENTRA_FL_FALLBACK', TX rows tag
'HHA_TX_MANUAL' — never mix the two books in the same row.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StateCode(StrEnum):
    FL = "FL"
    TX = "TX"


class SourceSystem(StrEnum):
    VENTRA_FL_ATHENA = "VENTRA_FL_ATHENA"  # auto-ingested via Ventra SFTP / Athena
    VENTRA_FL_FALLBACK = "VENTRA_FL_FALLBACK"  # Sandy's manual entry
    HHA_TX_MANUAL = "HHA_TX_MANUAL"  # always manual — no Ventra TX


# Reasonable upper bounds — bigger than any plausible HHA monthly value, small
# enough to catch typos like an extra zero.
COLLECTIONS_MAX = Decimal("100000000")  # $100M
AR_MAX = Decimal("100000000")


class MonthlyFinanceRowIn(BaseModel):
    """One state's row inside a batch."""

    state: StateCode
    collections_usd: Decimal = Field(..., ge=0, le=COLLECTIONS_MAX, decimal_places=2)
    ventra_fee_usd: Decimal = Field(default=Decimal(0), ge=0, le=COLLECTIONS_MAX, decimal_places=2)

    ar_total_usd: Decimal = Field(..., ge=0, le=AR_MAX, decimal_places=2)
    ar_0_30_usd: Decimal = Field(default=Decimal(0), ge=0, le=AR_MAX, decimal_places=2)
    ar_31_60_usd: Decimal = Field(default=Decimal(0), ge=0, le=AR_MAX, decimal_places=2)
    ar_61_90_usd: Decimal = Field(default=Decimal(0), ge=0, le=AR_MAX, decimal_places=2)
    ar_91_120_usd: Decimal = Field(default=Decimal(0), ge=0, le=AR_MAX, decimal_places=2)
    ar_over_120_usd: Decimal = Field(default=Decimal(0), ge=0, le=AR_MAX, decimal_places=2)

    net_collection_rate_pct: Decimal = Field(..., ge=0, le=100, decimal_places=2)
    days_in_ar: Decimal = Field(..., ge=0, le=Decimal(365), decimal_places=2)

    notes: str | None = Field(default=None, max_length=500)


class MonthlyFinanceBatchIn(BaseModel):
    """Sandy submits one batch per month covering FL and/or TX."""

    year: int = Field(..., ge=2020, le=2100)
    month: int = Field(..., ge=1, le=12)
    rows: list[MonthlyFinanceRowIn] = Field(..., min_length=1, max_length=2)

    @model_validator(mode="after")
    def _no_future_months_and_unique_states(self) -> MonthlyFinanceBatchIn:
        # Reject months entirely in the future (period start > today).
        period_first = date(self.year, self.month, 1)
        if period_first > date.today().replace(day=1):
            raise ValueError("Cannot enter finance for a future month")

        # Reject duplicate states inside the same batch.
        seen: set[StateCode] = set()
        for r in self.rows:
            if r.state in seen:
                raise ValueError(f"Duplicate state in batch: {r.state}")
            seen.add(r.state)
        return self


class MonthlyFinanceRowOut(BaseModel):
    """One persisted row, returned by GET + after-POST."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    year: int
    month: int
    period_first: date
    state: str
    collections_usd: Decimal
    ventra_fee_usd: Decimal
    ar_total_usd: Decimal
    ar_0_30_usd: Decimal
    ar_31_60_usd: Decimal
    ar_61_90_usd: Decimal
    ar_91_120_usd: Decimal
    ar_over_120_usd: Decimal
    net_collection_rate_pct: Decimal
    days_in_ar: Decimal
    source_system: str
    entered_by_upn: str
    notes: str | None
    updated_at: datetime
