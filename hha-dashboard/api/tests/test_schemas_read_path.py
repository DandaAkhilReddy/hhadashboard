"""Unit tests for read-path response schemas:
- operations (SiteToday, OperationsSummary, DailyEntryHistoryRow, SiteDetail)
- clinical (ClinicalSummary, CredentialExpiring)
- finance (FinanceToday, ArBuckets, ArAging, FinanceKpis, MonthRevenue)
- people (PeopleSummary, OpenPositionBySite)
- scorecards (ScorecardOut + MgmaBand Literal)
- sites (SiteOut + from_attributes=True hydration)
- alerts (Alert, Meta)

Read-path schemas are pure response models — no validators. Coverage
target is required-field rejection, type coercion, nested-model
composition, and round-trip via ``.model_dump()``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.schemas.alerts import Alert, Meta
from app.schemas.clinical import ClinicalSummary, CredentialExpiring
from app.schemas.finance import (
    ArAging,
    ArBuckets,
    FinanceKpis,
    FinanceToday,
    MonthRevenue,
)
from app.schemas.operations import (
    DailyEntryHistoryRow,
    OperationsSummary,
    SiteDetail,
    SiteToday,
)
from app.schemas.people import OpenPositionBySite, PeopleSummary
from app.schemas.scorecards import ScorecardOut
from app.schemas.sites import SiteOut

# ============================================================================
# operations.py
# ============================================================================


def _site_today_payload(**overrides) -> dict:
    base = {
        "id": 1,
        "name": "Westside Regional",
        "state": "FL",
        "medical_director": None,
        "md_status": None,
        "liaison": None,
        "census_today": None,
        "census_3mo_avg": None,
        "mtd_avg": None,
        "variance_pct": None,
        "open_shifts": None,
        "contract_end": None,
        "annual_subsidy_usd": 1_000_000,
    }
    return {**base, **overrides}


class TestSiteToday:
    def test_accepts_phase1_minimum_with_nulls(self) -> None:
        row = SiteToday(**_site_today_payload())
        assert row.id == 1
        assert row.census_today is None

    def test_accepts_fully_populated(self) -> None:
        row = SiteToday(
            **_site_today_payload(
                medical_director="Dr. Alice",
                md_status="ACTIVE",
                liaison="Mary",
                census_today=198,
                census_3mo_avg=200,
                mtd_avg=195.4,
                variance_pct=-2.3,
                open_shifts=2,
                contract_end="2027-12-31",
            )
        )
        assert row.census_today == 198
        assert row.variance_pct == pytest.approx(-2.3)

    def test_missing_required_id_raises(self) -> None:
        payload = _site_today_payload()
        del payload["id"]
        with pytest.raises(ValidationError, match="id"):
            SiteToday(**payload)

    def test_missing_required_annual_subsidy_raises(self) -> None:
        payload = _site_today_payload()
        del payload["annual_subsidy_usd"]
        with pytest.raises(ValidationError, match="annual_subsidy_usd"):
            SiteToday(**payload)


class TestOperationsSummary:
    def test_full_construct(self) -> None:
        summary = OperationsSummary(
            total_fl_census=1200,
            total_tx_census=400,
            total_fl_3mo_avg=1300,
            census_variance_vs_avg=-100,
            sites_below_avg=3,
            open_shifts_total=8,
            fl_site_count=7,
            tx_site_count=4,
            facilities_reported=9,
            facilities_missing=2,
            last_updated_at=datetime(2026, 5, 17, 15, tzinfo=UTC),
        )
        assert summary.facilities_reported == 9

    def test_accepts_null_last_updated(self) -> None:
        OperationsSummary(
            total_fl_census=0,
            total_tx_census=0,
            total_fl_3mo_avg=0,
            census_variance_vs_avg=0,
            sites_below_avg=0,
            open_shifts_total=0,
            fl_site_count=0,
            tx_site_count=0,
            facilities_reported=0,
            facilities_missing=0,
            last_updated_at=None,
        )


class TestDailyEntryHistoryRow:
    def test_accepts_minimum(self) -> None:
        row = DailyEntryHistoryRow(
            entry_date=date(2026, 5, 17),
            census=198,
            open_shifts=2,
            entered_by_upn="crystal@hha.com",
            source="manual",
            notes=None,
            updated_at=None,
        )
        assert row.notes is None

    def test_rejects_missing_entered_by_upn(self) -> None:
        with pytest.raises(ValidationError, match="entered_by_upn"):
            DailyEntryHistoryRow(  # type: ignore[call-arg]
                entry_date=date(2026, 5, 17),
                census=198,
                open_shifts=2,
                source="manual",
                notes=None,
                updated_at=None,
            )


class TestSiteDetail:
    def test_extends_site_today_with_history_and_flag(self) -> None:
        detail = SiteDetail(
            **_site_today_payload(census_today=198),
            entered_today=True,
            recent_entries=[
                DailyEntryHistoryRow(
                    entry_date=date(2026, 5, 17),
                    census=198,
                    open_shifts=2,
                    entered_by_upn="crystal@hha.com",
                    source="manual",
                    notes=None,
                    updated_at=None,
                )
            ],
        )
        assert detail.entered_today is True
        assert len(detail.recent_entries) == 1
        assert detail.census_today == 198

    def test_empty_recent_entries_list_accepted(self) -> None:
        detail = SiteDetail(
            **_site_today_payload(),
            entered_today=False,
            recent_entries=[],
        )
        assert detail.recent_entries == []


# ============================================================================
# clinical.py
# ============================================================================


class TestClinicalSummary:
    def test_full_construct(self) -> None:
        s = ClinicalSummary(
            hp_24h_pct=95.5,
            hp_24h_target=95,
            dc_48h_pct=88.0,
            dc_48h_target=90,
            los_fl_days=4.2,
            los_tx_days=3.8,
            los_woodmont_watch_days=5.5,
            los_woodmont_trend_days=0.3,
            credentials_expiring_30d=2,
            credentials_expiring_60d=4,
            credentials_expiring_90d=8,
        )
        assert s.hp_24h_pct == pytest.approx(95.5)

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(ValidationError, match="hp_24h_pct"):
            ClinicalSummary(  # type: ignore[call-arg]
                hp_24h_target=95,
                dc_48h_pct=88,
                dc_48h_target=90,
                los_fl_days=4,
                los_tx_days=3,
                los_woodmont_watch_days=5,
                los_woodmont_trend_days=0.2,
                credentials_expiring_30d=1,
                credentials_expiring_60d=2,
                credentials_expiring_90d=3,
            )


class TestCredentialExpiring:
    def test_full_construct(self) -> None:
        c = CredentialExpiring(
            physician="Dr. Alice",
            type="STATE_LICENSE",
            expires_in_days=14,
            expires_on="2026-06-01",
            tier="urgent",
        )
        assert c.tier == "urgent"

    @pytest.mark.parametrize("tier", ["urgent", "warning", "info"])
    def test_accepts_documented_tier_values(self, tier: str) -> None:
        # The schema uses a free str (no Literal); document the contract.
        CredentialExpiring(
            physician="Dr. Alice",
            type="DEA",
            expires_in_days=30,
            expires_on="2026-07-01",
            tier=tier,
        )


# ============================================================================
# finance.py
# ============================================================================


class TestFinanceToday:
    def test_full_construct(self) -> None:
        ft = FinanceToday(
            fl_daily_actual=147_000,
            fl_daily_target=147_727,
            fl_daily_delta=-727,
            fl_source_system="VENTRA_FL_FALLBACK",
            tx_daily_actual=22_500,
            tx_daily_target=22_500,
            tx_daily_delta=0,
            tx_source_system="HHA_TX_MANUAL",
            fl_mtd_actual=3_000_000,
            fl_mtd_target=3_250_000,
            fl_mtd_pct=92.3,
            ventra_fee_mtd=150_000,
        )
        assert ft.fl_source_system == "VENTRA_FL_FALLBACK"


class TestArBuckets:
    def test_full_construct(self) -> None:
        b = ArBuckets(
            bucket_0_30=30_000,
            bucket_31_60=10_000,
            bucket_61_90=5_000,
            bucket_91_120=3_000,
            bucket_over_120=2_000,
        )
        assert b.bucket_0_30 == 30_000

    def test_missing_bucket_raises(self) -> None:
        with pytest.raises(ValidationError, match="bucket_over_120"):
            ArBuckets(  # type: ignore[call-arg]
                bucket_0_30=30_000,
                bucket_31_60=10_000,
                bucket_61_90=5_000,
                bucket_91_120=3_000,
            )


class TestArAging:
    def test_composes_two_arbuckets(self) -> None:
        ar = ArAging(
            fl_total_usd=50_000,
            fl_buckets=ArBuckets(
                bucket_0_30=30_000,
                bucket_31_60=10_000,
                bucket_61_90=5_000,
                bucket_91_120=3_000,
                bucket_over_120=2_000,
            ),
            fl_over_120_pct=4.0,
            fl_source_system="VENTRA_FL_FALLBACK",
            tx_total_usd=10_000,
            tx_buckets=ArBuckets(
                bucket_0_30=6_000,
                bucket_31_60=2_000,
                bucket_61_90=1_000,
                bucket_91_120=600,
                bucket_over_120=400,
            ),
            tx_over_120_pct=4.0,
            tx_source_system="HHA_TX_MANUAL",
        )
        assert ar.fl_buckets.bucket_0_30 == 30_000
        assert ar.tx_buckets.bucket_over_120 == 400


class TestFinanceKpis:
    def test_full_construct(self) -> None:
        k = FinanceKpis(
            fl_days_in_ar=45.5,
            tx_days_in_ar=42.0,
            days_in_ar_target=45,
            fl_ncr_pct=95,
            tx_ncr_pct=97,
            ncr_billed_at="2026-04-30",
        )
        assert k.days_in_ar_target == 45


class TestMonthRevenue:
    def test_full_construct(self) -> None:
        m = MonthRevenue(month="2026-04", revenue_usd=4_500_000)
        assert m.month == "2026-04"


# ============================================================================
# people.py
# ============================================================================


class TestPeopleSummary:
    def test_full_construct(self) -> None:
        p = PeopleSummary(
            headcount_w2=100,
            headcount_1099=20,
            headcount_total=120,
            open_positions_total=8,
            turnover_90d_pct=12.5,
            below_fmv_count=61,
        )
        assert p.headcount_total == 120

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(ValidationError, match="headcount_total"):
            PeopleSummary(  # type: ignore[call-arg]
                headcount_w2=100,
                headcount_1099=20,
                open_positions_total=8,
                turnover_90d_pct=12.5,
                below_fmv_count=61,
            )


class TestOpenPositionBySite:
    def test_full_construct(self) -> None:
        op = OpenPositionBySite(
            site="Westside Regional", state="FL", count=3, severity="high"
        )
        assert op.severity == "high"


# ============================================================================
# scorecards.py — ScorecardOut + MgmaBand Literal
# ============================================================================


def _scorecard_payload(**overrides) -> dict:
    base = {
        "physician_id": 1,
        "name": "Dr. Alice",
        "site": "Westside Regional",
        "state": "FL",
        "employment_type": "W2",
        "comp_model": "SALARY",
        "status": "ACTIVE",
        "rank": 1,
        "rvu_90d": 1200,
        "below_fmv": False,
        "mgma_band": "50_75",
        "mgma_p50_usd": 300_000,
    }
    return {**base, **overrides}


class TestScorecardOut:
    def test_accepts_required_with_optional_comp_redacted(self) -> None:
        sc = ScorecardOut(**_scorecard_payload())
        # Comp-detail defaults are None — comp_viewer-only.
        assert sc.effective_comp_usd is None
        assert sc.fmv_source_note is None
        # Phase 2 placeholders also default to None.
        assert sc.revenue_per_fte_usd is None
        assert sc.encounters_per_day is None
        assert sc.documentation_score_pct is None
        assert sc.chart_turnaround_days is None

    def test_accepts_comp_viewer_populated_fields(self) -> None:
        sc = ScorecardOut(
            **_scorecard_payload(
                effective_comp_usd=325_000,
                fmv_source_note="MGMA 2025 Internal Medicine — Hospitalist",
            )
        )
        assert sc.effective_comp_usd == 325_000

    @pytest.mark.parametrize(
        "band", ["below_25", "25_50", "50_75", "75_90", "above_90"]
    )
    def test_accepts_every_mgma_band(self, band: str) -> None:
        sc = ScorecardOut(**_scorecard_payload(mgma_band=band))
        assert sc.mgma_band == band

    def test_rejects_invalid_mgma_band(self) -> None:
        with pytest.raises(ValidationError, match="mgma_band"):
            ScorecardOut(**_scorecard_payload(mgma_band="invalid"))

    def test_missing_required_physician_id_raises(self) -> None:
        payload = _scorecard_payload()
        del payload["physician_id"]
        with pytest.raises(ValidationError, match="physician_id"):
            ScorecardOut(**payload)

    def test_round_trip_model_dump(self) -> None:
        sc = ScorecardOut(**_scorecard_payload(effective_comp_usd=400_000))
        dumped = sc.model_dump()
        restored = ScorecardOut(**dumped)
        assert restored.model_dump() == dumped


# ============================================================================
# sites.py — SiteOut with from_attributes=True
# ============================================================================


class TestSiteOut:
    def test_constructs_from_dict(self) -> None:
        s = SiteOut(
            id=1,
            name="Westside Regional",
            state="FL",
            hospital_system="HCA",
            status="ACTIVE",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert s.id == 1

    def test_hydrates_from_orm_attributes(self) -> None:
        """`model_config = ConfigDict(from_attributes=True)` allows
        instantiation from any object with matching attributes — proves
        the ORM-row hydration path that the router relies on."""

        class _FakeOrmRow:
            id = 42
            name = "JFK Main Med Ctr"
            state = "FL"
            hospital_system = "JFK Health"
            status = "ACTIVE"
            created_at = datetime(2026, 1, 1, tzinfo=UTC)

        s = SiteOut.model_validate(_FakeOrmRow())
        assert s.id == 42
        assert s.name == "JFK Main Med Ctr"

    def test_accepts_null_hospital_system(self) -> None:
        SiteOut(
            id=1,
            name="X",
            state="FL",
            hospital_system=None,
            status="ACTIVE",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


# ============================================================================
# alerts.py — Alert + Meta
# ============================================================================


class TestAlert:
    def test_full_construct(self) -> None:
        a = Alert(
            id="ar-aging-fl-2026-05",
            severity="red",
            category="finance",
            title="FL AR >120d exceeds threshold",
            detail="11% over 120 days, target <8%",
            owner="Sandy Collins",
        )
        assert a.severity == "red"

    def test_missing_required_id_raises(self) -> None:
        with pytest.raises(ValidationError, match="id"):
            Alert(  # type: ignore[call-arg]
                severity="red",
                category="finance",
                title="t",
                detail="d",
                owner="o",
            )


class TestMeta:
    def test_full_construct(self) -> None:
        m = Meta(
            generated_at="2026-05-17T15:00:00Z",
            data_source="VENTRA_FL_FALLBACK",
            note="Sandy's manual entry; Ventra SFTP pending",
        )
        assert m.generated_at.startswith("2026-")
