from pydantic import BaseModel


class SiteToday(BaseModel):
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
