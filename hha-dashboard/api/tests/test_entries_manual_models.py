"""Metadata-level tests for the three manual-entry models (finance / clinical
/ HR). Mirrors the pattern in ``test_entries_ventra_model.py``: pin
CheckConstraint names + UniqueConstraint shape + ADR-001 ``data_class``
classification at unit speed, before a migration lands in CI's Postgres.

The triple covered here is:
- ``MonthlyFinanceManual`` (entries.monthly_finance_manual)
- ``WeeklyClinical`` (entries.weekly_clinical)
- ``WeeklyHrManual`` (entries.weekly_hr_manual)

These are the owner-form tables (Sandy, Dr. Aneja, Andrea respectively).
They're audited by the Postgres trigger, so the AUDITED_TABLES test in
``test_audit_service.py`` and the trigger-attachment test in
``test_audit_triggers.py`` already covers the audit chain; this file
covers the CHECK invariants the form layer relies on for fail-closed
validation if the API ever skips its own Pydantic guard.
"""

from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models.entries_clinical import WeeklyClinical
from app.models.entries_finance import MonthlyFinanceManual
from app.models.entries_hr import WeeklyHrManual


def _check_names(model: type) -> set[str]:
    """Return the fully-rendered names of every CheckConstraint on the model.

    Note: SQLAlchemy's metadata naming_convention (see app/models/base.py)
    prefixes every named CHECK with ``ck_<table_name>_``. Callers test
    against the suffix via ``any(n.endswith("...") for n in ...)``.
    """
    return {c.name for c in model.__table__.constraints if isinstance(c, CheckConstraint)}


def _unique_names(model: type) -> set[str]:
    """UniqueConstraints with explicit ``name=`` keep that literal name —
    the project's naming_convention only applies when no name was given."""
    return {c.name for c in model.__table__.constraints if isinstance(c, UniqueConstraint)}


def _has_check(model: type, suffix: str) -> bool:
    """True iff any CHECK on the table ends with the given local name."""
    return any(n is not None and n.endswith(suffix) for n in _check_names(model))


class TestMonthlyFinanceManual:
    def test_schema_is_entries(self) -> None:
        assert MonthlyFinanceManual.__table__.schema == "entries"

    def test_table_name_locked(self) -> None:
        assert MonthlyFinanceManual.__tablename__ == "monthly_finance_manual"

    def test_unique_constraint_pinned(self) -> None:
        # UniqueConstraint kept its literal name (no convention prefix).
        assert "one_finance_per_month_per_state" in _unique_names(MonthlyFinanceManual)

    def test_state_check_is_fl_or_tx(self) -> None:
        # Per ADR-005, no third state allowed in any manual finance row.
        assert any(
            "state IN ('FL', 'TX')" in str(c.sqltext)
            for c in MonthlyFinanceManual.__table__.constraints
            if isinstance(c, CheckConstraint)
            and c.name is not None
            and c.name.endswith("state_valid")
        )

    def test_source_system_check_excludes_unknown_tags(self) -> None:
        # Locks the three legal provenance tags. Adding a fourth requires a
        # migration + ADR amendment.
        found = next(
            (
                c
                for c in MonthlyFinanceManual.__table__.constraints
                if isinstance(c, CheckConstraint)
                and c.name is not None
                and c.name.endswith("source_system_valid")
            ),
            None,
        )
        assert found is not None
        sql = str(found.sqltext)
        assert "VENTRA_FL_ATHENA" in sql
        assert "VENTRA_FL_FALLBACK" in sql
        assert "HHA_TX_MANUAL" in sql

    def test_month_year_range_checks(self) -> None:
        assert _has_check(MonthlyFinanceManual, "month_valid")
        assert _has_check(MonthlyFinanceManual, "year_valid")

    def test_non_negative_dollar_checks(self) -> None:
        assert _has_check(MonthlyFinanceManual, "collections_non_negative")
        assert _has_check(MonthlyFinanceManual, "ar_total_non_negative")

    def test_ncr_in_range_check(self) -> None:
        assert _has_check(MonthlyFinanceManual, "ncr_in_range")

    @pytest.mark.parametrize(
        "col",
        [
            "id",
            "year",
            "month",
            "period_first",
            "state",
            "collections_usd",
            "ar_total_usd",
            "ar_0_30_usd",
            "source_system",
            "notes",
        ],
    )
    def test_every_aggregate_column_is_data_class_a(self, col: str) -> None:
        c = MonthlyFinanceManual.__table__.columns[col]
        assert c.info.get("data_class") == "A", (
            f"Column {col} must be Tier A (aggregate) per ADR-001."
        )

    def test_entered_by_upn_is_tier_b_directory(self) -> None:
        # UPN is directory data (Tier B), not aggregate (Tier A).
        c = MonthlyFinanceManual.__table__.columns["entered_by_upn"]
        assert c.info.get("data_class") == "B"

    def test_no_forbidden_phi_columns_present(self) -> None:
        cols = set(MonthlyFinanceManual.__table__.columns.keys())
        for forbidden in (
            "patient_id",
            "patient_name",
            "patient_dob",
            "mrn",
            "claim_id",
            "encounter_id",
            "dos_per_line",
            "cpt_per_line",
            "member_id",
            "subscriber_id",
            "guarantor_id",
        ):
            assert forbidden not in cols, (
                f"ADR-001 violation: forbidden column '{forbidden}' on "
                f"{MonthlyFinanceManual.__tablename__}"
            )


