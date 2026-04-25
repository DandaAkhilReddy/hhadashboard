"""Weekly HR / pipeline manual-entry model.

Andrea (owner_hr) enters this each week. Single row per week_ending — HR
metrics are HHA-wide (not split by state). Once ADP API integration lands
this becomes the fallback path; it stays valid forever as a manual override.

Per ADR-001: every column is Tier A (counts/percentages) except entered_by_upn
(Tier B — directory). No PHI.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Date,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, DataClass, TimestampMixin

A = DataClass.A.value
B = DataClass.B.value


class WeeklyHrManual(Base, TimestampMixin):
    """One row per week_ending. Re-saving the same week overwrites in place."""

    __tablename__ = "weekly_hr_manual"
    __table_args__ = (
        UniqueConstraint("week_ending", name="one_hr_per_week"),
        CheckConstraint("headcount_w2 >= 0", name="headcount_w2_non_negative"),
        CheckConstraint("headcount_1099 >= 0", name="headcount_1099_non_negative"),
        CheckConstraint("open_positions_total >= 0", name="open_positions_non_negative"),
        CheckConstraint(
            "terminations_90d_count >= 0", name="terminations_non_negative"
        ),
        CheckConstraint("below_fmv_count >= 0", name="below_fmv_non_negative"),
        Index("ix_weekly_hr_week_ending", "week_ending"),
        {"schema": "entries"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, info={"data_class": A})
    week_ending: Mapped[date] = mapped_column(Date, nullable=False, info={"data_class": A})

    headcount_w2: Mapped[int] = mapped_column(Integer, nullable=False, info={"data_class": A})
    headcount_1099: Mapped[int] = mapped_column(
        Integer, nullable=False, info={"data_class": A}
    )
    open_positions_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, info={"data_class": A}
    )
    terminations_90d_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, info={"data_class": A}
    )
    below_fmv_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, info={"data_class": A}
    )

    notes: Mapped[str | None] = mapped_column(Text, info={"data_class": A})

    entered_by_upn: Mapped[str] = mapped_column(
        String(200), nullable=False, info={"data_class": B}
    )
