"""Ventra pre-aggregated fact-table models per ADR-006.

Mirrors migration 0011 verbatim — three Tier-A fact tables in schema
``entries`` receiving daily pre-aggregated CSVs from Ventra:

  FactCollectionsDaily         — (date, facility_no, payer_class)
  FactArSnapshot                — (snapshot_date, facility_no, aging_bucket)
  FactRevenueByPhysicianMo      — (month, physician_npi, facility_no)

All columns are ``data_class=A`` — pre-aggregated by Ventra at source, no
patient or claim linkage by construction. The CI test
``test_schema_classification.py`` keeps it that way.

``source_system`` and ``state`` are intentionally NOT mutable from client
code — the DB CHECK constraints + DEFAULTs from migration 0011 lock them
to ``'VENTRA_FL_ATHENA'`` and ``'FL'`` respectively. The C12 writer never
passes those values; the DEFAULT kicks in on INSERT. The DB CHECK protects
against malicious INSERTs and configuration drift.

``ingest_run_id`` is the UUID of the ops.ingest_run row that wrote this
fact-table row. No FK constraint (the ops schema is independently
evolvable per migration 0012's rationale) — population is enforced at
the writer layer in ``jobs/ventra_ingest/ingest.py``.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, DataClass, TimestampMixin

A = DataClass.A.value


class FactCollectionsDaily(Base, TimestampMixin):
    """One row per (date, facility_no, payer_class). Daily grain from Ventra.

    Idempotent upsert key: ``uq_collections_daily_natural``. Re-running
    the ingest for the same drop overwrites mutable columns in place.
    """

    __tablename__ = "fact_collections_daily"
    __table_args__ = (
        UniqueConstraint(
            "date", "facility_no", "payer_class",
            name="uq_collections_daily_natural",
        ),
        CheckConstraint(
            "payer_class IN ('commercial', 'medicare', 'medicaid', 'selfpay', 'other')",
            name="collections_payer_class_valid",
        ),
        CheckConstraint("gross_charges >= 0", name="collections_gross_charges_non_negative"),
        CheckConstraint(
            "payments_received >= 0",
            name="collections_payments_received_non_negative",
        ),
        CheckConstraint(
            "source_system = 'VENTRA_FL_ATHENA'",
            name="collections_source_system_locked",
        ),
        CheckConstraint("state = 'FL'", name="collections_state_fl_only"),
        Index("ix_fact_collections_daily_date", "date"),
        Index("ix_fact_collections_daily_facility", "facility_no"),
        Index("ix_fact_collections_daily_ingest_run", "ingest_run_id"),
        {"schema": "entries"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, info={"data_class": A})
    date: Mapped[date] = mapped_column(Date, nullable=False, info={"data_class": A})
    facility_no: Mapped[int] = mapped_column(Integer, nullable=False, info={"data_class": A})
    payer_class: Mapped[str] = mapped_column(
        String(20), nullable=False, info={"data_class": A}
    )

    gross_charges: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, info={"data_class": A}
    )
    payments_received: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, info={"data_class": A}
    )
    contractual_adjustments: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal(0), info={"data_class": A}
    )
    write_offs: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal(0), info={"data_class": A}
    )
    payer_refunds: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal(0), info={"data_class": A}
    )
    patient_refunds: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal(0), info={"data_class": A}
    )
    net_revenue: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, info={"data_class": A}
    )

    # Server-default-driven invariants — NEVER passed by client code.
    source_system: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="VENTRA_FL_ATHENA",
        info={"data_class": A},
    )
    state: Mapped[str] = mapped_column(
        String(2), nullable=False, server_default="FL", info={"data_class": A}
    )

    ingest_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, info={"data_class": A}
    )


class FactArSnapshot(Base, TimestampMixin):
    """One row per (snapshot_date, facility_no, aging_bucket). Daily snapshot.

    Only the ``credit`` bucket may carry a negative outstanding_amount —
    enforced at DB level by ``ar_outstanding_non_negative_except_credit``.
    """

    __tablename__ = "fact_ar_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_date", "facility_no", "aging_bucket",
            name="uq_ar_snapshot_natural",
        ),
        CheckConstraint(
            "aging_bucket IN ('0-30', '31-60', '61-90', '91-120', '120+', 'credit')",
            name="ar_aging_bucket_valid",
        ),
        CheckConstraint(
            "aging_bucket = 'credit' OR outstanding_amount >= 0",
            name="ar_outstanding_non_negative_except_credit",
        ),
        CheckConstraint(
            "source_system = 'VENTRA_FL_ATHENA'",
            name="ar_source_system_locked",
        ),
        CheckConstraint("state = 'FL'", name="ar_state_fl_only"),
        Index("ix_fact_ar_snapshot_date", "snapshot_date"),
        Index("ix_fact_ar_snapshot_facility", "facility_no"),
        Index("ix_fact_ar_snapshot_ingest_run", "ingest_run_id"),
        {"schema": "entries"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, info={"data_class": A})
    snapshot_date: Mapped[date] = mapped_column(
        Date, nullable=False, info={"data_class": A}
    )
    facility_no: Mapped[int] = mapped_column(Integer, nullable=False, info={"data_class": A})
    aging_bucket: Mapped[str] = mapped_column(
        String(10), nullable=False, info={"data_class": A}
    )
    outstanding_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, info={"data_class": A}
    )

    source_system: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="VENTRA_FL_ATHENA",
        info={"data_class": A},
    )
    state: Mapped[str] = mapped_column(
        String(2), nullable=False, server_default="FL", info={"data_class": A}
    )

    ingest_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, info={"data_class": A}
    )


class FactRevenueByPhysicianMo(Base, TimestampMixin):
    """One row per (month, physician_npi, facility_no). Monthly grain.

    Emitted only on month-close drops (typically the 1st-3rd of each
    month, covering the prior month). ``month`` is the first-of-month
    date; vendor may emit prior-month or restated months on any drop.
    """

    __tablename__ = "fact_revenue_by_physician_mo"
    __table_args__ = (
        UniqueConstraint(
            "month", "physician_npi", "facility_no",
            name="uq_revenue_physician_mo_natural",
        ),
        CheckConstraint(
            "physician_npi ~ '^[0-9]{10}$'",
            name="physician_mo_npi_10_digit",
        ),
        CheckConstraint(
            "month = date_trunc('month', month)::date",
            name="physician_mo_month_is_first_of_month",
        ),
        CheckConstraint(
            "encounters_count >= 0",
            name="physician_mo_encounters_non_negative",
        ),
        CheckConstraint(
            "total_rvu >= 0", name="physician_mo_total_rvu_non_negative"
        ),
        CheckConstraint(
            "total_work_rvu >= 0",
            name="physician_mo_total_work_rvu_non_negative",
        ),
        CheckConstraint(
            "source_system = 'VENTRA_FL_ATHENA'",
            name="physician_mo_source_system_locked",
        ),
        CheckConstraint("state = 'FL'", name="physician_mo_state_fl_only"),
        Index("ix_fact_physician_mo_month", "month"),
        Index("ix_fact_physician_mo_npi", "physician_npi"),
        Index("ix_fact_physician_mo_ingest_run", "ingest_run_id"),
        {"schema": "entries"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, info={"data_class": A})
    month: Mapped[date] = mapped_column(Date, nullable=False, info={"data_class": A})
    physician_npi: Mapped[str] = mapped_column(
        String(10), nullable=False, info={"data_class": A}
    )
    facility_no: Mapped[int] = mapped_column(Integer, nullable=False, info={"data_class": A})
    encounters_count: Mapped[int] = mapped_column(
        Integer, nullable=False, info={"data_class": A}
    )
    total_rvu: Mapped[Decimal] = mapped_column(
        Numeric(9, 2), nullable=False, default=Decimal(0), info={"data_class": A}
    )
    total_work_rvu: Mapped[Decimal] = mapped_column(
        Numeric(9, 2), nullable=False, default=Decimal(0), info={"data_class": A}
    )
    revenue_attributed: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, info={"data_class": A}
    )

    source_system: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="VENTRA_FL_ATHENA",
        info={"data_class": A},
    )
    state: Mapped[str] = mapped_column(
        String(2), nullable=False, server_default="FL", info={"data_class": A}
    )

    ingest_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, info={"data_class": A}
    )


__all__ = [
    "FactArSnapshot",
    "FactCollectionsDaily",
    "FactRevenueByPhysicianMo",
]
