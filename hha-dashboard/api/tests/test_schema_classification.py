"""HIPAA data classification CI guard.

Enforces ADR-001 invariants at CI time:

1. No column may have data_class == "C" (PHI / LDS)
2. Every column must declare info["data_class"]
3. No forbidden column names (claim_id, patient_*, mrn, etc.)
4. data_class values are valid (A/B/C/D only)

If any of these fail, the PR cannot merge. Period.
See docs/adr/001-hipaa-data-classification.md.
"""

from __future__ import annotations

# Import every model module here so its tables register on Base.metadata.
# As new model files are added, import them below.
from app.models import audit, entries, masters, uploads  # noqa: F401
from app.models.base import Base, DataClass

VALID_DATA_CLASSES = {c.value for c in DataClass}

FORBIDDEN_COLUMN_NAMES = {
    # Claim / encounter identifiers
    "claim_id",
    "encounter_id",
    # Date-of-service at claim/encounter grain
    "dos",
    "dos_per_line",
    "service_date",
    # Service codes at the line level
    "cpt_per_line",
    "hcpcs_per_line",
    "icd_per_line",
    # Patient identifiers (any form)
    "patient_name",
    "patient_dob",
    "patient_id",
    "patient_mrn",
    "mrn",
    # Insurance identifiers that can re-identify
    "member_id",
    "subscriber_id",
    "subscriber_name",
    "guarantor_id",
    "guarantor_name",
    "policy_number",
}


def test_no_columns_with_data_class_c() -> None:
    """No column may be tier C (PHI) — PHI must never persist to Postgres."""
    violations = [
        f"{table.fullname}.{col.name}"
        for table in Base.metadata.tables.values()
        for col in table.columns
        if col.info.get("data_class") == DataClass.C.value
    ]
    assert not violations, (
        f"ADR-001 violation: columns marked data_class='C' (PHI) found: {violations}. "
        "PHI/LDS data is never persisted — aggregate at ingestion edge. "
        "See docs/adr/001-hipaa-data-classification.md."
    )


def test_every_column_has_data_class() -> None:
    """Every column must declare data_class info."""
    missing = [
        f"{table.fullname}.{col.name}"
        for table in Base.metadata.tables.values()
        for col in table.columns
        if "data_class" not in col.info
    ]
    assert not missing, (
        f"Columns missing data_class tag: {missing}. "
        'Every column must have info={"data_class": "A"|"B"|"C"|"D"}. '
        "See docs/adr/001-hipaa-data-classification.md."
    )


def test_no_forbidden_column_names() -> None:
    """Forbidden column names are rejected — these names must never appear."""
    violations = [
        f"{table.fullname}.{col.name}"
        for table in Base.metadata.tables.values()
        for col in table.columns
        if col.name in FORBIDDEN_COLUMN_NAMES
    ]
    assert not violations, (
        f"Forbidden column names found: {violations}. "
        "These names are banned per ADR-001 — they indicate PHI-level data "
        "attempting to enter the schema. Aggregate at the ingestion edge."
    )


def test_data_class_values_are_valid() -> None:
    """data_class must be one of A, B, C, D."""
    invalid = [
        f"{table.fullname}.{col.name}={dc!r}"
        for table in Base.metadata.tables.values()
        for col in table.columns
        if (dc := col.info.get("data_class")) is not None and dc not in VALID_DATA_CLASSES
    ]
    assert not invalid, (
        f"Invalid data_class values: {invalid}. "
        f"Must be one of {sorted(VALID_DATA_CLASSES)}."
    )


def test_schema_has_expected_tables() -> None:
    """Sanity check — all expected tables exist across all schemas."""
    expected = {
        # masters (Session 1)
        "masters.sites",
        "masters.contracts",
        "masters.physicians",
        "masters.comp_agreements",
        "masters.credentials",
        "masters.site_coverage",
        # Session 3 additions
        "entries.daily_entries",
        "audit.audit_log",
        "uploads.upload_log",
    }
    actual = {t.fullname for t in Base.metadata.tables.values()}
    missing = expected - actual
    assert not missing, f"Expected tables missing from metadata: {missing}"
