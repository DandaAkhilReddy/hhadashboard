"""Metadata-level tests for masters/* + uploads.upload_log + entries.daily_entries
+ auth.census_credentials. Same pattern as the manual/alerts tests: pin
CHECK names + ADR-001 ``data_class`` + StrEnum value catalogs at unit
speed, before a migration drift lands in CI's Postgres.

Coverage targets:
- ``Site`` / ``Contract`` / ``Physician`` / ``CompAgreement`` / ``Credential`` / ``SiteCoverage``
  (masters schema)
- ``UploadLog`` (uploads schema)
- ``DailyEntry`` (entries schema)
- ``CensusCredential`` (auth schema)
- The StrEnum value catalogs (StateCode, SiteStatus, EmploymentType,
  CompModel, PhysicianStatus, CredentialType, CoverageRole)
"""

from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models.census_credentials import CensusCredential
from app.models.entries import DailyEntry
from app.models.masters import (
    CompAgreement,
    CompModel,
    Contract,
    CoverageRole,
    Credential,
    CredentialType,
    EmploymentType,
    Physician,
    PhysicianStatus,
    Site,
    SiteCoverage,
    SiteStatus,
    StateCode,
)
from app.models.uploads import UploadLog


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


# ---------- Masters: StrEnum catalogs ----------


class TestMastersStrEnums:
    def test_state_code_locked_to_fl_tx(self) -> None:
        # Per ADR-005 — no third state ever in the Phase 1 scope.
        assert {member.value for member in StateCode} == {"FL", "TX"}

    def test_site_status_values(self) -> None:
        assert {member.value for member in SiteStatus} == {"ACTIVE", "PROSPECT", "TERMED"}

    def test_employment_type_w2_or_1099(self) -> None:
        assert {member.value for member in EmploymentType} == {"W2", "1099"}

    def test_comp_model_values(self) -> None:
        assert {member.value for member in CompModel} == {
            "SALARY",
            "PER_DIEM",
            "RVU",
            "HYBRID",
        }

    def test_physician_status_values(self) -> None:
        assert {member.value for member in PhysicianStatus} == {
            "ACTIVE",
            "PIP",
            "VACANT",
            "TERMED",
        }

    def test_credential_type_values(self) -> None:
        assert {member.value for member in CredentialType} == {
            "STATE_LICENSE",
            "DEA",
            "BOARD_CERTIFICATION",
            "HOSPITAL_PRIVILEGE",
        }

    def test_coverage_role_values(self) -> None:
        assert {member.value for member in CoverageRole} == {
            "MEDICAL_DIRECTOR",
            "LIAISON",
            "COVERING",
        }


# ---------- Masters tables ----------


class TestSite:
    def test_schema_is_masters(self) -> None:
        assert Site.__table__.schema == "masters"

    def test_name_is_unique(self) -> None:
        # The unique=True kwarg renders an unnamed unique index; just verify
        # the column flag, no name lookup.
        assert Site.__table__.columns["name"].unique is True

    @pytest.mark.parametrize(
        ("col", "expected_class"),
        [
            ("id", "D"),
            ("name", "D"),
            ("state", "D"),
            ("hospital_system", "D"),
            ("address", "D"),
            ("status", "B"),  # operational status is HR/directory class
        ],
    )
    def test_column_data_class(self, col: str, expected_class: str) -> None:
        assert Site.__table__.columns[col].info.get("data_class") == expected_class

    def test_no_phi_columns(self) -> None:
        cols = set(Site.__table__.columns.keys())
        for forbidden in ("patient_id", "mrn", "claim_id"):
            assert forbidden not in cols


