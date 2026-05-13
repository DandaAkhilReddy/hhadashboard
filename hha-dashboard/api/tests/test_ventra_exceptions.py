"""Unit tests for jobs.ventra_ingest.exceptions.

These pin the exception hierarchy that the main orchestrator's ``except``
chain depends on (Python MRO routes ADRViolation → ValidationError →
Exception). A change that breaks ``isinstance(e, ValidationError)`` for
ADRViolation would silently re-route V12 incidents through the generic
quarantine path — exactly the kind of regression CI must catch.
"""

from __future__ import annotations

import pytest

from jobs.ventra_ingest.exceptions import ADRViolation, DedupSkip, ValidationError


class TestValidationError:
    """Shape contract for V1-V11, V13 quarantine routing."""

    def test_carries_rule_message_and_details(self) -> None:
        err = ValidationError(
            rule="V5",
            message="unknown column foo",
            details={"file_name": "collections.csv", "line_no": 2},
        )

        assert err.rule == "V5"
        assert err.message == "unknown column foo"
        assert err.details == {"file_name": "collections.csv", "line_no": 2}

    def test_details_defaults_to_empty_dict_when_none(self) -> None:
        """Routing code reads err.details unconditionally; None would crash."""
        err = ValidationError(rule="V1", message="manifest unparseable")

        assert err.details == {}

    def test_details_defaults_to_empty_dict_when_omitted(self) -> None:
        err = ValidationError(rule="V1", message="manifest unparseable", details=None)

        assert err.details == {}

    def test_str_includes_rule_prefix(self) -> None:
        """``str(err)`` is what landed in ops.ingest_run.error_message until
        the main orchestrator started passing structured details — the
        ``V<n>: ...`` shape is the operator-facing contract."""
        err = ValidationError(rule="V9", message="ar buckets dup")

        assert str(err) == "V9: ar buckets dup"

    def test_is_exception_subclass(self) -> None:
        assert issubclass(ValidationError, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            raise ValidationError(rule="V3", message="sha mismatch")

        assert exc_info.value.rule == "V3"


class TestADRViolation:
    """Phase 1B main.py catches ADRViolation BEFORE ValidationError. Subclass
    relationship must hold and rule must be locked to V12."""

    def test_is_validation_error_subclass(self) -> None:
        """MRO: catching ValidationError without ADRViolation first would
        route a V12 incident through the wrong path (no incident email)."""
        assert issubclass(ADRViolation, ValidationError)

    def test_instance_is_validation_error(self) -> None:
        err = ADRViolation(message="non-FL facility", details={"facility_no": 99})

        assert isinstance(err, ValidationError)
        assert isinstance(err, Exception)

    def test_rule_is_locked_to_v12(self) -> None:
        """ADR-005 says non-FL facility in Ventra drop is the only V12 case;
        the constructor does not accept a rule arg to prevent accidental
        re-tagging."""
        err = ADRViolation(message="tx facility leaked")

        assert err.rule == "V12"

    def test_carries_message_and_details(self) -> None:
        err = ADRViolation(
            message="non-FL facility in Ventra drop",
            details={
                "file_name": "collections.csv",
                "line_no": 7,
                "facility_no": 99,
                "hha_state": "TX",
            },
        )

        assert err.message == "non-FL facility in Ventra drop"
        assert err.details["facility_no"] == 99
        assert err.details["hha_state"] == "TX"

    def test_details_defaults_to_empty(self) -> None:
        err = ADRViolation(message="boom")

        assert err.details == {}

    def test_str_includes_v12_prefix(self) -> None:
        err = ADRViolation(message="non-FL facility")

        assert str(err) == "V12: non-FL facility"

    def test_caught_as_validation_error_via_subclass_check(self) -> None:
        """The orchestrator may catch ValidationError after the ADRViolation
        clause — make sure the subclass still satisfies that catch."""
        try:
            raise ADRViolation(message="boom")
        except ValidationError as e:
            assert e.rule == "V12"
        else:  # pragma: no cover - sanity guard, would fail above
            pytest.fail("expected ADRViolation to be caught as ValidationError")


class TestDedupSkip:
    """V13 idempotent re-delivery path. NOT a ValidationError — a successful
    no-op outcome that the orchestrator routes through the success branch."""

    def test_is_not_validation_error(self) -> None:
        """If this becomes a ValidationError subclass, the quarantine path
        starts firing on every duplicate manifest — operator spam + false
        quarantine writes."""
        assert not issubclass(DedupSkip, ValidationError)
        err = DedupSkip(drop_date="2026-05-13", files=["collections.csv"])
        assert not isinstance(err, ValidationError)

    def test_carries_drop_date_and_files(self) -> None:
        err = DedupSkip(
            drop_date="2026-05-13",
            files=["collections.csv", "ar_snapshot.csv"],
        )

        assert err.drop_date == "2026-05-13"
        assert err.files == ["collections.csv", "ar_snapshot.csv"]

    def test_str_includes_drop_date_and_files_csv(self) -> None:
        err = DedupSkip(
            drop_date="2026-05-13",
            files=["collections.csv", "ar_snapshot.csv"],
        )

        rendered = str(err)
        assert "2026-05-13" in rendered
        assert "collections.csv,ar_snapshot.csv" in rendered

    def test_handles_empty_file_list(self) -> None:
        """Edge case: caller could pass [] if every file in a manifest hit
        dedup but the list was already filtered upstream."""
        err = DedupSkip(drop_date="2026-05-13", files=[])

        assert err.files == []
        assert str(err) == "dedup_skip drop_date=2026-05-13 files="

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(DedupSkip) as exc_info:
            raise DedupSkip(drop_date="2026-05-13", files=["x.csv"])

        assert exc_info.value.drop_date == "2026-05-13"
