"""Physician monthly file parser — entries.fact_revenue_by_physician_mo
source rows.

Per ADR-006, Ventra writes one ``physician_monthly.csv`` ONLY on month-
close drops (typically the 1st-3rd of each month, covering the prior
month's data). The file is omitted on most daily drops.

This module owns V5 (schema match), V7 (month is first-of-month), and
V11 (10-digit NPI; non-negative encounter / RVU counts).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ._loop import parse_csv_rows


class PhysicianMonthlyRow(BaseModel):
    """One ``physician_monthly.csv`` row."""

    model_config = ConfigDict(extra="forbid", strict=False)

    # V7 (month is first-of-month) checked in the model_validator below.
    month: date
    # V11 NPI shape — 10 ASCII digits, no formatting characters.
    physician_npi: str = Field(pattern=r"^[0-9]{10}$")
    facility_no: int = Field(gt=0)
    # V11 — encounters non-negative.
    encounters_count: int = Field(ge=0)
    # V11 — RVU sums non-negative. total_work_rvu defaults to 0 because
    # not every encounter has work-RVU mapping (e.g. NP supervision).
    total_rvu: Decimal = Field(default=Decimal(0), ge=0)
    total_work_rvu: Decimal = Field(default=Decimal(0), ge=0)
    revenue_attributed: Decimal
    # Ventra's PM-system tag — accepted, discarded at write.
    source_system: str

    @model_validator(mode="after")
    def _v7_month_is_first_of_month(self) -> "PhysicianMonthlyRow":
        """V7 — ``month`` must be the first day of the month it names.

        Mirrors the DB CHECK ``month = date_trunc('month', month)::date``
        on ``entries.fact_revenue_by_physician_mo`` from migration 0011.
        Catches drift early (vendor sends 2026-05-31 instead of 2026-05-01)
        before the DB rejects the upsert.
        """
        if self.month.day != 1:
            raise ValueError(
                f"V7: month={self.month.isoformat()} is not the first day "
                f"of its month (day={self.month.day})"
            )
        return self


def parse_physician_monthly(data: bytes) -> list[PhysicianMonthlyRow]:
    """Parse ``physician_monthly.csv`` bytes into ``PhysicianMonthlyRow``."""
    return parse_csv_rows(data, PhysicianMonthlyRow, "physician_monthly.csv")
