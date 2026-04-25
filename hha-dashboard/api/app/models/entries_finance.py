"""Monthly finance manual-entry model.

Sandy Collins (owner_finance) enters this every month for both states. FL is
a temporary fallback path until Ventra SFTP ingestion lands (Session 7+); TX
stays manual indefinitely per the FL-only Ventra scope decision (ADR-001 +
DASHBOARD_PLAN.md).

Per ADR-001: all dollar amounts are Tier A aggregates. No claim-level data,
no patient identifiers. The `source_system` column tags every row with its
provenance so the FL-vs-TX split is enforced at row level (never mix the
two books in one record).
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


class MonthlyFinanceManual(Base, TimestampMixin):
    """One row per (year, month, state). Idempotent via the unique constraint —
    re-saving the same period overwrites in place (the service layer upserts).

    `period_first` is a derived first-of-month date (e.g. 2026-04-01) so we can
    range-query without composing year + month every time.
    """

    __tablename__ = "monthly_finance_manual"
    __table_args__ = (
        UniqueConstraint("year", "month", "state", name="one_finance_per_month_per_state"),
        CheckConstraint("month BETWEEN 1 AND 12", name="month_valid"),
        CheckConstraint("year BETWEEN 2020 AND 2100", name="year_valid"),
        CheckConstraint("state IN ('FL', 'TX')", name="state_valid"),
        CheckConstraint(
            "source_system IN ('VENTRA_FL_FALLBACK', 'HHA_TX_MANUAL')",
            name="source_system_valid",
        ),
        CheckConstraint("collections_usd >= 0", name="collections_non_negative"),
        CheckConstraint("ar_total_usd >= 0", name="ar_total_non_negative"),
        CheckConstraint(
            "net_collection_rate_pct BETWEEN 0 AND 100",
            name="ncr_in_range",
        ),
        CheckConstraint("days_in_ar >= 0", name="days_in_ar_non_negative"),
        Index("ix_monthly_finance_year_month", "year", "month"),
        Index("ix_monthly_finance_state", "state"),
        {"schema": "entries"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, info={"data_class": A})
    year: Mapped[int] = mapped_column(Integer, nullable=False, info={"data_class": A})
    month: Mapped[int] = mapped_column(Integer, nullable=False, info={"data_class": A})
    period_first: Mapped[date] = mapped_column(Date, nullable=False, info={"data_class": A})
    state: Mapped[str] = mapped_column(String(2), nullable=False, info={"data_class": A})

    # Collections + revenue
    collections_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, info={"data_class": A}
    )
    ventra_fee_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=0, info={"data_class": A}
    )

    # AR aging — total + 5 buckets (must reconcile, but we don't enforce in DB)
    ar_total_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, info={"data_class": A}
    )
    ar_0_30_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=0, info={"data_class": A}
    )
    ar_31_60_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=0, info={"data_class": A}
    )
    ar_61_90_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=0, info={"data_class": A}
    )
    ar_91_120_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=0, info={"data_class": A}
    )
    ar_over_120_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=0, info={"data_class": A}
    )

    # KPIs (entered, not derived — Sandy types them from the Ventra report)
    net_collection_rate_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, info={"data_class": A}
    )
    days_in_ar: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, info={"data_class": A}
    )

    # Provenance
    source_system: Mapped[str] = mapped_column(
        String(30), nullable=False, info={"data_class": A}
    )  # 'VENTRA_FL_FALLBACK' | 'HHA_TX_MANUAL'
    entered_by_upn: Mapped[str] = mapped_column(
        String(200), nullable=False, info={"data_class": B}
    )
    notes: Mapped[str | None] = mapped_column(Text, info={"data_class": A})