class TestContract:
    def test_schema_is_masters(self) -> None:
        assert Contract.__table__.schema == "masters"

    @pytest.mark.parametrize(
        ("col", "expected_class"),
        [
            ("id", "A"),
            ("site_id", "A"),
            ("start_date", "A"),
            ("end_date", "A"),
            ("annual_subsidy_usd", "A"),
            ("payment_schedule", "A"),
            ("coverage_min_mds", "A"),
            ("contract_pdf_url", "D"),  # public link
        ],
    )
    def test_column_data_class(self, col: str, expected_class: str) -> None:
        assert Contract.__table__.columns[col].info.get("data_class") == expected_class


class TestPhysician:
    def test_schema_is_masters(self) -> None:
        assert Physician.__table__.schema == "masters"

    def test_npi_is_unique(self) -> None:
        assert Physician.__table__.columns["npi"].unique is True

    def test_id_is_tier_b_directory(self) -> None:
        # Even the PK is Tier B per ADR-001 — physician identity is HR/directory.
        assert Physician.__table__.columns["id"].info.get("data_class") == "B"

    @pytest.mark.parametrize(
        "col",
        [
            "name",
            "npi",
            "dea",
            "email",
            "current_status",
            "pip_start_date",
            "primary_site_id",
            "paycom_employee_id",
            "athena_provider_id",
            "hire_date",
            "term_date",
        ],
    )
    def test_every_physician_column_is_tier_b(self, col: str) -> None:
        assert Physician.__table__.columns[col].info.get("data_class") == "B"


