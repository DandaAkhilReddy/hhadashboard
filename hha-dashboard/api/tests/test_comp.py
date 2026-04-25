"""Unit tests for services.comp — MGMA band math + comp annualization."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from app.models.masters import CompAgreement
from app.services.comp import (
    MGMA_IM_HOSPITALIST_TOTAL_COMP_USD,
    annualize_comp_agreement,
    compute_mgma_band,
    is_below_fmv,
    mgma_benchmark_50th_usd,
)


# ---- Band classification ----


def test_band_below_25th_for_under_p25() -> None:
    p25 = MGMA_IM_HOSPITALIST_TOTAL_COMP_USD[25]
    assert compute_mgma_band(p25 - 1) == "below_25"


def test_band_25_50_at_p25_boundary() -> None:
    p25 = MGMA_IM_HOSPITALIST_TOTAL_COMP_USD[25]
    # Boundaries: p25 itself goes into the 25-50 band (>= p25, < p50)
    assert compute_mgma_band(p25) == "25_50"


def test_band_50_75_at_p50_boundary() -> None:
    p50 = MGMA_IM_HOSPITALIST_TOTAL_COMP_USD[50]
    assert compute_mgma_band(p50) == "50_75"


def test_band_75_90_at_p75_boundary() -> None:
    p75 = MGMA_IM_HOSPITALIST_TOTAL_COMP_USD[75]
    assert compute_mgma_band(p75) == "75_90"


def test_band_above_90_at_p90() -> None:
    p90 = MGMA_IM_HOSPITALIST_TOTAL_COMP_USD[90]
    assert compute_mgma_band(p90) == "above_90"
    assert compute_mgma_band(p90 + 100_000) == "above_90"


def test_band_zero_is_below_25() -> None:
    assert compute_mgma_band(0) == "below_25"


# ---- Below-FMV ----


def test_is_below_fmv_true_under_p25() -> None:
    p25 = MGMA_IM_HOSPITALIST_TOTAL_COMP_USD[25]
    assert is_below_fmv(p25 - 1) is True


def test_is_below_fmv_false_at_p25() -> None:
    p25 = MGMA_IM_HOSPITALIST_TOTAL_COMP_USD[25]
    assert is_below_fmv(p25) is False


def test_is_below_fmv_false_well_above() -> None:
    assert is_below_fmv(500_000) is False


# ---- Public benchmark accessor ----


def test_mgma_p50_matches_constant() -> None:
    assert mgma_benchmark_50th_usd() == MGMA_IM_HOSPITALIST_TOTAL_COMP_USD[50]


# ---- annualize_comp_agreement ----


def _agreement(**fields: object) -> CompAgreement:
    """Build a CompAgreement-shaped object without hitting the DB.

    We can't construct CompAgreement directly without a session in some
    SQLAlchemy configs; MagicMock matches the duck-typed access pattern.
    """
    defaults = {
        "physician_id": 1,
        "effective_from": date(2024, 1, 1),
        "effective_to": None,
        "employment_type": "W2",
        "base_salary_usd": None,
        "per_diem_rate_usd": None,
        "rvu_rate_usd": None,
        "rvu_threshold_annual": None,
        "call_stipend_usd": None,
        "fmv_benchmark_usd": Decimal("320000"),
    }
    defaults.update(fields)
    mock = MagicMock(spec=CompAgreement)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def test_annualize_pure_salary() -> None:
    agreement = _agreement(base_salary_usd=Decimal("310000"))
    assert annualize_comp_agreement(agreement) == 310_000


def test_annualize_salary_plus_rvu() -> None:
    agreement = _agreement(
        base_salary_usd=Decimal("250000"),
        rvu_rate_usd=Decimal("55"),
        rvu_threshold_annual=Decimal("4500"),
    )
    # 250_000 + 55 * 4500 = 497_500
    assert annualize_comp_agreement(agreement) == 497_500


def test_annualize_salary_plus_stipend() -> None:
    agreement = _agreement(
        base_salary_usd=Decimal("280000"),
        call_stipend_usd=Decimal("20000"),
    )
    assert annualize_comp_agreement(agreement) == 300_000


def test_annualize_per_diem_only_returns_zero() -> None:
    # Per-diem agreements have no base/RVU/stipend at the agreement level.
    agreement = _agreement(per_diem_rate_usd=Decimal("1800"))
    assert annualize_comp_agreement(agreement) == 0


def test_annualize_handles_floats_and_ints() -> None:
    # SQLAlchemy Numeric columns are typed as float in mappings; runtime
    # is Decimal. Helper must accept both.
    agreement = _agreement(
        base_salary_usd=300_000.0,
        rvu_rate_usd=50,
        rvu_threshold_annual=200,
    )
    assert annualize_comp_agreement(agreement) == 310_000
