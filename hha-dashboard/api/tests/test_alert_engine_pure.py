"""Pure-Python tests for ``app.services.alert_engine``.

The existing ``test_alert_engine.py`` is gated on a live Postgres and
``pytest.skip``'s the whole module when the DB isn't reachable. That
leaves the dataclass shape + threshold constants entirely uncovered in
CI environments without a database. This module plugs that gap with
no I/O — every test is a synchronous assertion against a frozen
dataclass or a module-level constant.

The threshold values are part of the contract: ops leadership reviews
them and the cron path uses them to raise (or suppress) flags. Pinning
them here means a sneaky tweak to ``alert_engine.py`` shows up as a
failing test, not a quiet behavior change in production.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass
from decimal import Decimal
from typing import get_args

import pytest

from app.services import alert_engine
from app.services.alert_engine import (
    AR_OVER_120_PCT_THRESHOLD,
    BELOW_FMV_COUNT_THRESHOLD,
    DC_48H_FLOOR_PCT,
    FL_MONTHLY_COLLECTIONS_TARGET_USD,
    HP_24H_FLOOR_PCT,
    LOS_CEILING_DAYS,
    NCR_FLOOR_PCT,
    OPEN_POSITIONS_THRESHOLD,
    TX_MONTHLY_COLLECTIONS_TARGET_USD,
    AlertCandidate,
    Category,
    Severity,
)

# ============================================================================
# AlertCandidate dataclass shape
# ============================================================================


class TestAlertCandidateShape:
    def test_is_dataclass(self) -> None:
        assert is_dataclass(AlertCandidate)

    def test_field_names_locked(self) -> None:
        # The cron's idempotency check + the front-end serializer both depend
        # on this exact field ordering.
        names = [f.name for f in fields(AlertCandidate)]
        assert names == ["id", "severity", "category", "title", "detail", "owner"]

    def test_every_field_is_str_annotated(self) -> None:
        # Severity / Category are Literal[str, ...] which still satisfies str.
        # With ``from __future__ import annotations`` the annotations are
        # strings, so we assert via the underlying typing introspection.
        annotations = AlertCandidate.__annotations__
        for name in ("id", "title", "detail", "owner"):
            assert annotations[name] == "str"
        # Severity / Category are Literal aliases — just confirm presence.
        assert annotations["severity"] == "Severity"
        assert annotations["category"] == "Category"


class TestAlertCandidateFrozen:
    def test_instances_are_frozen(self) -> None:
        a = AlertCandidate(
            id="fl-collections-2026-05",
            severity="red",
            category="finance",
            title="FL collections below target",
            detail="2,100,000 of 2,500,000",
            owner="Sandy",
        )
        with pytest.raises(FrozenInstanceError):
            a.id = "mutated"  # type: ignore[misc]

    def test_instances_are_hashable(self) -> None:
        # frozen=True implicitly makes the class hashable, so callers can
        # de-dup via set() or use the candidate as a dict key.
        a = AlertCandidate("x", "red", "finance", "t", "d", "o")
        assert hash(a) == hash(a)
        # Identical fields → identical hash.
        b = AlertCandidate("x", "red", "finance", "t", "d", "o")
        assert hash(a) == hash(b)

    def test_equality_by_value(self) -> None:
        a = AlertCandidate("x", "red", "finance", "t", "d", "o")
        b = AlertCandidate("x", "red", "finance", "t", "d", "o")
        assert a == b

    def test_inequality_on_any_field_diff(self) -> None:
        base = AlertCandidate("x", "red", "finance", "t", "d", "o")
        for field_name, mutated in [
            ("id", "y"),
            ("severity", "yellow"),
            ("category", "operations"),
            ("title", "tt"),
            ("detail", "dd"),
            ("owner", "oo"),
        ]:
            kwargs = {
                "id": base.id,
                "severity": base.severity,
                "category": base.category,
                "title": base.title,
                "detail": base.detail,
                "owner": base.owner,
            }
            kwargs[field_name] = mutated
            assert AlertCandidate(**kwargs) != base, field_name


# ============================================================================
# AlertCandidate.as_dict() — serializer used by the API + cron payloads
# ============================================================================


class TestAsDict:
    def test_returns_all_six_keys(self) -> None:
        a = AlertCandidate("id1", "red", "finance", "T", "D", "O")
        d = a.as_dict()
        assert set(d.keys()) == {"id", "severity", "category", "title", "detail", "owner"}

    def test_key_order_matches_field_order(self) -> None:
        # The front-end log + email template reads keys in dict-insertion
        # order; preserving field order avoids visual churn between rows.
        a = AlertCandidate("id1", "red", "finance", "T", "D", "O")
        assert list(a.as_dict().keys()) == [
            "id",
            "severity",
            "category",
            "title",
            "detail",
            "owner",
        ]

    def test_values_round_trip(self) -> None:
        a = AlertCandidate(
            id="below-fmv-2026-05",
            severity="yellow",
            category="people",
            title="3 MDs below MGMA p25",
            detail="Dr. X, Dr. Y, Dr. Z",
            owner="Andrea",
        )
        d = a.as_dict()
        assert d["id"] == "below-fmv-2026-05"
        assert d["severity"] == "yellow"
        assert d["category"] == "people"
        assert d["title"] == "3 MDs below MGMA p25"
        assert d["detail"] == "Dr. X, Dr. Y, Dr. Z"
        assert d["owner"] == "Andrea"

    def test_returned_dict_is_a_fresh_mutable_copy(self) -> None:
        # Callers may want to enrich the dict before posting it. The
        # frozen-dataclass invariant must NOT extend to the returned dict.
        a = AlertCandidate("id1", "blue", "clinical", "T", "D", "O")
        d = a.as_dict()
        d["extra"] = "ok"  # mutation should succeed
        # And the second call returns an untouched fresh dict.
        assert "extra" not in a.as_dict()

    def test_dict_value_types_are_strings_only(self) -> None:
        a = AlertCandidate("id1", "red", "finance", "T", "D", "O")
        d = a.as_dict()
        for v in d.values():
            assert isinstance(v, str)


# ============================================================================
# Severity / Category Literal value sets
# ============================================================================


class TestSeverityLiteral:
    def test_exactly_three_severities(self) -> None:
        # The Literal type itself defines the legal set — pin it so a sneaky
        # 4th value doesn't slip into the cron path.
        assert set(get_args(Severity)) == {"red", "yellow", "blue"}

    def test_severity_order_red_yellow_blue(self) -> None:
        # The order matters for the digest template (red rows render first).
        assert get_args(Severity) == ("red", "yellow", "blue")


class TestCategoryLiteral:
    def test_exactly_four_categories(self) -> None:
        # Matches the 4 team boards in DASHBOARD_PLAN.md.
        assert set(get_args(Category)) == {
            "finance",
            "operations",
            "clinical",
            "people",
        }

    def test_no_scorecards_category(self) -> None:
        # Doctor Scorecards is an exec-only board and is not part of the
        # alert engine — confirm it's not accidentally added.
        assert "scorecards" not in get_args(Category)


# ============================================================================
# Threshold constants — pinned per ops review
# ============================================================================


class TestFinanceThresholds:
    def test_fl_monthly_collections_target_is_2_5m(self) -> None:
        # Per ops review with Sandy + the CFO — FL book is targeted at
        # $2.5M/mo through the Ventra Florida automation. Changing this
        # without ops approval is a process violation.
        assert Decimal("2_500_000") == FL_MONTHLY_COLLECTIONS_TARGET_USD
        assert isinstance(FL_MONTHLY_COLLECTIONS_TARGET_USD, Decimal)

    def test_tx_monthly_collections_target_is_800k(self) -> None:
        # TX book is the manual-entry path (ADR-005). Lower target reflects
        # the smaller footprint (4 TX sites vs 7 FL sites).
        assert Decimal("800_000") == TX_MONTHLY_COLLECTIONS_TARGET_USD
        assert isinstance(TX_MONTHLY_COLLECTIONS_TARGET_USD, Decimal)

    def test_fl_target_is_strictly_greater_than_tx(self) -> None:
        # Sanity: the 7-site FL book outperforms the 4-site TX book.
        assert FL_MONTHLY_COLLECTIONS_TARGET_USD > TX_MONTHLY_COLLECTIONS_TARGET_USD

    def test_ar_over_120_percent_threshold_is_20(self) -> None:
        # Industry standard — over-120 buckets > 20% of total AR is a red flag.
        assert Decimal("20") == AR_OVER_120_PCT_THRESHOLD
        assert isinstance(AR_OVER_120_PCT_THRESHOLD, Decimal)

    def test_ncr_floor_is_90_percent(self) -> None:
        # Net Collection Rate floor — below 90% triggers a finance alert.
        assert Decimal("90") == NCR_FLOOR_PCT
        assert isinstance(NCR_FLOOR_PCT, Decimal)


class TestClinicalThresholds:
    def test_hp_24h_floor_is_90_percent(self) -> None:
        # H&P-within-24h compliance floor.
        assert Decimal("90") == HP_24H_FLOOR_PCT
        assert isinstance(HP_24H_FLOOR_PCT, Decimal)

    def test_dc_48h_floor_is_90_percent(self) -> None:
        # Discharge summary within 48h compliance floor.
        assert Decimal("90") == DC_48H_FLOOR_PCT
        assert isinstance(DC_48H_FLOOR_PCT, Decimal)

    def test_los_ceiling_is_5_days(self) -> None:
        # ALOS ceiling — beyond 5.0 days is a clinical alert.
        assert Decimal("5.0") == LOS_CEILING_DAYS
        assert isinstance(LOS_CEILING_DAYS, Decimal)

    def test_clinical_floors_are_consistent(self) -> None:
        # H&P-24h and DC-48h share the same 90% floor — symmetric reads.
        assert HP_24H_FLOOR_PCT == DC_48H_FLOOR_PCT


class TestPeopleThresholds:
    def test_below_fmv_count_threshold_is_5(self) -> None:
        # If 5+ MDs are below MGMA p25, the People board's "below-FMV count"
        # tile flips red.
        assert BELOW_FMV_COUNT_THRESHOLD == 5
        assert isinstance(BELOW_FMV_COUNT_THRESHOLD, int)

    def test_open_positions_threshold_is_8(self) -> None:
        # Unfilled-positions ceiling — beyond 8 open is a People alert.
        assert OPEN_POSITIONS_THRESHOLD == 8
        assert isinstance(OPEN_POSITIONS_THRESHOLD, int)


class TestThresholdTypes:
    @pytest.mark.parametrize(
        "name",
        [
            "FL_MONTHLY_COLLECTIONS_TARGET_USD",
            "TX_MONTHLY_COLLECTIONS_TARGET_USD",
            "AR_OVER_120_PCT_THRESHOLD",
            "NCR_FLOOR_PCT",
            "HP_24H_FLOOR_PCT",
            "DC_48H_FLOOR_PCT",
            "LOS_CEILING_DAYS",
        ],
    )
    def test_money_and_percentage_thresholds_are_decimal(self, name: str) -> None:
        # Decimal (not float) is mandatory for any value that hits a finance
        # comparison — float arithmetic on cents has historically caused
        # rounding-vs-target false positives.
        assert isinstance(getattr(alert_engine, name), Decimal)

    @pytest.mark.parametrize(
        "name",
        ["BELOW_FMV_COUNT_THRESHOLD", "OPEN_POSITIONS_THRESHOLD"],
    )
    def test_count_thresholds_are_int(self, name: str) -> None:
        # Counts are int, not Decimal — they're compared against COUNT(*)
        # results from the DB, which come back as int.
        assert isinstance(getattr(alert_engine, name), int)
        assert not isinstance(getattr(alert_engine, name), bool)
