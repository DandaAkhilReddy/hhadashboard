from pydantic import BaseModel


class ScorecardOut(BaseModel):
    physician_id: int
    name: str
    site: str
    state: str
    employment_type: str
    comp_model: str
    status: str
    rank: int
    rvu_90d: int
    below_fmv: bool
    # P2+ tiles
    revenue_per_fte_usd: int | None
    encounters_per_day: float | None
    documentation_score_pct: float | None
    chart_turnaround_days: float | None
