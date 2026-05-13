"""Read-side Pydantic schemas for the Ventra pre-aggregated fact tables.

One ``*Out`` model per fact table, plus an ``Envelope`` wrapper that
carries result-set metadata (count, requested filters) alongside the
rows. Routers in ``finance_ventra.py`` return these directly.

All columns are Tier-A per ADR-001 by construction. The vendor
``source_system`` column on the SQLAlchemy model is always
``'VENTRA_FL_ATHENA'`` (DB CHECK locked) — we don't expose it in the
out-schema because every row carries the same value.
"""

from __future__ import annotations

import uuid
from datetime import date as date_t
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class CollectionsRowOut(BaseModel):
    """One row of ``entries.fact_collections_daily``."""

    model_config = ConfigDict(from_attributes=True)

    date: date_t
    facility_no: int
    payer_class: str
    gross_charges: Decimal
    payments_received: Decimal
    contractual_adjustments: Decimal
    write_offs: Decimal
    payer_refunds: Decimal
    patient_refunds: Decimal
    net_revenue: Decimal
    ingest_run_id: uuid.UUID
    updated_at: datetime


class ArSnapshotRowOut(BaseModel):
    """One row of ``entries.fact_ar_snapshot``."""

    model_config = ConfigDict(from_attributes=True)

    snapshot_date: date_t
    facility_no: int
    aging_bucket: str
    outstanding_amount: Decimal
    ingest_run_id: uuid.UUID
    updated_at: datetime


class PhysicianMonthlyRowOut(BaseModel):
    """One row of ``entries.fact_revenue_by_physician_mo``."""

    model_config = ConfigDict(from_attributes=True)

    month: date_t
    physician_npi: str
    facility_no: int
    encounters_count: int
    total_rvu: Decimal
    total_work_rvu: Decimal
    revenue_attributed: Decimal
    ingest_run_id: uuid.UUID
    updated_at: datetime


class Envelope[T: BaseModel](BaseModel):
    """Standard list-response envelope: count + rows.

    Future-proofs the response shape so adding cursor pagination or
    aggregate metadata in a follow-up does not break consumers."""

    count: int
    rows: list[T]
