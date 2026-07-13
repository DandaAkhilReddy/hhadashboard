"""Metadata-level tests for the alerts schema models.

Locks the CHECK invariants and ADR-001 classification on the three
alert tables. The cron + alert_engine tests cover behavior; this file
catches schema-shape regressions at unit speed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models.alerts import AlertLog, AlertSubscription, CredentialAlertLog


def _has_check(model: type, suffix: str) -> bool:
    return any(
        c.name is not None and c.name.endswith(suffix)
        for c in model.__table__.constraints
        if isinstance(c, CheckConstraint)
    )


def _has_unique(model: type, suffix: str) -> bool:
    return any(
        c.name is not None and c.name.endswith(suffix)
        for c in model.__table__.constraints
        if isinstance(c, UniqueConstraint)
    )


class TestAlertSubscription:
    def test_schema_is_alerts(self) -> None:
        assert AlertSubscription.__table__.schema == "alerts"

    def test_role_check_locks_six_legal_roles(self) -> None:
        found = next(
            (
                c
                for c in AlertSubscription.__table__.constraints
                if isinstance(c, CheckConstraint)
                and c.name is not None
                and c.name.endswith("role_valid")
            ),
            None,
        )
        assert found is not None
        sql = str(found.sqltext)
        for role in (
            "admin",
            "exec",
            "owner_finance",
            "owner_ops",
            "owner_clinical",
            "owner_hr",
        ):
            assert role in sql, f"Role {role!r} missing from role_valid CHECK"

    def test_frequency_check_locks_four_legal_values(self) -> None:
        found = next(
            (
                c
                for c in AlertSubscription.__table__.constraints
                if isinstance(c, CheckConstraint)
                and c.name is not None
                and c.name.endswith("frequency_valid")
            ),
            None,
        )
        assert found is not None
        sql = str(found.sqltext)
        for freq in ("immediate", "daily", "weekly", "never"):
            assert freq in sql

    def test_unique_role_email(self) -> None:
        assert _has_unique(AlertSubscription, "uq_alert_subscriptions_role_email")

    @pytest.mark.parametrize(
        ("col", "expected_class"),
        [
            ("id", "A"),
            ("role", "A"),
            ("email", "B"),  # directory — recipient address
            ("categories", "A"),
            ("frequency", "A"),
        ],
    )
    def test_column_data_class(self, col: str, expected_class: str) -> None:
        c = AlertSubscription.__table__.columns[col]
        assert c.info.get("data_class") == expected_class


class TestAlertLog:
    def test_schema_is_alerts(self) -> None:
        assert AlertLog.__table__.schema == "alerts"

    def test_unique_dedup_constraint(self) -> None:
        assert _has_unique(AlertLog, "uq_alert_log_dedup")

    def test_recipient_email_is_tier_b(self) -> None:
        # Recipient identity is directory data — Tier B per ADR-001.
        c = AlertLog.__table__.columns["recipient_email"]
        assert c.info.get("data_class") == "B"

    @pytest.mark.parametrize(
        "col",
        [
            "alert_id",
            "target_date",
            "severity",
            "category",
            "sent_at",
            "acs_message_id",
        ],
    )
    def test_aggregate_columns_are_tier_a(self, col: str) -> None:
        c = AlertLog.__table__.columns[col]
        assert c.info.get("data_class") == "A"


class TestCredentialAlertLog:
    def test_schema_is_alerts(self) -> None:
        assert CredentialAlertLog.__table__.schema == "alerts"

    def test_threshold_band_locked_to_30_60_90(self) -> None:
        assert _has_check(CredentialAlertLog, "threshold_band_valid")
        # SQL pinned values
        found = next(
            (
                c
                for c in CredentialAlertLog.__table__.constraints
                if isinstance(c, CheckConstraint)
                and c.name is not None
                and c.name.endswith("threshold_band_valid")
            ),
            None,
        )
        assert found is not None
        sql = str(found.sqltext)
        assert "30" in sql
        assert "60" in sql
        assert "90" in sql

    def test_unique_per_credential_per_band(self) -> None:
        assert _has_unique(CredentialAlertLog, "uq_credential_alert_log_band")

    def test_credential_id_fk_cascades_on_delete(self) -> None:
        # When a credential is removed, its alert-band rows go with it.
        col = CredentialAlertLog.__table__.columns["credential_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].ondelete == "CASCADE"
        # Inspect the unresolved target — avoid forcing the FK to resolve
        # (which would require importing masters.credentials). The target
        # string keeps it free of cross-module test dependencies.
        assert fks[0]._colspec == "masters.credentials.id"

    @pytest.mark.parametrize(
        "col",
        ["id", "credential_id", "threshold_band", "alerted_on"],
    )
    def test_every_column_is_tier_a(self, col: str) -> None:
        c = CredentialAlertLog.__table__.columns[col]
        assert c.info.get("data_class") == "A"
