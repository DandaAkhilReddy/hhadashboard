"""Metadata-level test for ``app.models.audit.AuditLog`` — the table
written by the Postgres ``audit.log_change()`` trigger on every audited
mutation.

Mirrors the metadata-pin pattern from ``test_alerts_model.py`` /
``test_entries_manual_models.py``. The trigger itself is exercised
end-to-end by ``test_audit_triggers.py`` against a live Postgres; this
file locks the column shape + ADR-001 ``data_class`` invariants at
unit speed.
"""

from __future__ import annotations

import pytest

from app.models.audit import JSON_VARIANT, AuditLog


class TestAuditLogTableShape:
    def test_schema_is_audit(self) -> None:
        assert AuditLog.__table__.schema == "audit"

    def test_table_name_locked(self) -> None:
        assert AuditLog.__tablename__ == "audit_log"

    @pytest.mark.parametrize(
        "col",
        [
            "id",
            "table_schema",
            "table_name",
            "row_pk",
            "action",
            "diff",
            "changed_by_upn",
            "reason",
            "changed_at",
        ],
    )
    def test_required_column_present(self, col: str) -> None:
        assert col in AuditLog.__table__.columns

    def test_id_is_primary_key(self) -> None:
        pk_cols = [c.name for c in AuditLog.__table__.primary_key.columns]
        assert pk_cols == ["id"]

    @pytest.mark.parametrize(
        "col",
        ["id", "table_schema", "table_name", "row_pk", "action", "diff", "changed_by_upn", "changed_at"],
    )
    def test_required_non_null_columns(self, col: str) -> None:
        # Every load-bearing column is NOT NULL — the trigger writes them
        # all on every audited mutation.
        assert AuditLog.__table__.columns[col].nullable is False

    def test_reason_is_nullable(self) -> None:
        # ``reason`` is the only optional column — trigger leaves it NULL
        # unless the caller explicitly set the ``audit.reason`` GUC.
        assert AuditLog.__table__.columns["reason"].nullable is True


class TestAuditLogDataClassification:
    @pytest.mark.parametrize(
        "col",
        [
            "id",
            "table_schema",
            "table_name",
            "row_pk",
            "action",
            "diff",
            "changed_by_upn",
            "reason",
            "changed_at",
        ],
    )
    def test_every_column_is_tier_b(self, col: str) -> None:
        # The whole audit log is Tier B (directory / workforce) by design:
        # it contains diffs of Tier-A operational rows attributed to a UPN.
        # Per ADR-001 + ADR-003.
        assert AuditLog.__table__.columns[col].info.get("data_class") == "B"


class TestJsonVariant:
    def test_diff_column_uses_json_variant(self) -> None:
        """The ``diff`` column gets JSONB on Postgres and generic JSON on
        SQLite — pin via column-level type identity."""
        diff_col = AuditLog.__table__.columns["diff"]
        # SQLAlchemy stores TypeEngine instances; identity check against
        # the module-level JSON_VARIANT is the cheapest way to confirm
        # the migration applies the dialect-aware variant.
        assert diff_col.type is JSON_VARIANT


class TestAuditLogDocumentedContract:
    def test_no_phi_columns(self) -> None:
        """Audit rows must never carry PHI directly — the ``diff`` field
        carries column-level diffs of audited tables (all already
        non-PHI by ADR-001), but no PHI keys should appear at this
        layer either."""
        cols = set(AuditLog.__table__.columns.keys())
        for forbidden in (
            "patient_id",
            "patient_name",
            "mrn",
            "claim_id",
            "encounter_id",
            "member_id",
        ):
            assert forbidden not in cols