class TestWeeklyClinical:
    def test_schema_is_entries(self) -> None:
        assert WeeklyClinical.__table__.schema == "entries"

    def test_unique_constraint_per_week_per_state(self) -> None:
        assert "one_clinical_per_week_per_state" in _unique_names(WeeklyClinical)

    def test_state_check_pinned(self) -> None:
        assert _has_check(WeeklyClinical, "state_valid")

    def test_percent_columns_clamped_to_0_100(self) -> None:
        assert _has_check(WeeklyClinical, "hp_24h_pct_in_range")
        assert _has_check(WeeklyClinical, "dc_48h_pct_in_range")

    def test_los_has_non_negative_and_sanity_cap(self) -> None:
        assert _has_check(WeeklyClinical, "avg_los_non_negative")
        assert _has_check(WeeklyClinical, "avg_los_sanity_cap")  # ≤ 60 days

    def test_charts_audited_non_negative(self) -> None:
        assert _has_check(WeeklyClinical, "charts_audited_non_negative")

    @pytest.mark.parametrize(
        "col",
        [
            "id",
            "week_ending",
            "state",
            "hp_24h_pct",
            "dc_48h_pct",
            "avg_los_days",
            "charts_audited_count",
            "notes",
        ],
    )
    def test_every_aggregate_column_is_data_class_a(self, col: str) -> None:
        c = WeeklyClinical.__table__.columns[col]
        assert c.info.get("data_class") == "A"

    def test_entered_by_upn_is_tier_b(self) -> None:
        c = WeeklyClinical.__table__.columns["entered_by_upn"]
        assert c.info.get("data_class") == "B"

    def test_no_chart_level_columns_present(self) -> None:
        # Clinical is a HIGH-RISK schema for PHI leakage if someone tries to
        # add chart-level columns. Pin the denylist.
        cols = set(WeeklyClinical.__table__.columns.keys())
        for forbidden in (
            "chart_id",
            "patient_id",
            "patient_name",
            "mrn",
            "encounter_id",
            "admit_diagnosis",
        ):
            assert forbidden not in cols, (
                f"ADR-001 violation on weekly_clinical: '{forbidden}'"
            )


class TestWeeklyHrManual:
    def test_schema_is_entries(self) -> None:
        assert WeeklyHrManual.__table__.schema == "entries"

    def test_unique_constraint_one_per_week(self) -> None:
        # No state split — HR is HHA-wide per the model docstring.
        assert "one_hr_per_week" in _unique_names(WeeklyHrManual)

    def test_no_state_check_constraint(self) -> None:
        # State split is intentionally absent on HR — verify.
        assert not _has_check(WeeklyHrManual, "state_valid")

    def test_every_count_has_non_negative_check(self) -> None:
        assert _has_check(WeeklyHrManual, "headcount_w2_non_negative")
        assert _has_check(WeeklyHrManual, "headcount_1099_non_negative")
        assert _has_check(WeeklyHrManual, "open_positions_non_negative")
        assert _has_check(WeeklyHrManual, "terminations_non_negative")
        assert _has_check(WeeklyHrManual, "below_fmv_non_negative")

    @pytest.mark.parametrize(
        "col",
        [
            "id",
            "week_ending",
            "headcount_w2",
            "headcount_1099",
            "open_positions_total",
            "terminations_90d_count",
            "below_fmv_count",
            "notes",
        ],
    )
    def test_every_aggregate_column_is_data_class_a(self, col: str) -> None:
        c = WeeklyHrManual.__table__.columns[col]
        assert c.info.get("data_class") == "A"

    def test_entered_by_upn_is_tier_b(self) -> None:
        c = WeeklyHrManual.__table__.columns["entered_by_upn"]
        assert c.info.get("data_class") == "B"

    def test_no_employee_pii_columns_present(self) -> None:
        # Salary-by-name etc. would be Tier C; the model must never carry them.
        cols = set(WeeklyHrManual.__table__.columns.keys())
        for forbidden in (
            "employee_id",
            "employee_name",
            "ssn",
            "dob",
            "salary",
            "compensation",
        ):
            assert forbidden not in cols, (
                f"ADR-001 violation on weekly_hr_manual: '{forbidden}'"
            )
