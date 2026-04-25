"""Weekly clinical-quality manual-entry model.

Dr. Aneja and Dr. Reddy (owner_clinical) audit a sample of charts each week
and enter the rollup numbers. Per-state because LOS varies between FL and TX
and the H&P/DC compliance rates are reported per book.

Per ADR-001: all columns are Tier A (aggregate %s, count, average days). No
patient identifiers, no chart-level data.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, DataClass, TimestampMixin

A = DataClass.A.value
B = DataClass.B.value


class WeeklyClinical(Base, TimestampMixin):
    """One row per (week_ending, state). Idempotent — re-saving overwrites."""

    __tablename__ = "weekly_clinical"
    __table_args__ = (
        UniqueConstraint(
            "week_ending", "state", name="one_clinical_per_week_per_state"
        ),
        CheckConstraint("state IN ('FL', 'TX')", name="state_valid"),
        CheckConstraint(
            "hp_24h_pct BETWEEN 0 AND 100", name="hp_24h_pct_in_range"
        ),
        CheckConstraint(
            "dc_48h_pct BETWEEN 0 AND 100", name="dc_48h_pct_in_range"
        ),
        CheckConstraint("avg_los_days >= 0", name="avg_los_non_negative"),
        CheckConstraint("avg_los_days <= 60", name="avg_los_sanity_cap"),
        CheckConstraint(
            "charts_audited_count >= 0", name="charts_audited_non_negative"
        ),
        Index("ix_weekly_clinical_week_ending", "week_ending"),
        Index("ix_weekly_clinical_state", "state"),
        {"schema": "entries"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, info={"data_class": A})
    week_ending: Mapped[date] = mapped_column(Date, nullable=False, info={"data_class": A})
    state: Mapped[str] = mapped_column(String(2), nullable=False, info={"data_class": A})

    # Compliance rates (entered as percentages 0-100)
    hp_24h_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, info={"data_class": A}
    )
    dc_48h_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, info={"data_class": A}
    )

    # Length of stay + audit volume
    avg_los_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, info={"data_class": A}
    )
    charts_audited_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, info={"data_class": A}
    )

    # Free-text rollup (e.g. "Woodmont still flagged — LOS 5.8d, +0.4 over 4 weeks")
    notes: Mapped[str | None] = mapped_column(Text, info={"data_class": A})

    entered_by_upn: Mapped[str] = mapped_column(
        String(200), nullable=False, info={"data_class": B}
    )
