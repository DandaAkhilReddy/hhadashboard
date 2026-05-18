"""Unit tests for the owner-form Pydantic schemas:
- entries.daily_entries (Crystal)
- entries.monthly_finance_manual (Sandy)
- entries.weekly_clinical (Dr. Aneja / Dr. Reddy)
- entries.weekly_hr_manual (Andrea)
- auth.census_credentials portal payloads

These schemas are exercised indirectly via router tests, which means
ValidationError edge cases (missing required, out-of-range, regex /
``model_validator`` cross-field rules) are largely uncovered. This file
pins every constraint at pure-Python speed — no DB, no FastAPI, just
``BaseModel.__init__`` paths.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.census_portal import (
    LoginIn,
    PortalCensusBatchIn,
    PortalCensusRow,
)
from app.schemas.entries import (
    CENSUS_MAX,
    OPEN_SHIFTS_MAX,
    DailyCensusBatchIn,
    DailyEntryIn,
)
from app.schemas.monthly_finance import (
    AR_MAX,
    COLLECTIONS_MAX,
    MonthlyFinanceBatchIn,
    MonthlyFinanceRowIn,
    SourceSystem,
    StateCode,
)
from app.schemas.weekly_clinical import (
    LOS_MAX,
    WeeklyClinicalBatchIn,
    WeeklyClinicalRowIn,
)
from app.schemas.weekly_hr import WeeklyHrIn


def _last_sunday(today: date | None = None) -> date:
    """Return the most-recent Sunday on or before `today`. Used as a
    week_ending anchor that always passes the weekday-==-6 validator."""
    d = today or date.today()
    return d - timedelta(days=(d.weekday() + 1) % 7)


# ============================================================================
# entries.daily_entries — DailyEntryIn + DailyCensusBatchIn
# ============================================================================


class TestDailyEntryIn:
    def test_minimum_valid_row(self) -> None:
        row = DailyEntryIn(site_id=1, census=0)
        assert row.site_id == 1
        assert row.census == 0
        assert row.open_shifts == 0
        assert row.notes is None

    def test_rejects_zero_site_id(self) -> None:
        with pytest.raises(ValidationError, match="site_id"):
            DailyEntryIn(site_id=0, census=100)

    def test_rejects_negative_site_id(self) -> None:
        with pytest.raises(ValidationError, match="site_id"):
            DailyEntryIn(site_id=-1, census=100)

    def test_rejects_negative_census(self) -> None:
        with pytest.raises(ValidationError, match="census"):
            DailyEntryIn(site_id=1, census=-1)

    def test_accepts_census_max(self) -> None:
        row = DailyEntryIn(site_id=1, census=CENSUS_MAX)
        assert row.census == CENSUS_MAX

    def test_rejects_census_above_max(self) -> None:
        with pytest.raises(ValidationError, match="census"):
            DailyEntryIn(site_id=1, census=CENSUS_MAX + 1)

    def test_open_shifts_default_is_zero(self) -> None:
        row = DailyEntryIn(site_id=1, census=100)
        assert row.open_shifts == 0

    def test_rejects_open_shifts_above_max(self) -> None:
        with pytest.raises(ValidationError, match="open_shifts"):
            DailyEntryIn(site_id=1, census=100, open_shifts=OPEN_SHIFTS_MAX + 1)

    def test_rejects_negative_open_shifts(self) -> None:
        with pytest.raises(ValidationError, match="open_shifts"):
            DailyEntryIn(site_id=1, census=100, open_shifts=-1)

    def test_notes_max_length_enforced(self) -> None:
        # 500-char string allowed; 501 rejected.
        DailyEntryIn(site_id=1, census=100, notes="x" * 500)
        with pytest.raises(ValidationError, match="notes"):
            DailyEntryIn(site_id=1, census=100, notes="x" * 501)

    def test_missing_required_site_id_raises(self) -> None:
        with pytest.raises(ValidationError, match="site_id"):
            DailyEntryIn(census=100)  # type: ignore[call-arg]

    def test_missing_required_census_raises(self) -> None:
        with pytest.raises(ValidationError, match="census"):
            DailyEntryIn(site_id=1)  # type: ignore[call-arg]


class TestDailyCensusBatchIn:
    def test_minimum_valid_batch(self) -> None:
        batch = DailyCensusBatchIn(
            entry_date=date.today(),
            rows=[DailyEntryIn(site_id=1, census=100)],
        )
        assert len(batch.rows) == 1

    def test_rejects_future_date(self) -> None:
        with pytest.raises(ValidationError, match="future"):
            DailyCensusBatchIn(
                entry_date=date.today() + timedelta(days=1),
                rows=[DailyEntryIn(site_id=1, census=100)],
            )

    def test_accepts_today_as_entry_date(self) -> None:
        # The validator uses ``> date.today()``, so today is fine.
        DailyCensusBatchIn(
            entry_date=date.today(),
            rows=[DailyEntryIn(site_id=1, census=100)],
        )

    def test_rejects_empty_rows_list(self) -> None:
        with pytest.raises(ValidationError, match="rows"):
            DailyCensusBatchIn(entry_date=date.today(), rows=[])

    def test_rejects_more_than_50_rows(self) -> None:
        with pytest.raises(ValidationError, match="rows"):
            DailyCensusBatchIn(
                entry_date=date.today(),
                rows=[DailyEntryIn(site_id=i + 1, census=100) for i in range(51)],
            )


# ============================================================================
# entries.monthly_finance_manual — MonthlyFinanceRowIn + BatchIn
# ============================================================================


def _good_row(state: StateCode = StateCode.FL) -> MonthlyFinanceRowIn:
    return MonthlyFinanceRowIn(
        state=state,
        collections_usd=Decimal("100000"),
        ar_total_usd=Decimal("50000"),
        net_collection_rate_pct=Decimal("95.5"),
        days_in_ar=Decimal("42"),
    )


class TestStateCodeEnum:
    def test_only_fl_and_tx(self) -> None:
        assert {m.value for m in StateCode} == {"FL", "TX"}


class TestSourceSystemEnum:
    def test_three_legal_provenance_tags(self) -> None:
        assert {m.value for m in SourceSystem} == {
            "VENTRA_FL_ATHENA",
            "VENTRA_FL_FALLBACK",
            "HHA_TX_MANUAL",
        }


class TestMonthlyFinanceRowIn:
    def test_accepts_minimum_required_fields(self) -> None:
        row = _good_row()
        assert row.state == StateCode.FL
        # Defaults — every AR bucket starts at 0
        assert row.ar_0_30_usd == Decimal(0)
        assert row.ventra_fee_usd == Decimal(0)
        assert row.notes is None

    def test_rejects_invalid_state(self) -> None:
        with pytest.raises(ValidationError, match="state"):
            MonthlyFinanceRowIn(
                state="WA",  # type: ignore[arg-type]
                collections_usd=Decimal("100000"),
                ar_total_usd=Decimal("50000"),
                net_collection_rate_pct=Decimal("95"),
                days_in_ar=Decimal("42"),
            )

    def test_rejects_negative_collections(self) -> None:
        with pytest.raises(ValidationError, match="collections_usd"):
            MonthlyFinanceRowIn(
                state=StateCode.FL,
                collections_usd=Decimal("-1"),
                ar_total_usd=Decimal("50000"),
                net_collection_rate_pct=Decimal("95"),
                days_in_ar=Decimal("42"),
            )

    def test_rejects_collections_above_cap(self) -> None:
        with pytest.raises(ValidationError, match="collections_usd"):
            MonthlyFinanceRowIn(
                state=StateCode.FL,
                collections_usd=COLLECTIONS_MAX + Decimal(1),
                ar_total_usd=Decimal("50000"),
                net_collection_rate_pct=Decimal("95"),
                days_in_ar=Decimal("42"),
            )

    def test_rejects_ar_total_above_cap(self) -> None:
        with pytest.raises(ValidationError, match="ar_total_usd"):
            MonthlyFinanceRowIn(
                state=StateCode.FL,
                collections_usd=Decimal("100000"),
                ar_total_usd=AR_MAX + Decimal(1),
                net_collection_rate_pct=Decimal("95"),
                days_in_ar=Decimal("42"),
            )

    @pytest.mark.parametrize("pct", [Decimal("-0.01"), Decimal("100.01"), Decimal("200")])
    def test_rejects_ncr_outside_0_to_100(self, pct: Decimal) -> None:
        with pytest.raises(ValidationError, match="net_collection_rate_pct"):
            MonthlyFinanceRowIn(
                state=StateCode.FL,
                collections_usd=Decimal("100000"),
                ar_total_usd=Decimal("50000"),
                net_collection_rate_pct=pct,
                days_in_ar=Decimal("42"),
            )

    @pytest.mark.parametrize("ncr", [Decimal(0), Decimal("100"), Decimal("95.5")])
    def test_accepts_ncr_in_range(self, ncr: Decimal) -> None:
        row = MonthlyFinanceRowIn(
            state=StateCode.FL,
            collections_usd=Decimal("100000"),
            ar_total_usd=Decimal("50000"),
            net_collection_rate_pct=ncr,
            days_in_ar=Decimal("42"),
        )
        assert row.net_collection_rate_pct == ncr

    def test_rejects_days_in_ar_above_365(self) -> None:
        with pytest.raises(ValidationError, match="days_in_ar"):
            MonthlyFinanceRowIn(
                state=StateCode.FL,
                collections_usd=Decimal("100000"),
                ar_total_usd=Decimal("50000"),
                net_collection_rate_pct=Decimal("95"),
                days_in_ar=Decimal("366"),
            )

    def test_notes_max_length(self) -> None:
        MonthlyFinanceRowIn(
            state=StateCode.FL,
            collections_usd=Decimal("100000"),
            ar_total_usd=Decimal("50000"),
            net_collection_rate_pct=Decimal("95"),
            days_in_ar=Decimal("42"),
            notes="x" * 500,
        )
        with pytest.raises(ValidationError, match="notes"):
            MonthlyFinanceRowIn(
                state=StateCode.FL,
                collections_usd=Decimal("100000"),
                ar_total_usd=Decimal("50000"),
                net_collection_rate_pct=Decimal("95"),
                days_in_ar=Decimal("42"),
                notes="x" * 501,
            )


class TestMonthlyFinanceBatchIn:
    def test_accepts_one_state_batch(self) -> None:
        batch = MonthlyFinanceBatchIn(
            year=date.today().year - 1,
            month=1,
            rows=[_good_row()],
        )
        assert len(batch.rows) == 1

    def test_accepts_both_states_batch(self) -> None:
        batch = MonthlyFinanceBatchIn(
            year=date.today().year - 1,
            month=1,
            rows=[_good_row(StateCode.FL), _good_row(StateCode.TX)],
        )
        assert len(batch.rows) == 2

    def test_rejects_duplicate_state_in_batch(self) -> None:
        with pytest.raises(ValidationError, match="Duplicate state"):
            MonthlyFinanceBatchIn(
                year=date.today().year - 1,
                month=1,
                rows=[_good_row(StateCode.FL), _good_row(StateCode.FL)],
            )

    def test_rejects_future_month(self) -> None:
        future_year = date.today().year + 5
        with pytest.raises(ValidationError, match="future"):
            MonthlyFinanceBatchIn(year=future_year, month=1, rows=[_good_row()])

    def test_rejects_year_before_2020(self) -> None:
        with pytest.raises(ValidationError, match="year"):
            MonthlyFinanceBatchIn(year=2019, month=1, rows=[_good_row()])

    def test_rejects_month_zero_or_thirteen(self) -> None:
        with pytest.raises(ValidationError, match="month"):
            MonthlyFinanceBatchIn(year=2025, month=0, rows=[_good_row()])
        with pytest.raises(ValidationError, match="month"):
            MonthlyFinanceBatchIn(year=2025, month=13, rows=[_good_row()])

    def test_rejects_more_than_two_rows(self) -> None:
        with pytest.raises(ValidationError, match="rows"):
            MonthlyFinanceBatchIn(
                year=2025,
                month=1,
                rows=[
                    _good_row(StateCode.FL),
                    _good_row(StateCode.TX),
                    _good_row(StateCode.FL),
                ],
            )


# ============================================================================
# entries.weekly_clinical — WeeklyClinicalRowIn + BatchIn
# ============================================================================


def _good_clinical_row(state: str = "FL") -> WeeklyClinicalRowIn:
    return WeeklyClinicalRowIn(
        state=state,  # type: ignore[arg-type]
        hp_24h_pct=Decimal("95"),
        dc_48h_pct=Decimal("90"),
        avg_los_days=Decimal("4.5"),
    )


class TestWeeklyClinicalRowIn:
    def test_accepts_minimum_required(self) -> None:
        row = _good_clinical_row()
        assert row.charts_audited_count == 0  # default
        assert row.notes is None

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("hp_24h_pct", Decimal("-0.01")),
            ("hp_24h_pct", Decimal("100.01")),
            ("dc_48h_pct", Decimal("-1")),
            ("dc_48h_pct", Decimal("101")),
        ],
    )
    def test_rejects_pct_outside_range(self, field: str, value: Decimal) -> None:
        kwargs = {
            "state": "FL",
            "hp_24h_pct": Decimal("95"),
            "dc_48h_pct": Decimal("90"),
            "avg_los_days": Decimal("4"),
        }
        kwargs[field] = value
        with pytest.raises(ValidationError, match=field):
            WeeklyClinicalRowIn(**kwargs)  # type: ignore[arg-type]

    def test_rejects_los_above_sanity_cap(self) -> None:
        with pytest.raises(ValidationError, match="avg_los_days"):
            WeeklyClinicalRowIn(
                state="FL",  # type: ignore[arg-type]
                hp_24h_pct=Decimal("95"),
                dc_48h_pct=Decimal("90"),
                avg_los_days=LOS_MAX + Decimal(1),
            )

    def test_rejects_negative_charts_count(self) -> None:
        with pytest.raises(ValidationError, match="charts_audited_count"):
            WeeklyClinicalRowIn(
                state="FL",  # type: ignore[arg-type]
                hp_24h_pct=Decimal("95"),
                dc_48h_pct=Decimal("90"),
                avg_los_days=Decimal("4"),
                charts_audited_count=-1,
            )

    def test_notes_max_length_1000(self) -> None:
        WeeklyClinicalRowIn(
            state="FL",  # type: ignore[arg-type]
            hp_24h_pct=Decimal("95"),
            dc_48h_pct=Decimal("90"),
            avg_los_days=Decimal("4"),
            notes="x" * 1000,
        )
        with pytest.raises(ValidationError, match="notes"):
            WeeklyClinicalRowIn(
                state="FL",  # type: ignore[arg-type]
                hp_24h_pct=Decimal("95"),
                dc_48h_pct=Decimal("90"),
                avg_los_days=Decimal("4"),
                notes="x" * 1001,
            )


class TestWeeklyClinicalBatchIn:
    def test_accepts_sunday_week_ending(self) -> None:
        sunday = _last_sunday()
        batch = WeeklyClinicalBatchIn(week_ending=sunday, rows=[_good_clinical_row()])
        assert batch.week_ending == sunday

    def test_rejects_non_sunday_week_ending(self) -> None:
        sunday = _last_sunday()
        not_sunday = sunday + timedelta(days=1)  # Monday
        with pytest.raises(ValidationError, match="Sunday"):
            WeeklyClinicalBatchIn(week_ending=not_sunday, rows=[_good_clinical_row()])

    def test_rejects_week_ending_too_far_in_future(self) -> None:
        far_future_sunday = _last_sunday() + timedelta(days=14)
        with pytest.raises(ValidationError, match="future"):
            WeeklyClinicalBatchIn(
                week_ending=far_future_sunday, rows=[_good_clinical_row()]
            )

    def test_rejects_duplicate_state(self) -> None:
        with pytest.raises(ValidationError, match="Duplicate state"):
            WeeklyClinicalBatchIn(
                week_ending=_last_sunday(),
                rows=[_good_clinical_row("FL"), _good_clinical_row("FL")],
            )

    def test_accepts_both_states(self) -> None:
        batch = WeeklyClinicalBatchIn(
            week_ending=_last_sunday(),
            rows=[_good_clinical_row("FL"), _good_clinical_row("TX")],
        )
        assert len(batch.rows) == 2


# ============================================================================
# entries.weekly_hr_manual — WeeklyHrIn
# ============================================================================


class TestWeeklyHrIn:
    def test_accepts_minimum_required(self) -> None:
        row = WeeklyHrIn(
            week_ending=_last_sunday(), headcount_w2=100, headcount_1099=20
        )
        # Defaults
        assert row.open_positions_total == 0
        assert row.terminations_90d_count == 0
        assert row.below_fmv_count == 0
        assert row.notes is None

    def test_rejects_non_sunday_week_ending(self) -> None:
        with pytest.raises(ValidationError, match="Sunday"):
            WeeklyHrIn(
                week_ending=_last_sunday() + timedelta(days=2),  # Tuesday
                headcount_w2=100,
                headcount_1099=20,
            )

    def test_rejects_week_ending_far_in_future(self) -> None:
        with pytest.raises(ValidationError, match="future"):
            WeeklyHrIn(
                week_ending=_last_sunday() + timedelta(days=14),
                headcount_w2=100,
                headcount_1099=20,
            )

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("headcount_w2", -1),
            ("headcount_w2", 10001),
            ("headcount_1099", -1),
            ("headcount_1099", 10001),
            ("open_positions_total", 1001),
            ("terminations_90d_count", 1001),
            ("below_fmv_count", 10001),
        ],
    )
    def test_rejects_out_of_range_counts(self, field: str, value: int) -> None:
        kwargs = {"week_ending": _last_sunday(), "headcount_w2": 100, "headcount_1099": 20}
        kwargs[field] = value
        with pytest.raises(ValidationError, match=field):
            WeeklyHrIn(**kwargs)  # type: ignore[arg-type]

    def test_accepts_zero_counts(self) -> None:
        row = WeeklyHrIn(week_ending=_last_sunday(), headcount_w2=0, headcount_1099=0)
        assert row.headcount_w2 == 0

    def test_notes_max_length_1000(self) -> None:
        WeeklyHrIn(
            week_ending=_last_sunday(),
            headcount_w2=100,
            headcount_1099=20,
            notes="x" * 1000,
        )
        with pytest.raises(ValidationError, match="notes"):
            WeeklyHrIn(
                week_ending=_last_sunday(),
                headcount_w2=100,
                headcount_1099=20,
                notes="x" * 1001,
            )


# ============================================================================
# auth.census_credentials — portal payloads
# ============================================================================


class TestLoginIn:
    def test_accepts_typical_credentials(self) -> None:
        login = LoginIn(email="portal@hha.com", password="hunter2")
        assert login.email == "portal@hha.com"

    def test_rejects_empty_password(self) -> None:
        with pytest.raises(ValidationError, match="password"):
            LoginIn(email="portal@hha.com", password="")

    def test_rejects_too_short_email(self) -> None:
        with pytest.raises(ValidationError, match="email"):
            LoginIn(email="ab", password="hunter2")

    def test_rejects_oversized_email(self) -> None:
        with pytest.raises(ValidationError, match="email"):
            LoginIn(email="x" * 201, password="hunter2")

    def test_rejects_oversized_password(self) -> None:
        with pytest.raises(ValidationError, match="password"):
            LoginIn(email="portal@hha.com", password="x" * 201)


class TestPortalCensusRow:
    def test_accepts_minimum_valid(self) -> None:
        row = PortalCensusRow(site_id=1, census=0)
        assert row.census == 0

    def test_rejects_negative_census(self) -> None:
        with pytest.raises(ValidationError, match="census"):
            PortalCensusRow(site_id=1, census=-1)

    def test_rejects_census_above_2000(self) -> None:
        with pytest.raises(ValidationError, match="census"):
            PortalCensusRow(site_id=1, census=2001)

    def test_accepts_census_at_2000_boundary(self) -> None:
        row = PortalCensusRow(site_id=1, census=2000)
        assert row.census == 2000


class TestPortalCensusBatchIn:
    def test_accepts_today_entry_date(self) -> None:
        batch = PortalCensusBatchIn(
            entry_date=date.today(),
            rows=[PortalCensusRow(site_id=1, census=100)],
        )
        assert batch.entry_date == date.today()

    def test_rejects_future_entry_date(self) -> None:
        with pytest.raises(ValidationError, match="future"):
            PortalCensusBatchIn(
                entry_date=date.today() + timedelta(days=1),
                rows=[PortalCensusRow(site_id=1, census=100)],
            )

    def test_rejects_empty_rows(self) -> None:
        with pytest.raises(ValidationError, match="rows"):
            PortalCensusBatchIn(entry_date=date.today(), rows=[])

    def test_rejects_more_than_50_rows(self) -> None:
        with pytest.raises(ValidationError, match="rows"):
            PortalCensusBatchIn(
                entry_date=date.today(),
                rows=[PortalCensusRow(site_id=i + 1, census=10) for i in range(51)],
            )