class TestCompAgreement:
    def test_schema_is_masters(self) -> None:
        assert CompAgreement.__table__.schema == "masters"

    def test_effective_dates_check_pinned(self) -> None:
        assert _has_check(CompAgreement, "effective_dates")

    def test_physician_id_fk_cascades_on_delete(self) -> None:
        col = CompAgreement.__table__.columns["physician_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].ondelete == "CASCADE"
        assert fks[0]._colspec == "masters.physicians.id"

    @pytest.mark.parametrize(
        "col",
        [
            "id",
            "physician_id",
            "effective_from",
            "effective_to",
            "employment_type",
            "base_salary_usd",
            "per_diem_rate_usd",
            "rvu_rate_usd",
            "rvu_threshold_annual",
            "call_stipend_usd",
            "fmv_benchmark_usd",
            "notes",
            "created_by_upn",
        ],
    )
    def test_every_comp_column_is_tier_b(self, col: str) -> None:
        # Every comp-agreement column is HR/workforce — Tier B per ADR-001.
        assert CompAgreement.__table__.columns[col].info.get("data_class") == "B"


class TestCredential:
    def test_schema_is_masters(self) -> None:
        assert Credential.__table__.schema == "masters"

    def test_physician_id_fk_cascades_on_delete(self) -> None:
        col = Credential.__table__.columns["physician_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].ondelete == "CASCADE"

    def test_hospital_id_fk_set_null_on_delete(self) -> None:
        # When a hospital is removed, credentials keep existing but lose the FK.
        col = Credential.__table__.columns["hospital_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].ondelete == "SET NULL"

    def test_expires_on_is_not_null(self) -> None:
        # The alert engine relies on every credential having an expiry date.
        assert Credential.__table__.columns["expires_on"].nullable is False


class TestSiteCoverage:
    def test_schema_is_masters(self) -> None:
        assert SiteCoverage.__table__.schema == "masters"

    def test_site_and_physician_fks_both_cascade(self) -> None:
        for col_name in ("site_id", "physician_id"):
            col = SiteCoverage.__table__.columns[col_name]
            fks = list(col.foreign_keys)
            assert len(fks) == 1
            assert fks[0].ondelete == "CASCADE"


# ---------- Uploads schema ----------


class TestUploadLog:
    def test_schema_is_uploads(self) -> None:
        assert UploadLog.__table__.schema == "uploads"

    def test_status_check_locks_five_legal_values(self) -> None:
        found = next(
            (
                c
                for c in UploadLog.__table__.constraints
                if isinstance(c, CheckConstraint)
                and c.name is not None
                and c.name.endswith("status_valid")
            ),
            None,
        )
        assert found is not None
        sql = str(found.sqltext)
        for value in ("uploaded", "processing", "processed", "error", "expired"):
            assert value in sql

    def test_size_and_retry_non_negative_checks(self) -> None:
        assert _has_check(UploadLog, "size_non_negative")
        assert _has_check(UploadLog, "retry_count_non_negative")

    def test_uploaded_by_upn_is_tier_b(self) -> None:
        # Identity is directory data.
        c = UploadLog.__table__.columns["uploaded_by_upn"]
        assert c.info.get("data_class") == "B"

    @pytest.mark.parametrize(
        "col",
        [
            "id",
            "uploaded_at",
            "file_type",
            "original_filename",
            "blob_name",
            "size_bytes",
            "sha256",
            "status",
            "processing_started_at",
            "processing_finished_at",
            "rows_written",
            "error_message",
            "retry_count",
        ],
    )
    def test_aggregate_columns_are_tier_a(self, col: str) -> None:
        assert UploadLog.__table__.columns[col].info.get("data_class") == "A"

    def test_no_phi_columns(self) -> None:
        cols = set(UploadLog.__table__.columns.keys())
        for forbidden in ("patient_id", "mrn", "ssn", "dob"):
            assert forbidden not in cols


# ---------- Entries: daily_entries ----------


class TestDailyEntry:
    def test_schema_is_entries(self) -> None:
        assert DailyEntry.__table__.schema == "entries"

    def test_unique_per_site_per_day(self) -> None:
        assert _has_unique(DailyEntry, "one_entry_per_site_per_day")

    def test_census_and_open_shifts_non_negative(self) -> None:
        assert _has_check(DailyEntry, "census_non_negative")
        assert _has_check(DailyEntry, "open_shifts_non_negative")

    def test_site_id_fk_restricts_deletion(self) -> None:
        # Can't delete a site that has daily entries — protects historical truth.
        col = DailyEntry.__table__.columns["site_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].ondelete == "RESTRICT"

    def test_entered_by_upn_is_tier_b(self) -> None:
        c = DailyEntry.__table__.columns["entered_by_upn"]
        assert c.info.get("data_class") == "B"

    @pytest.mark.parametrize(
        "col",
        [
            "id",
            "site_id",
            "entry_date",
            "census",
            "open_shifts",
            "source",
            "pdf_sha256",
            "notes",
        ],
    )
    def test_aggregate_columns_are_tier_a(self, col: str) -> None:
        assert DailyEntry.__table__.columns[col].info.get("data_class") == "A"


# ---------- Auth: census_credentials ----------


class TestCensusCredential:
    def test_schema_is_auth(self) -> None:
        assert CensusCredential.__table__.schema == "auth"

    def test_single_row_check_pinned(self) -> None:
        # Locks the single-row table invariant — only one credential record
        # exists for the entire portal.
        assert _has_check(CensusCredential, "single_row")

    def test_attempts_non_negative_check(self) -> None:
        assert _has_check(CensusCredential, "attempts_non_negative")

    def test_email_unique(self) -> None:
        assert _has_unique(CensusCredential, "uq_census_credentials_email")

    def test_email_and_password_hash_are_tier_b(self) -> None:
        # Directory / workforce data.
        assert CensusCredential.__table__.columns["email"].info.get("data_class") == "B"
        assert (
            CensusCredential.__table__.columns["password_hash"].info.get("data_class") == "B"
        )

    @pytest.mark.parametrize(
        "col",
        [
            "id",
            "active_session_token",
            "active_session_expires_at",
            "failed_attempts",
            "locked_until",
        ],
    )
    def test_session_state_columns_are_tier_a(self, col: str) -> None:
        assert CensusCredential.__table__.columns[col].info.get("data_class") == "A"

    def test_password_hash_is_not_null(self) -> None:
        # A row without a hash would lock the portal out — defensive pin.
        assert CensusCredential.__table__.columns["password_hash"].nullable is False
