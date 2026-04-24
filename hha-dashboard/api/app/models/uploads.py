"""Uploads schema — the cron job's work queue.

Every row represents one file uploaded by a user. The upload_ingest cron
claims rows via `SELECT ... FOR UPDATE SKIP LOCKED WHERE status='uploaded'`,
processes them, and flips status to `processed` or `error`.

Per ADR-001: all columns are Tier A (metadata) or Tier B (UPN). No PHI.
Filenames are free-text but never contain patient identifiers by convention
— see hipaa checklist in the PR template. A malformed filename doesn't
violate ADR-001 on its own; it's only a concern if someone puts PHI in it.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base, DataClass

A = DataClass.A.value
B = DataClass.B.value


class UploadLog(Base):
    """One row per uploaded file. The cron job's queue + audit trail."""

    __tablename__ = "upload_log"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded', 'processing', 'processed', 'error', 'expired')",
            name="status_valid",
        ),
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
        CheckConstraint("retry_count >= 0", name="retry_count_non_negative"),
        Index("ix_upload_log_status_uploaded_at", "status", "uploaded_at"),
        Index("ix_upload_log_uploaded_by_upn", "uploaded_by_upn"),
        {"schema": "uploads"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, info={"data_class": A})
    uploaded_by_upn: Mapped[str] = mapped_column(
        String(200), nullable=False, info={"data_class": B}
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        info={"data_class": A},
    )
    file_type: Mapped[str] = mapped_column(String(30), nullable=False, info={"data_class": A})
    # file_type values: 'census_pdf' | 'finance_xlsx' | 'clinical_xlsx' | 'hr_xlsx' | 'unknown'
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False, info={"data_class": A})
    blob_name: Mapped[str] = mapped_column(String(1000), nullable=False, info={"data_class": A})
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, info={"data_class": A})
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, info={"data_class": A})
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="uploaded", info={"data_class": A}
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), info={"data_class": A}
    )
    processing_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), info={"data_class": A}
    )
    rows_written: Mapped[int | None] = mapped_column(Integer, info={"data_class": A})
    error_message: Mapped[str | None] = mapped_column(Text, info={"data_class": A})
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, info={"data_class": A}
    )
