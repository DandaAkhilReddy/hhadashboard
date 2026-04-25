from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# Mirrors comp.MgmaBand. Pydantic v2 prefers Literal here over a re-import
# so the OpenAPI schema names the enum cleanly.
MgmaBand = Literal["below_25", "25_50", "50_75", "75_90", "above_90"]


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

    # MGMA Internal Medicine Hospitalist comparison.
    # `mgma_band` is visible to all execs (it's a qualitative bucket, not $).
    # The dollar-amount fields below are only populated when the caller has
    # comp_viewer; otherwise they are None and the UI hides them.
    mgma_band: MgmaBand
    mgma_p50_usd: int

    # Comp-detail fields — comp_viewer only. Non-comp-viewers see None here
    # and the UI shows the band but redacts the dollar amount.
    effective_comp_usd: int | None = None
    fmv_source_note: str | None = None

    # P2+ tiles — placeholders until Athena ingestion lands
    revenue_per_fte_usd: int | None = None
    encounters_per_day: float | None = None
    documentation_score_pct: float | None = None
    chart_turnaround_days: float | None = None
