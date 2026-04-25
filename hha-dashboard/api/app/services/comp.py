"""Physician compensation computations.

Two responsibilities:

1. **Effective comp at a given date** — given a physician_id and as-of date,
   roll up the active comp_agreement (base salary + RVU portion + stipends)
   into a single annualized total-comp dollar amount. This is the number
   we compare against MGMA benchmarks.

2. **MGMA Internal Medicine Hospitalist FMV bands** — the publicly cited
   approximation values used until HHA's licensed MGMA Provider Compensation
   Survey data is loaded into a `mgma_benchmarks` table (deferred — see
   ADR-001 footnote on FMV).

   The values below are **illustrative round-number approximations** drawn
   from publicly reported ranges (Medscape Hospitalist Compensation Reports,
   MGMA press releases). They are **NOT** the licensed MGMA Provider
   Compensation Survey values and must not be used for actual FMV defense.
   Replace via:
     - tenant admin adds the licensed values to `mgma_benchmarks` table, OR
     - HHA legal redlines this constant and the test fixtures.

The "below FMV" rule used here matches the existing People board: a
physician's total annualized comp below the **25th percentile** of the
specialty band is flagged as below-FMV (i.e., we are likely under-paying
relative to the broader market — note: the other tail, "above the 90th",
is the FMV-defense risk and is *separately* tracked, not in this v1).
"""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal
from typing import Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.masters import CompAgreement

# ---------------------------------------------------------------------------
# MGMA Internal Medicine Hospitalist — public-approximation v1 (2024 ranges)
# ---------------------------------------------------------------------------
# !!! NOT licensed MGMA data. See module docstring. Replace before relying
# !!! on these for any actual comp / FMV decision.

MGMA_SPECIALTY: Final = "Internal Medicine — Hospitalist"
MGMA_SOURCE_NOTE: Final = (
    "Public-approximation v1 (2024). Replace with HHA's licensed MGMA "
    "Provider Compensation Survey values before any FMV-defense use."
)

MGMA_IM_HOSPITALIST_TOTAL_COMP_USD: Final[dict[int, int]] = {
    25: 270_000,
    50: 320_000,
    75: 385_000,
    90: 460_000,
}

MGMA_IM_HOSPITALIST_WRVU_PER_FTE: Final[dict[int, int]] = {
    25: 4_400,
    50: 5_300,
    75: 6_400,
    90: 7_700,
}

MgmaBand = Literal["below_25", "25_50", "50_75", "75_90", "above_90"]


def compute_mgma_band(comp_usd: int) -> MgmaBand:
    """Classify a total-comp value into its MGMA percentile band.

    Args:
        comp_usd: Annualized total compensation, USD.

    Returns:
        One of "below_25", "25_50", "50_75", "75_90", "above_90".
    """
    bands = MGMA_IM_HOSPITALIST_TOTAL_COMP_USD
    if comp_usd < bands[25]:
        return "below_25"
    if comp_usd < bands[50]:
        return "25_50"
    if comp_usd < bands[75]:
        return "50_75"
    if comp_usd < bands[90]:
        return "75_90"
    return "above_90"


def is_below_fmv(comp_usd: int) -> bool:
    """True when the physician's comp is below the 25th-percentile band.

    Matches the People board's existing `below_fmv_count` semantics.
    """
    return comp_usd < MGMA_IM_HOSPITALIST_TOTAL_COMP_USD[25]


def mgma_benchmark_50th_usd() -> int:
    """The 50th-percentile total-comp benchmark for the configured specialty."""
    return MGMA_IM_HOSPITALIST_TOTAL_COMP_USD[50]


# ---------------------------------------------------------------------------
# Effective comp from a CompAgreement
# ---------------------------------------------------------------------------


def annualize_comp_agreement(agreement: CompAgreement) -> int:
    """Roll a single CompAgreement into one annualized total-comp number.

    Combines base salary + (RVU rate × annual threshold) + call stipend.
    Per-diem agreements with no base produce 0 here — they don't have a
    salaried equivalent at the agreement level; use payroll for those.

    All values are coerced to int USD. Decimal precision below the dollar
    is dropped intentionally — bands are 5-figure round numbers.
    """
    base = _to_int(agreement.base_salary_usd)
    rvu_rate = _to_decimal(agreement.rvu_rate_usd)
    rvu_threshold = agreement.rvu_threshold_annual or 0
    rvu_part = int(rvu_rate * Decimal(rvu_threshold)) if rvu_rate else 0
    stipend = _to_int(agreement.call_stipend_usd)
    return base + rvu_part + stipend


async def effective_comp_at(
    db: AsyncSession,
    physician_id: int,
    as_of: date_type,
) -> int | None:
    """Return the annualized comp for a physician on a given date.

    Picks the comp_agreement whose [effective_from, effective_to) window
    contains `as_of`. If none, returns None — the caller decides whether
    that's "no data" (fall back to fake) or an error.
    """
    stmt = (
        select(CompAgreement)
        .where(CompAgreement.physician_id == physician_id)
        .where(CompAgreement.effective_from <= as_of)
        .where(
            (CompAgreement.effective_to.is_(None))
            | (CompAgreement.effective_to > as_of)
        )
        .order_by(CompAgreement.effective_from.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    agreement = result.scalar_one_or_none()
    if agreement is None:
        return None
    return annualize_comp_agreement(agreement)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_int(v: Decimal | float | int | None) -> int:
    # SQLAlchemy Numeric columns return Decimal at runtime even when the
    # mapped annotation is `float`. Accept both, plus None for nullable cols.
    if v is None:
        return 0
    return int(v)


def _to_decimal(v: Decimal | float | int | None) -> Decimal:
    if v is None:
        return Decimal(0)
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))
