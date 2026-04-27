from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class SiteToday(BaseModel):
    """One row of the Operations Board.

    Phase 1 contract: only `id`, `name`, `state`, and `annual_subsidy_usd` are
    guaranteed non-null. Every other field is `None` until real operational
    data lands (census + open_shifts from a portal/owner-form entry; MD,
    liaison, contract details from masters tables once admins populate them).
    The frontend renders `null` as "—" everywhere.
    """

    id: int
    name: str
    state: str
    medical_director: str | None
    md_status: str | None
    liaison: str | None
    census_today: int | None
    census_3mo_avg: int | None
    mtd_avg: float | None
    variance_pct: float | None
    open_shifts: int | None
    contract_end: str | None
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
    # Phase 1 census-portal integration: how fresh is today's data?
    facilities_reported: int
    facilities_missing: int
    last_updated_at: datetime | None


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
