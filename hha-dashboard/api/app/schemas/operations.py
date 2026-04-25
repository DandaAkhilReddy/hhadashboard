from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class SiteToday(BaseModel):
    id: int
    name: str
    state: str
    medical_director: str | None
    md_status: str
    liaison: str | None
    census_today: int
    census_3mo_avg: int
    mtd_avg: float
    variance_pct: float
    open_shifts: int
    contract_end: str
    annual_subsidy_usd: int


class OperationsSummary(BaseModel):
    total_fl_census: int
    total_tx_census: int
    total_fl_3mo_avg: int
    census_variance_vs_avg: int
    sites_below_avg: int
    open_shifts_total: int
    fl_site_count: int
    tx_site_count: int


class DailyEntryHistoryRow(BaseModel):
    """One past entry for a site — read-only on the detail page."""

    entry_date: date
    census: int
    open_shifts: int
    entered_by_upn: str
    source: str
    notes: str | None
    updated_at: datetime | None


class SiteDetail(SiteToday):
    """Per-facility drill-down: today's row + recent history + entered-today flag."""

    entered_today: bool
    recent_entries: list[DailyEntryHistoryRow]
