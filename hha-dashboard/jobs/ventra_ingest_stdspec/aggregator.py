"""In-memory aggregator — invoice rows -> 3 fact-table aggregate sets.

Streamed input from ``parsers.parse_invoice`` is fed one row at a time
into ``Aggregator.process_invoice_row``. Internal defaultdicts accumulate
by the natural keys of the three fact tables, then ``to_*_rows`` methods
emit immutable dataclass instances ready for the writer (H11).

Memory profile:
  - Bounded by the cardinality of (date, facility, payer) +
    (snapshot_date, facility, bucket) + (month, npi, facility), NOT by
    row count. For a year of FL data across 7 sites + ~50 physicians +
    5 payer classes:
      collections:   365 * 7 * 5    = 12,775 entries
      ar_snapshot:   1 * 7 * 6       =     42 entries
      physician_mo:  12 * 50 * 7     =  4,200 entries
    Total ~17k Decimal sums + counters. Trivial memory footprint.
  - Even on a multi-million-row month of claims, the accumulator stays
    bounded — only the keys grow, not the values.

PHI-safety contract:
  - The aggregator NEVER stores raw row content. Only the aggregation
    keys (already non-PHI after the parser's strip layer) and the
    Decimal sums + counters.
  - V15 layer 2 (post-strip assertion) runs on every row that arrives:
    if the InvoiceRow somehow carries a forbidden attribute (shouldn't
    be possible given Pydantic's model definition, but defensive),
    raise PHILeakError immediately.
  - Aggregate output dataclasses contain only the columns the fact tables
    accept. PHI cannot reach the writer through this layer.

Net-revenue formula (locked 2026-05-25 pending Ventra confirmation):
  net_revenue = payments_received - payer_refunds - patient_refunds

The CFO + Sandy Collins signed off on this formula for the working
session call. If Ventra's reply asks for a different definition, this
function is the single place to update — every downstream consumer
reads net_revenue from the aggregate, never recomputes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .exceptions import ValidationError
from .parsers import GuarantorRow, InvoiceRow
from .phi import assert_no_phi_columns

# ============================================================================
# Aggregate dataclasses — writer inputs
# ============================================================================


@dataclass(frozen=True, slots=True)
class CollectionsAggregate:
    """One row of fact_collections_daily.

    Natural key: (date, facility_no, payer_class). source_system is set
    by the writer to VENTRA_FL_STDSPEC_AGG; state is set by the DB
    default to FL.
    """

    date: date
    facility_no: int
    payer_class: str
    gross_charges: Decimal
    payments_received: Decimal
    contractual_adjustments: Decimal
    write_offs: Decimal
    payer_refunds: Decimal
    patient_refunds: Decimal
    net_revenue: Decimal


@dataclass(frozen=True, slots=True)
class ArSnapshotAggregate:
    """One row of fact_ar_snapshot.

    Natural key: (snapshot_date, facility_no, aging_bucket). snapshot_date
    is the drop_date (the day we processed the invoice file).
    """

    snapshot_date: date
    facility_no: int
    aging_bucket: str
    outstanding_amount: Decimal


@dataclass(frozen=True, slots=True)
class PhysicianMonthlyAggregate:
    """One row of fact_revenue_by_physician_mo.

    Natural key: (month, physician_npi, facility_no). ``month`` is the
    first-of-month for the invoice's service_date.
    """

    month: date
    physician_npi: str
    facility_no: int
    encounters_count: int
    total_rvu: Decimal
    total_work_rvu: Decimal
    revenue_attributed: Decimal


# ============================================================================
# Aging-bucket classifier
# ============================================================================


def classify_aging_bucket(days_since_service: int, outstanding_amount: Decimal) -> str:
    """Return the AR aging bucket label per the standard 30-day bands.

    The ``credit`` bucket catches negative outstanding amounts (payments
    that overshot the charge — patient refunds owed), regardless of
    days. Otherwise the band is selected by days_since_service.
    """
    if outstanding_amount < 0:
        return "credit"
    if days_since_service <= 30:
        return "0-30"
    if days_since_service <= 60:
        return "31-60"
    if days_since_service <= 90:
        return "61-90"
    if days_since_service <= 120:
        return "91-120"
    return "120+"


def _first_of_month(d: date) -> date:
    """Return the first-of-month date for ``d``.

    Matches the ``month = date_trunc('month', month)::date`` CHECK
    constraint on fact_revenue_by_physician_mo.
    """
    return date(d.year, d.month, 1)


# ============================================================================
# Aggregator
# ============================================================================


@dataclass(slots=True)
class _CollectionsAccumulator:
    """Mutable accumulator for one (date, facility, payer) group."""

    gross_charges: Decimal = Decimal(0)
    payments_received: Decimal = Decimal(0)
    contractual_adjustments: Decimal = Decimal(0)
    write_offs: Decimal = Decimal(0)
    payer_refunds: Decimal = Decimal(0)
    patient_refunds: Decimal = Decimal(0)


@dataclass(slots=True)
class _ArAccumulator:
    """Mutable accumulator for one (snapshot_date, facility, bucket) group."""

    outstanding_amount: Decimal = Decimal(0)


@dataclass(slots=True)
class _PhysicianAccumulator:
    """Mutable accumulator for one (month, npi, facility) group."""

    encounters_count: int = 0
    total_rvu: Decimal = Decimal(0)
    total_work_rvu: Decimal = Decimal(0)
    revenue_attributed: Decimal = Decimal(0)


@dataclass(slots=True)
class Aggregator:
    """Streaming accumulator over invoice rows.

    Usage:
        agg = Aggregator(drop_date=date(2026, 6, 3))
        for row in parse_invoice(invoice_bytes):
            agg.process_invoice_row(row)
        for grow in parse_guarantor(guarantor_bytes):
            agg.process_guarantor_row(grow)
        collections = agg.to_collections_rows()
        ar_snapshot = agg.to_ar_snapshot_rows()
        physician_mo = agg.to_physician_monthly_rows()
        agg.assert_v12_facility_consistency()
    """

    drop_date: date
    # Set of facility_no values seen in invoice rows. The orchestrator
    # uses this for V12 (FL-only check via masters.sites). Guarantor
    # rows confirm consistency with the invoice set.
    invoice_facilities: set[int] = field(default_factory=set)
    guarantor_facilities: set[int] = field(default_factory=set)
    # Row counters surface in the ingest_run telemetry.
    invoice_rows_consumed: int = 0
    guarantor_rows_consumed: int = 0
    phi_columns_stripped_total: int = 0
    # Internal accumulators. defaultdict(constructor) — each lookup
    # creates an empty accumulator on first access.
    _collections: defaultdict[tuple[date, int, str], _CollectionsAccumulator] = field(
        default_factory=lambda: defaultdict(_CollectionsAccumulator)
    )
    _ar: defaultdict[tuple[date, int, str], _ArAccumulator] = field(
        default_factory=lambda: defaultdict(_ArAccumulator)
    )
    _physician: defaultdict[
        tuple[date, str, int], _PhysicianAccumulator
    ] = field(default_factory=lambda: defaultdict(_PhysicianAccumulator))

    def process_invoice_row(self, row: InvoiceRow) -> None:
        """Update all three accumulators from one invoice row.

        V15 layer 2 assertion runs on the row's dump first — defensive
        against a parser bug or a future Pydantic config change that
        accidentally lets a PHI field through. Should never fire under
        the H8 parser, but cheap insurance.
        """
        dumped = row.model_dump(mode="python")
        # The PHI denial layer rejects any forbidden column key. If the
        # InvoiceRow model ever picks up such a key by accident, this
        # raises PHILeakError to the orchestrator's incident path.
        assert_no_phi_columns(dumped)

        self.invoice_rows_consumed += 1
        self.invoice_facilities.add(row.facility_no)

        # ---- Collections accumulator ----
        coll_key = (row.service_date, row.facility_no, row.payer_class)
        cacc = self._collections[coll_key]
        cacc.gross_charges += row.gross_charges
        cacc.payments_received += row.payments_received
        cacc.contractual_adjustments += row.contractual_adjustments
        cacc.write_offs += row.write_offs
        cacc.payer_refunds += row.payer_refunds
        cacc.patient_refunds += row.patient_refunds

        # ---- AR snapshot accumulator ----
        bucket = classify_aging_bucket(row.days_since_service, row.outstanding_amount)
        ar_key = (self.drop_date, row.facility_no, bucket)
        self._ar[ar_key].outstanding_amount += row.outstanding_amount

        # ---- Physician monthly accumulator ----
        phys_key = (
            _first_of_month(row.service_date),
            row.rendering_npi,
            row.facility_no,
        )
        pacc = self._physician[phys_key]
        pacc.encounters_count += 1
        pacc.total_rvu += row.total_rvu
        pacc.total_work_rvu += row.work_rvu
        # Revenue attribution = payments_received per encounter line.
        # An alternative formula (net_revenue distributed across lines)
        # is documented in the plan; locked at payments_received for v1.
        pacc.revenue_attributed += row.payments_received

    def process_guarantor_row(self, row: GuarantorRow) -> None:
        """Record the guarantor row for V12 cross-file consistency.

        Aggregator doesn't consume guarantor data into any fact table —
        the file is only parsed for V15 sanity. We track facility_no
        per row so the orchestrator can verify the invoice + guarantor
        facility sets match (one of V12's checks).
        """
        self.guarantor_rows_consumed += 1
        self.guarantor_facilities.add(row.facility_no)

    # ----------------------------------------------------------------
    # Emit aggregates as writer-ready dataclass instances
    # ----------------------------------------------------------------

    def to_collections_rows(self) -> list[CollectionsAggregate]:
        """Emit one CollectionsAggregate per (date, facility, payer) group.

        Computes net_revenue per the locked formula:
            net_revenue = payments_received - payer_refunds - patient_refunds

        Result is sorted by (date, facility, payer) so the writer's
        idempotent upsert sees a deterministic order — easier to diff
        between runs and easier to read in audit logs.
        """
        out: list[CollectionsAggregate] = []
        for (d, fac, payer), acc in sorted(self._collections.items()):
            net = acc.payments_received - acc.payer_refunds - acc.patient_refunds
            out.append(
                CollectionsAggregate(
                    date=d,
                    facility_no=fac,
                    payer_class=payer,
                    gross_charges=acc.gross_charges,
                    payments_received=acc.payments_received,
                    contractual_adjustments=acc.contractual_adjustments,
                    write_offs=acc.write_offs,
                    payer_refunds=acc.payer_refunds,
                    patient_refunds=acc.patient_refunds,
                    net_revenue=net,
                )
            )
        return out

    def to_ar_snapshot_rows(self) -> list[ArSnapshotAggregate]:
        """Emit one ArSnapshotAggregate per (snapshot_date, facility, bucket)."""
        return [
            ArSnapshotAggregate(
                snapshot_date=d,
                facility_no=fac,
                aging_bucket=bucket,
                outstanding_amount=acc.outstanding_amount,
            )
            for (d, fac, bucket), acc in sorted(self._ar.items())
        ]

    def to_physician_monthly_rows(self) -> list[PhysicianMonthlyAggregate]:
        """Emit one PhysicianMonthlyAggregate per (month, npi, facility)."""
        return [
            PhysicianMonthlyAggregate(
                month=m,
                physician_npi=npi,
                facility_no=fac,
                encounters_count=acc.encounters_count,
                total_rvu=acc.total_rvu,
                total_work_rvu=acc.total_work_rvu,
                revenue_attributed=acc.revenue_attributed,
            )
            for (m, npi, fac), acc in sorted(self._physician.items())
        ]

    # ----------------------------------------------------------------
    # Cross-file consistency check (called by main.py before write)
    # ----------------------------------------------------------------

    def assert_facility_set_consistency(self) -> None:
        """Raise V12-equivalent ValidationError if invoice + guarantor
        facility sets differ.

        Both files describe the same drop; if invoice references facility
        5 but guarantor doesn't (or vice versa), Ventra's source-side
        join is broken. Raise V12 to route to the incident path — this
        is the same severity as a TX facility appearing (ADR-005
        violation) because either is a vendor-side data-quality incident
        that demands immediate investigation.

        Special case: empty guarantor set is allowed (some drops have no
        new guarantors; the file may contain only the header).
        """
        if not self.guarantor_facilities:
            return

        invoice_only = self.invoice_facilities - self.guarantor_facilities
        guarantor_only = self.guarantor_facilities - self.invoice_facilities
        if invoice_only or guarantor_only:
            raise ValidationError(
                rule="V12",
                safe_message=(
                    f"facility set mismatch between invoice and guarantor: "
                    f"invoice_only={sorted(invoice_only)} "
                    f"guarantor_only={sorted(guarantor_only)}"
                ),
                internal_details={
                    "invoice_facility_count": len(self.invoice_facilities),
                    "guarantor_facility_count": len(self.guarantor_facilities),
                    "invoice_only": sorted(invoice_only),
                    "guarantor_only": sorted(guarantor_only),
                },
            )


__all__ = [
    "Aggregator",
    "ArSnapshotAggregate",
    "CollectionsAggregate",
    "PhysicianMonthlyAggregate",
    "classify_aging_bucket",
]
