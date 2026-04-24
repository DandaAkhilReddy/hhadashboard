"""Entries schema — manual user-entered numbers.

Per ADR-001: all columns are Tier A (aggregate) or Tier B (directory / HR).
No PHI. Census counts are integers; no patient identifiers.
"""

from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, DataClass, TimestampMixin

A = DataClass.A.value
B = DataClass.B.value


class DailyEntry(Base, TimestampMixin):
    """One row per site per day. Typed in by owner_ops (Crystal) via /entry/daily-census.

    Idempotent via UNIQUE(site_id, entry_date) — re-submitting the same day's count
    overwrites the previous value (the service layer does the upsert).

    `source` tells you whether Crystal typed it or the system extracted it from a PDF.
    `pdf_sha256` is a hash of the source PDF (if any) — proves provenance without
    persisting the PDF itself. It is NOT a patient identifier (it's a hash of an
    entire file containing aggregate data) → Tier A.
    """

    __tablename__ = "daily_entries"
    __table_args__ = (
        UniqueConstraint("site_id", "entry_date", name="one_entry_per_site_per_day"),
        CheckConstraint("census >= 0", name="census_non_negative"),
        CheckConstraint("open_shifts >= 0", name="open_shifts_non_negative"),
        {"schema": "entries"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, info={"data_class": A})
    site_id: Mapped[int] = mapped_column(
        ForeignKey("masters.sites.id", ondelete="RESTRICT"),
        nullable=False,
        info={"data_class": A},
    )
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, info={"data_class": A})
    census: Mapped[int] = mapped_column(Integer, nullable=False, info={"data_class": A})
    open_shifts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, info={"data_class": A}
    )
    entered_by_upn: Mapped[str] = mapped_column(String(200), nullable=False, info={"data_class": B})
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manual", info={"data_class": A}
    )  # 'manual' | 'pdf_extract'
    pdf_sha256: Mapped[str | None] = mapped_column(String(64), info={"data_class": A})
    notes: Mapped[str | None] = mapped_column(Text, info={"data_class": A})
