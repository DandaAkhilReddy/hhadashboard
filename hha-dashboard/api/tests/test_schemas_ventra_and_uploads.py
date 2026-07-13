"""Unit tests for Ventra fact + uploads response schemas.

Covers:
- ``ventra_facts``: CollectionsRowOut, ArSnapshotRowOut,
  PhysicianMonthlyRowOut, Envelope[T] generic wrapper
- ``uploads``: FileType + UploadStatus StrEnums, UploadOut,
  UploadAcceptedOut

Pure Pydantic — no DB, no FastAPI. Pins the ORM-hydration path
(``from_attributes=True``) plus the StrEnum value catalogs that the
frontend's typed types depend on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.uploads import (
    FileType,
    UploadAcceptedOut,
    UploadOut,
    UploadStatus,
)
from app.schemas.ventra_facts import (
    ArSnapshotRowOut,
    CollectionsRowOut,
    Envelope,
    PhysicianMonthlyRowOut,
)

# ============================================================================
# uploads.py — StrEnum catalogs
# ============================================================================


class TestFileTypeEnum:
    def test_locks_five_legal_values(self) -> None:
        # The frontend's `FileType` TypeScript Literal must stay in sync
        # with this set.
        assert {m.value for m in FileType} == {
            "census_pdf",
            "finance_xlsx",
            "clinical_xlsx",
            "hr_xlsx",
            "unknown",
        }

    def test_str_enum_members_are_strings(self) -> None:
        # StrEnum members compare equal to their underlying str value —
        # callers use this pattern when checking against route params.
        assert FileType.CENSUS_PDF == "census_pdf"
        assert FileType.UNKNOWN == "unknown"


class TestUploadStatusEnum:
    def test_locks_five_legal_lifecycle_values(self) -> None:
        # Mirrors the DB CHECK on uploads.upload_log.status_valid; the
        # UploadDropZone STATUS_LABEL dict has the same 5 keys.
        assert {m.value for m in UploadStatus} == {
            "uploaded",
            "processing",
            "processed",
            "error",
            "expired",
        }


# ============================================================================
# uploads.py — Out models
# ============================================================================


def _upload_row(**overrides) -> dict:
    base = {
        "id": 1,
        "uploaded_by_upn": "crystal@hha.com",
        "uploaded_at": datetime(2026, 5, 17, 15, tzinfo=UTC),
        "file_type": "census_pdf",
        "original_filename": "census-2026-05-17.pdf",
        "blob_name": "uploads/1.pdf",
        "size_bytes": 2_048_000,
        "sha256": "a" * 64,
        "status": "uploaded",
        "processing_started_at": None,
        "processing_finished_at": None,
        "rows_written": None,
        "error_message": None,
        "retry_count": 0,
    }
    return {**base, **overrides}


class TestUploadOut:
    def test_accepts_minimum_required(self) -> None:
        row = UploadOut(**_upload_row())
        assert row.id == 1
        assert row.status == "uploaded"

    def test_accepts_terminal_processed_state(self) -> None:
        row = UploadOut(
            **_upload_row(
                status="processed",
                processing_started_at=datetime(2026, 5, 17, 15, 0, tzinfo=UTC),
                processing_finished_at=datetime(2026, 5, 17, 15, 0, 14, tzinfo=UTC),
                rows_written=11,
            )
        )
        assert row.rows_written == 11
        assert row.processing_finished_at is not None

    def test_accepts_terminal_error_state_with_message(self) -> None:
        row = UploadOut(
            **_upload_row(
                status="error",
                processing_started_at=datetime(2026, 5, 17, 15, 0, tzinfo=UTC),
                processing_finished_at=datetime(2026, 5, 17, 15, 0, 5, tzinfo=UTC),
                error_message="No site/census matches found",
                retry_count=3,
            )
        )
        assert row.error_message == "No site/census matches found"
        assert row.retry_count == 3

    def test_missing_required_id_raises(self) -> None:
        payload = _upload_row()
        del payload["id"]
        with pytest.raises(ValidationError, match="id"):
            UploadOut(**payload)

    def test_missing_required_uploaded_by_upn_raises(self) -> None:
        payload = _upload_row()
        del payload["uploaded_by_upn"]
        with pytest.raises(ValidationError, match="uploaded_by_upn"):
            UploadOut(**payload)

    def test_hydrates_from_orm_attributes(self) -> None:
        """``from_attributes=True`` lets routers return an ORM row
        directly — exercise that path."""

        class _FakeOrmRow:
            id = 42
            uploaded_by_upn = "akhil@hha.com"
            uploaded_at = datetime(2026, 5, 17, 12, tzinfo=UTC)
            file_type = "finance_xlsx"
            original_filename = "april-collections.xlsx"
            blob_name = "uploads/42.xlsx"
            size_bytes = 4096
            sha256 = "b" * 64
            status = "processed"
            processing_started_at = None
            processing_finished_at = None
            rows_written = 2
            error_message = None
            retry_count = 0

        row = UploadOut.model_validate(_FakeOrmRow())
        assert row.id == 42
        assert row.file_type == "finance_xlsx"


class TestUploadAcceptedOut:
    def test_default_message(self) -> None:
        out = UploadAcceptedOut(id=42, status="uploaded", file_type="census_pdf")
        assert out.message == "Upload accepted. Will be processed within 15 minutes."

    def test_custom_message_override(self) -> None:
        out = UploadAcceptedOut(
            id=42,
            status="uploaded",
            file_type="census_pdf",
            message="custom",
        )
        assert out.message == "custom"

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(ValidationError, match="status"):
            UploadAcceptedOut(id=42, file_type="census_pdf")  # type: ignore[call-arg]


# ============================================================================
# ventra_facts.py — CollectionsRowOut
# ============================================================================


def _collections_payload(**overrides) -> dict:
    base = {
        "date": date(2026, 5, 17),
        "facility_no": 1,
        "payer_class": "commercial",
        "gross_charges": Decimal("100000.00"),
        "payments_received": Decimal("60000.00"),
        "contractual_adjustments": Decimal("30000.00"),
        "write_offs": Decimal("5000.00"),
        "payer_refunds": Decimal("0"),
        "patient_refunds": Decimal("100"),
        "net_revenue": Decimal("64900.00"),
        "ingest_run_id": uuid.uuid4(),
        "updated_at": datetime(2026, 5, 17, 8, tzinfo=UTC),
    }
    return {**base, **overrides}


class TestCollectionsRowOut:
    def test_accepts_minimum_required(self) -> None:
        row = CollectionsRowOut(**_collections_payload())
        assert row.facility_no == 1
        assert isinstance(row.ingest_run_id, uuid.UUID)

    def test_missing_required_field_raises(self) -> None:
        payload = _collections_payload()
        del payload["net_revenue"]
        with pytest.raises(ValidationError, match="net_revenue"):
            CollectionsRowOut(**payload)

    def test_rejects_non_uuid_ingest_run_id(self) -> None:
        with pytest.raises(ValidationError, match="ingest_run_id"):
            CollectionsRowOut(**_collections_payload(ingest_run_id="not-a-uuid"))

    def test_decimal_fields_preserve_precision(self) -> None:
        row = CollectionsRowOut(
            **_collections_payload(net_revenue=Decimal("64900.12"))
        )
        # Pydantic keeps the original Decimal value.
        assert row.net_revenue == Decimal("64900.12")

    def test_hydrates_from_orm_attributes(self) -> None:
        run_id = uuid.uuid4()

        class _FakeRow:
            date = date(2026, 5, 17)
            facility_no = 1
            payer_class = "medicare"
            gross_charges = Decimal("50000")
            payments_received = Decimal("30000")
            contractual_adjustments = Decimal("15000")
            write_offs = Decimal("1000")
            payer_refunds = Decimal("0")
            patient_refunds = Decimal("0")
            net_revenue = Decimal("34000")
            ingest_run_id = run_id
            updated_at = datetime(2026, 5, 17, tzinfo=UTC)

        row = CollectionsRowOut.model_validate(_FakeRow())
        assert row.ingest_run_id == run_id
        assert row.payer_class == "medicare"


# ============================================================================
# ventra_facts.py — ArSnapshotRowOut
# ============================================================================


class TestArSnapshotRowOut:
    def test_accepts_minimum_required(self) -> None:
        row = ArSnapshotRowOut(
            snapshot_date=date(2026, 5, 17),
            facility_no=1,
            aging_bucket="0-30",
            outstanding_amount=Decimal("30000.00"),
            ingest_run_id=uuid.uuid4(),
            updated_at=datetime(2026, 5, 17, tzinfo=UTC),
        )
        assert row.aging_bucket == "0-30"

    def test_accepts_credit_bucket_with_negative_amount(self) -> None:
        # The DB CHECK allows negative on aging_bucket='credit'; the
        # response schema does not constrain.
        row = ArSnapshotRowOut(
            snapshot_date=date(2026, 5, 17),
            facility_no=1,
            aging_bucket="credit",
            outstanding_amount=Decimal("-500"),
            ingest_run_id=uuid.uuid4(),
            updated_at=datetime(2026, 5, 17, tzinfo=UTC),
        )
        assert row.outstanding_amount == Decimal("-500")

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(ValidationError, match="snapshot_date"):
            ArSnapshotRowOut(  # type: ignore[call-arg]
                facility_no=1,
                aging_bucket="0-30",
                outstanding_amount=Decimal("0"),
                ingest_run_id=uuid.uuid4(),
                updated_at=datetime(2026, 5, 17, tzinfo=UTC),
            )


# ============================================================================
# ventra_facts.py — PhysicianMonthlyRowOut
# ============================================================================


class TestPhysicianMonthlyRowOut:
    def test_accepts_minimum_required(self) -> None:
        row = PhysicianMonthlyRowOut(
            month=date(2026, 4, 1),
            physician_npi="1234567890",
            facility_no=1,
            encounters_count=120,
            total_rvu=Decimal("180.5"),
            total_work_rvu=Decimal("100.2"),
            revenue_attributed=Decimal("45000"),
            ingest_run_id=uuid.uuid4(),
            updated_at=datetime(2026, 5, 17, tzinfo=UTC),
        )
        assert row.physician_npi == "1234567890"
        assert row.encounters_count == 120

    def test_npi_kept_as_string_not_coerced_to_int(self) -> None:
        """NPI is 10-digit numeric but stored as str so leading zeros
        survive. Pydantic must preserve the str shape."""
        row = PhysicianMonthlyRowOut(
            month=date(2026, 4, 1),
            physician_npi="0123456789",
            facility_no=1,
            encounters_count=1,
            total_rvu=Decimal("1"),
            total_work_rvu=Decimal("1"),
            revenue_attributed=Decimal("100"),
            ingest_run_id=uuid.uuid4(),
            updated_at=datetime(2026, 5, 17, tzinfo=UTC),
        )
        assert row.physician_npi == "0123456789"
        assert isinstance(row.physician_npi, str)


# ============================================================================
# ventra_facts.py — Envelope[T] generic wrapper
# ============================================================================


class TestEnvelope:
    def test_wraps_collections_rows(self) -> None:
        row = CollectionsRowOut(**_collections_payload())
        env = Envelope[CollectionsRowOut](count=1, rows=[row])
        assert env.count == 1
        assert len(env.rows) == 1

    def test_wraps_empty_result_set(self) -> None:
        env = Envelope[CollectionsRowOut](count=0, rows=[])
        assert env.rows == []

    def test_count_can_diverge_from_rows_length_for_pagination(self) -> None:
        """``count`` is intended as the total, ``rows`` as a page —
        they're allowed to differ. Pin this contract."""
        env = Envelope[CollectionsRowOut](count=500, rows=[])
        assert env.count == 500

    def test_missing_count_raises(self) -> None:
        with pytest.raises(ValidationError, match="count"):
            Envelope[CollectionsRowOut](rows=[])  # type: ignore[call-arg]

    def test_round_trip_model_dump(self) -> None:
        run_id = uuid.uuid4()
        row = CollectionsRowOut(**_collections_payload(ingest_run_id=run_id))
        env = Envelope[CollectionsRowOut](count=1, rows=[row])
        dumped = env.model_dump()
        assert dumped["count"] == 1
        assert len(dumped["rows"]) == 1
