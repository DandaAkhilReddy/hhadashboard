"""Unit tests for the pure-Python (synchronous, no-DB) functions in
``app.services.fake_data``.

The async ``get_*_summary`` functions in the same module read from a
real Postgres and are exercised by the ``test_*_read_prefers_db.py``
integration tests. This file covers everything else: the deterministic
helpers, the dataclass-driven constants, and the hardcoded demo lists
used by routers as fallbacks when no DB entries exist yet.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.fake_data import (
    ALL_SITES,
    FL_DAILY_TARGET,
    FL_MTD_TARGET,
    FL_SITES,
    SCORECARD_MDS,
    TX_DAILY_TARGET,
    TX_SITES,
    MDSpec,
    SiteSpec,
    _noise,
    _seed,
    get_credentials_expiring,
    get_current_alerts,
    get_meta,
    get_monthly_revenue_trend,
    get_open_positions_by_site,
    get_scorecards,
)

# ============================================================================
# Deterministic helpers
# ============================================================================


class TestSeed:
    def test_returns_value_in_unit_interval(self) -> None:
        # _seed maps any hashable tuple to a float in [0, 1).
        for parts in [(), ("a",), (1, 2, "x"), ("hp-fl", "2026-05-17")]:
            v = _seed(*parts)
            assert 0.0 <= v < 1.0

    def test_is_deterministic_for_same_inputs(self) -> None:
        assert _seed("hp-fl", "2026-05-17") == _seed("hp-fl", "2026-05-17")

    def test_distinct_inputs_yield_distinct_outputs(self) -> None:
        # Two different seed keys should not collide.
        assert _seed("a") != _seed("b")
        assert _seed("hp-fl", "2026-05-17") != _seed("hp-fl", "2026-05-18")


class TestNoise:
    def test_bounded_by_amplitude(self) -> None:
        for _ in range(20):
            v = _noise(("rev", 2026, 1), amplitude=0.05)
            assert -0.05 <= v <= 0.05

    def test_zero_amplitude_returns_zero(self) -> None:
        assert _noise(("any",), 0.0) == 0.0

    def test_deterministic(self) -> None:
        a = _noise(("rev", 2026, 5), 0.06)
        b = _noise(("rev", 2026, 5), 0.06)
        assert a == b


# ============================================================================
# Sites constants
# ============================================================================


class TestSiteConstants:
    def test_all_sites_is_fl_plus_tx(self) -> None:
        assert ALL_SITES == FL_SITES + TX_SITES

    def test_fl_sites_are_all_state_fl(self) -> None:
        # Per ADR-005: Florida book is the only one the Ventra ingestion touches.
        assert all(s.state == "FL" for s in FL_SITES)

    def test_tx_sites_are_all_state_tx(self) -> None:
        assert all(s.state == "TX" for s in TX_SITES)

    def test_fl_site_count_matches_dashboard_plan(self) -> None:
        # 7 FL sites + 4 TX sites = 11 total, per DASHBOARD_PLAN.md.
        assert len(FL_SITES) == 7
        assert len(TX_SITES) == 4
        assert len(ALL_SITES) == 11

    def test_site_specs_are_immutable_dataclasses(self) -> None:
        site = ALL_SITES[0]
        assert isinstance(site, SiteSpec)
        # frozen=True means assignment raises FrozenInstanceError
        with pytest.raises(Exception):  # noqa: B017,PT011
            site.name = "modified"  # type: ignore[misc]

    def test_targets_are_positive(self) -> None:
        assert FL_DAILY_TARGET > 0
        assert TX_DAILY_TARGET > 0
        assert FL_MTD_TARGET > FL_DAILY_TARGET  # 30-day rollup beats one day


# ============================================================================
# Monthly revenue trend
# ============================================================================


class TestMonthlyRevenueTrend:
    def test_returns_12_months(self) -> None:
        rows = get_monthly_revenue_trend()
        assert len(rows) == 12

    def test_every_entry_has_month_and_revenue(self) -> None:
        rows = get_monthly_revenue_trend()
        for r in rows:
            assert "month" in r
            assert "revenue_usd" in r
            assert isinstance(r["revenue_usd"], int)

    def test_current_month_is_pinned_partial_value(self) -> None:
        # Per the source: months[-1]["revenue_usd"] = 2_280_000 (pain point)
        rows = get_monthly_revenue_trend()
        assert rows[-1]["revenue_usd"] == 2_280_000

    def test_month_labels_render_as_three_letter_year(self) -> None:
        rows = get_monthly_revenue_trend()
        # e.g. "May 2026" — three-letter month + four-digit year
        for r in rows:
            label = r["month"]
            assert len(label) >= 7  # "Xxx YYYY"

    def test_deterministic_across_calls(self) -> None:
        """All months except the last are noise-driven but deterministic
        (seeded by (year, month)). Calling twice in the same day yields
        the same numbers."""
        a = get_monthly_revenue_trend()
        b = get_monthly_revenue_trend()
        assert a == b


# ============================================================================
# Credentials expiring
# ============================================================================


class TestCredentialsExpiring:
    def test_returns_seven_credentials(self) -> None:
        out = get_credentials_expiring()
        assert len(out) == 7

    def test_each_row_has_expected_fields(self) -> None:
        out = get_credentials_expiring()
        for row in out:
            assert set(row.keys()) == {
                "physician",
                "type",
                "expires_in_days",
                "expires_on",
                "tier",
            }

    def test_first_four_are_tier_urgent(self) -> None:
        # The mockup orders <30d as urgent, then warning.
        out = get_credentials_expiring()
        assert all(row["tier"] == "urgent" for row in out[:4])

    def test_remaining_three_are_tier_warning(self) -> None:
        out = get_credentials_expiring()
        assert all(row["tier"] == "warning" for row in out[4:])

    def test_expires_in_days_is_strictly_increasing(self) -> None:
        # The list is sorted by urgency (closest expiry first).
        out = get_credentials_expiring()
        days = [row["expires_in_days"] for row in out]
        assert days == sorted(days)


# ============================================================================
# Open positions
# ============================================================================


class TestOpenPositionsBySite:
    def test_returns_seven_rows(self) -> None:
        out = get_open_positions_by_site()
        assert len(out) == 7

    def test_severity_values_are_documented_set(self) -> None:
        out = get_open_positions_by_site()
        for row in out:
            assert row["severity"] in {"high", "medium", "low"}

    def test_sum_of_counts_matches_demo_total(self) -> None:
        # Sanity: numbers come from the mockup; total counts = 12.
        out = get_open_positions_by_site()
        assert sum(row["count"] for row in out) == 12

    def test_state_field_has_fl_tx_or_dash(self) -> None:
        # The "Other / unassigned" bucket uses an em-dash for state.
        out = get_open_positions_by_site()
        for row in out:
            assert row["state"] in {"FL", "TX", "—"}


# ============================================================================
# Scorecards
# ============================================================================


class TestScorecardMdsConstants:
    def test_seven_demo_physicians(self) -> None:
        assert len(SCORECARD_MDS) == 7

    def test_every_md_is_frozen_dataclass(self) -> None:
        for md in SCORECARD_MDS:
            assert isinstance(md, MDSpec)

    @pytest.mark.parametrize("md", list(SCORECARD_MDS))
    def test_md_field_literals(self, md: MDSpec) -> None:
        # employment_type and comp_model are Literal types — confirm the
        # constants used in the demo set are valid. With `from __future__
        # import annotations` the type hints are strings, so we pin the
        # legal value sets directly rather than introspecting.
        assert md.employment_type in {"W2", "1099"}
        assert md.comp_model in {"SALARY", "PER_DIEM", "RVU", "HYBRID"}


class TestGetScorecards:
    def test_returns_one_row_per_md(self) -> None:
        rows = get_scorecards()
        assert len(rows) == len(SCORECARD_MDS)

    def test_redacts_comp_when_include_comp_detail_false(self) -> None:
        # Default: include_comp_detail=False → dollar fields are None
        rows = get_scorecards()
        for r in rows:
            assert r["effective_comp_usd"] is None
            assert r["fmv_source_note"] is None

    def test_surfaces_comp_when_include_comp_detail_true(self) -> None:
        rows = get_scorecards(include_comp_detail=True)
        for r in rows:
            assert isinstance(r["effective_comp_usd"], int)
            assert isinstance(r["fmv_source_note"], str)

    def test_below_fmv_flag_drives_off_25th_percentile(self) -> None:
        """One demo MD is below the MGMA p25 — confirm at least one row
        carries below_fmv=True. (Otherwise the People board's
        below-FMV-count tile would never show non-zero in the demo.)"""
        rows = get_scorecards()
        assert any(r["below_fmv"] is True for r in rows)

    def test_mgma_band_is_one_of_five_documented_values(self) -> None:
        rows = get_scorecards()
        for r in rows:
            assert r["mgma_band"] in {
                "below_25",
                "25_50",
                "50_75",
                "75_90",
                "above_90",
            }

    def test_p2_placeholder_fields_default_to_none(self) -> None:
        rows = get_scorecards()
        for r in rows:
            assert r["revenue_per_fte_usd"] is None
            assert r["encounters_per_day"] is None
            assert r["documentation_score_pct"] is None
            assert r["chart_turnaround_days"] is None

    def test_physician_ids_are_one_indexed(self) -> None:
        rows = get_scorecards()
        # The enumerate(SCORECARD_MDS) start=0 + i + 1 means 1..N.
        ids = [r["physician_id"] for r in rows]
        assert ids == list(range(1, len(SCORECARD_MDS) + 1))


# ============================================================================
# Current alerts (fallback)
# ============================================================================


class TestGetCurrentAlerts:
    def test_returns_three_demo_alerts(self) -> None:
        out = get_current_alerts()
        assert len(out) == 3

    def test_today_param_is_accepted_for_compat(self) -> None:
        # The today kwarg is accepted but ignored — matches the engine
        # signature so routers can pass it interchangeably.
        a = get_current_alerts()
        b = get_current_alerts(today=date(2026, 5, 17))
        assert a == b

    def test_every_alert_has_required_fields(self) -> None:
        out = get_current_alerts()
        for alert in out:
            assert set(alert.keys()) >= {
                "id",
                "severity",
                "category",
                "title",
                "detail",
                "owner",
            }

    def test_severities_are_documented_set(self) -> None:
        out = get_current_alerts()
        for alert in out:
            assert alert["severity"] in {"red", "yellow", "blue"}

    def test_categories_are_documented_set(self) -> None:
        out = get_current_alerts()
        for alert in out:
            assert alert["category"] in {"finance", "operations", "clinical", "people"}


# ============================================================================
# Meta
# ============================================================================


class TestGetMeta:
    def test_has_generated_at_in_iso_z_format(self) -> None:
        meta = get_meta()
        # ISO 8601 + 'Z' suffix
        assert isinstance(meta["generated_at"], str)
        assert meta["generated_at"].endswith("Z")

    def test_data_source_pinned(self) -> None:
        assert get_meta()["data_source"] == "fake_data_service"

    def test_note_mentions_fake_data(self) -> None:
        # The note is the documented "this is fake data" warning for
        # consumers reading the meta — pin its substance.
        note = get_meta()["note"]
        assert "fake" in note.lower() or "deterministic" in note.lower()
