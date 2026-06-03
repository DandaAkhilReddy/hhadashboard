"""Ventra fact-table models — dual-source (Phase 4 hybrid).

Mirrors migrations 0011 + 0013 — three Tier-A fact tables in schema
``entries`` receiving aggregated data from two parallel Ventra pipelines:

  FactCollectionsDaily         — (date, facility_no, payer_class, source_system)
  FactArSnapshot                — (snapshot_date, facility_no, aging_bucket, source_system)
  FactRevenueByPhysicianMo      — (month, physician_npi, facility_no, source_system)

``source_system`` carries the provenance tag:

  ``VENTRA_FL_PREAGG``        — Ventra's pre-aggregated extract (ADR-006).
  ``VENTRA_FL_STDSPEC_AGG``   — HHA's in-memory aggregation of Ventra's
                                row-level Standard Data Extract. PHI is
                                stripped at the parser layer (V15); only
                                Tier-A aggregates ever reach this table.

The dual CHECK constraint (``*_source_system_dual``) accepts either value
and rejects everything else. The natural-key UNIQUE constraint is widened
to include ``source_system`` so both pipelines coexist per tuple — the
reconciliation job in ``jobs/ventra_reconcile/`` joins on the original
natural key minus source_system.

All columns are ``data_class=A`` — pre-aggregated by construction; no
patient or claim linkage by either pipeline. The CI test
``test_schema_classification.py`` keeps it that way. Per ADR-001 the
stdspec path enforces this at four layers (V15 forbidden-column denial
before strip, after strip, at telemetry export, and at DB write).

``state`` is locked to ``'FL'`` by DB DEFAULT + CHECK — both pipelines
are FL-only (ADR-005). The application code never sets it.

``source_system`` is intentionally set by app code (no server_default) so
the stdspec writer must pass ``VENTRA_FL_STDSPEC_AGG`` explicitly and the
preagg writer must pass ``VENTRA_FL_PREAGG`` explicitly. Forcing the
explicit set prevents a silent default-wins bug if either path is
misconfigured.

``ingest_run_id`` is the UUID of the ops.ingest_run row that wrote this
fact-table row. No FK constraint (the ops schema is independently
evolvable per migration 0012's rationale) — population is enforced at
the writer layer in each pipeline's ``ingest.py``.
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
            "date", "facility_no", "payer_class", "source_system",
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
            "source_system IN ('VENTRA_FL_PREAGG', 'VENTRA_FL_STDSPEC_AGG')",
            name="collections_source_system_dual",
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

    # Provenance tag — explicitly set per pipeline. No server_default; the
    # writer MUST pass either 'VENTRA_FL_PREAGG' or 'VENTRA_FL_STDSPEC_AGG'.
    source_system: Mapped[str] = mapped_column(
        String(30), nullable=False, info={"data_class": A},
    )
    # State stays server-default-locked; both pipelines are FL-only (ADR-005).
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
            "snapshot_date", "facility_no", "aging_bucket", "source_system",
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
            "source_system IN ('VENTRA_FL_PREAGG', 'VENTRA_FL_STDSPEC_AGG')",
            name="ar_source_system_dual",
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
        String(30), nullable=False, info={"data_class": A},
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
            "month", "physician_npi", "facility_no", "source_system",
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
            "source_system IN ('VENTRA_FL_PREAGG', 'VENTRA_FL_STDSPEC_AGG')",
            name="physician_mo_source_system_dual",
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
        String(30), nullable=False, info={"data_class": A},
    )
    state: Mapped[str] = mapped_column(
        String(2), nullable=False, server_default="FL", info={"data_class": A}
    )

    ingest_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, info={"data_class": A}
    )


# Provenance values — exported for app code to use without string typos.
SOURCE_PREAGG = "VENTRA_FL_PREAGG"
SOURCE_STDSPEC = "VENTRA_FL_STDSPEC_AGG"

__all__ = [
    "SOURCE_PREAGG",
    "SOURCE_STDSPEC",
    "FactArSnapshot",
    "FactCollectionsDaily",
    "FactRevenueByPhysicianMo",
]
