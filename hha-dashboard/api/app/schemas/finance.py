from pydantic import BaseModel


class FinanceToday(BaseModel):
    fl_daily_actual: int
    fl_daily_target: int
    fl_daily_delta: int
    fl_source_system: str
    tx_daily_actual: int
    tx_daily_target: int
    tx_daily_delta: int
    tx_source_system: str
    fl_mtd_actual: int
    fl_mtd_target: int
    fl_mtd_pct: float
    ventra_fee_mtd: int


class ArBuckets(BaseModel):
    # keys: "0-30", "31-60", "61-90", "91-120", ">120"
    bucket_0_30: int
    bucket_31_60: int
    bucket_61_90: int
    bucket_91_120: int
    bucket_over_120: int


class ArAging(BaseModel):
    fl_total_usd: int
    fl_buckets: ArBuckets
    fl_over_120_pct: float
    fl_source_system: str
    tx_total_usd: int
    tx_buckets: ArBuckets
    tx_over_120_pct: float
    tx_source_system: str


class FinanceKpis(BaseModel):
    fl_days_in_ar: float
    tx_days_in_ar: float
    days_in_ar_target: int
    fl_ncr_pct: int
    tx_ncr_pct: int
    ncr_billed_at: str


class MonthRevenue(BaseModel):
    month: str
    revenue_usd: int
