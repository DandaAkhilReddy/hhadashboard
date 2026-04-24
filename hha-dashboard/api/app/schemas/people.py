from pydantic import BaseModel


class PeopleSummary(BaseModel):
    headcount_w2: int
    headcount_1099: int
    headcount_total: int
    open_positions_total: int
    turnover_90d_pct: float
    below_fmv_count: int


class OpenPositionBySite(BaseModel):
    site: str
    state: str
    count: int
    severity: str  # "high" | "medium" | "low"
