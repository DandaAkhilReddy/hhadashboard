"""In-memory multi-file join + aggregation for the row-level pipeline.

Rewritten 2026-06-16 (R4) against Ventra's real 5-file spec. The pipeline
ingests Invoice + ChargeLines + Physician + Facility + TransactionsAlt and
must JOIN them in memory before aggregating to the three fact-table grains.

Join model (from the spec's "File Joins" tab):
  Invoice.InvoiceNo == ChargeLines.InvoiceNo == TransactionsAlt.InvoiceNo
  Invoice.FacilityNo == Facility.FacilityNo
  ChargeLines.PrimaryPhysicianNPI == Physician.NPI

Because the files stream independently and in any order, the aggregator
accumulates per-invoice partial state keyed by the transient ``InvoiceNo``
(never persisted), then ``emit(facility_map)`` performs the join +
facility resolution + aggregation and returns the three aggregate lists.

Derivations:
  fact_collections_daily (date, site_id, payer):
    gross_charges        <- sum ChargeLines.ChargeAmt
    payments_received    <- sum TransactionsAlt where TranType=Payment
    contractual_adjustments <- TranType=Adjustment & comment~contract
    write_offs           <- TranType=Adjustment & comment~bad debt/write
    payer_refunds        <- TranType=Refund & TranSource=Insurance
    patient_refunds      <- TranType=Refund & TranSource=Patient
    net_revenue          = payments_received - payer_refunds - patient_refunds
    date  = the charge/transaction PostingDate (operational, NOT DOS/PHI)
    payer = normalize(Invoice.PrimaryInsClass) for charges;
            normalize(TransactionsAlt.InsuranceClass) for payments

  fact_ar_snapshot (drop_date, site_id, bucket):
    per invoice: open_balance = sum(charges) - sum(payments+adjustments+writeoffs)
    age_days = drop_date - max(charge PostingDate for that invoice)
    bucket via classify_aging_bucket(age_days, open_balance)

  fact_revenue_by_physician_mo (month, npi, site_id):
    encounters_count  = distinct InvoiceNo count per (month, npi, site)
    total_rvu/work_rvu <- sum ChargeLines.RVU/WorkRVU
    revenue_attributed <- payments attributed to the invoices in the group
    month = first-of-month(charge PostingDate)

Facility resolution: every aggregate's ``facility_no`` is the HHA
``masters.sites.id`` (1-7), resolved from the Ventra ``FacilityNo``
(2284-2290) via the ``facility_map`` passed to ``emit()`` (loaded from
``dims.facility_codes`` by ``validate_fl_only`` in R5). A Ventra FacilityNo
absent from the map raises — but ``validate_fl_only`` runs first and
quarantines unmapped drops (V8), so ``emit`` should never hit that.

PHI-safety: the aggregator stores only the transient InvoiceNo join key +
aggregation keys + Decimal sums + counters. No raw row content; no PHI
column. The emitted aggregates carry only fact-table columns.

Net-revenue formula (locked 2026-05-25, CFO + Sandy sign-off):
  net_revenue = payments_received - payer_refunds - patient_refunds
Single place to update if Ventra's reply changes the definition.

Signed amounts (Ventra confirmed 2026-06-22): ``TranAmt`` carries its
natural sign — a payment reversal is a negative Payment, etc. Buckets
accumulate the SIGNED sum so same-type reversals net correctly, then emit
takes the column magnitude (the fact columns are non-negative; net_revenue
+ AR formulas encode direction). Payments are expected to net non-negative;
a negative net fails closed as V10 rather than abs-flipping (which would
overstate collections). The exact per-TranType sign convention is the open
clarification in the 2026-06-22 reply.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .exceptions import ValidationError
from .parsers.standard_spec import (
    ChargeLineRow,
    FacilityRow,
    InvoiceRow,
    PhysicianRow,
    TransactionRow,
    normalize_payer_class,
)

# ============================================================================
# Aggregate dataclasses — writer inputs (unchanged from H9 / writer contract)
# ============================================================================


@dataclass(frozen=True, slots=True)
class CollectionsAggregate:
    """One row of fact_collections_daily. Natural key (date, facility_no,
    payer_class). source_system set by the writer to VENTRA_FL_STDSPEC_AGG;
    state set by the DB default to FL. ``facility_no`` is the HHA site_id."""

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
    """One row of fact_ar_snapshot. Natural key (snapshot_date, facility_no,
    aging_bucket). ``facility_no`` is the HHA site_id."""

    snapshot_date: date
    facility_no: int
    aging_bucket: str
    outstanding_amount: Decimal


@dataclass(frozen=True, slots=True)
class PhysicianMonthlyAggregate:
    """One row of fact_revenue_by_physician_mo. Natural key (month,
    physician_npi, facility_no). ``facility_no`` is the HHA site_id."""

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
    that overshot the charge — refunds owed), regardless of days.
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
    """Return the first-of-month date for ``d`` — matches the
    fact_revenue_by_physician_mo month CHECK."""
    return date(d.year, d.month, 1)


# ============================================================================
# Transaction classification
# ============================================================================


def _classify_transaction(row: TransactionRow) -> tuple[str, Decimal]:
    """Map a transaction to a collections bucket + its SIGNED amount.

    Returns ``(bucket, signed_amount)`` where bucket is one of:
      'payments_received' | 'contractual_adjustments' | 'write_offs'
      | 'payer_refunds' | 'patient_refunds' | 'ignore'

    Ventra confirmed (2026-06-22) that ``TranAmt`` carries its natural sign
    — a payment reversal is a negative Payment, etc. We preserve the sign
    here and let the aggregator NET same-type reversals before taking the
    column magnitude at emit. This fixes the prior ``abs()``-per-row bug
    that double-counted a payment and its reversal as two positives.

    The exact per-``TranType`` sign convention is the one open clarification
    in the 2026-06-22 reply; the emit-stage magnitudes + the V10
    net-negative-payments guard make the interim handling fail-closed.

    Transfers and unknown types map to 'ignore' (internal AR movement,
    net-zero to collections).
    """
    ttype = (row.tran_type or "").strip().lower()
    comment = (row.tran_comment or "").strip().lower()
    source = (row.tran_source or "").strip().lower()
    amt = row.tran_amt  # signed — do NOT abs here; netting happens at emit

    if ttype == "payment":
        return "payments_received", amt
    if ttype == "refund":
        if "patient" in source:
            return "patient_refunds", amt
        return "payer_refunds", amt
    if ttype == "adjustment":
        if "bad debt" in comment or "write" in comment or "writeoff" in comment:
            return "write_offs", amt
        # Contract adjustments + any other adjustment default to contractual.
        return "contractual_adjustments", amt
    # Transfer / Unknown -> net-zero internal movement.
    return "ignore", amt


# ============================================================================
# Per-invoice transient accumulators (keyed by InvoiceNo — never persisted)
# ============================================================================


@dataclass(slots=True)
class _InvoiceState:
    """Partial state for one invoice, joined across the 5 files."""

    ventra_facility_no: int | None = None
    payer_class: str = "other"  # from Invoice.PrimaryInsClass
    gross_charges: Decimal = Decimal(0)
    # Field names match the _classify_transaction bucket names so
    # process_transaction_row can setattr() directly.
    payments_received: Decimal = Decimal(0)
    contractual_adjustments: Decimal = Decimal(0)
    write_offs: Decimal = Decimal(0)
    payer_refunds: Decimal = Decimal(0)
    patient_refunds: Decimal = Decimal(0)
    last_posting_date: date | None = None
    # charge contributions for the physician/collections grain:
    # list of (posting_date, npi, charge_amt, rvu, work_rvu)
    charges: list[tuple[date | None, str, Decimal, Decimal, Decimal]] = field(
        default_factory=list
    )
    # transaction contributions: list of (posting_dt, payer_class, bucket, amount)
    txns: list[tuple[date | None, str, str, Decimal]] = field(default_factory=list)


@dataclass(slots=True)
class Aggregator:
    """Multi-file in-memory join + aggregation.

    Usage:
        agg = Aggregator(drop_date=date(2026, 6, 16))
        for r in parse_invoice(b):       agg.process_invoice_row(r)
        for r in parse_chargelines(b):   agg.process_chargeline_row(r)
        for r in parse_transactions(b):  agg.process_transaction_row(r)
        for r in parse_physician(b):     agg.process_physician_row(r)
        for r in parse_facility(b):      agg.process_facility_row(r)
        collections, ar, physician = agg.emit(facility_map)
    """

    drop_date: date

    _invoices: dict[int, _InvoiceState] = field(default_factory=dict)
    physician_types: dict[str, str] = field(default_factory=dict)
    ventra_facilities: set[int] = field(default_factory=set)

    invoice_rows_consumed: int = 0
    chargeline_rows_consumed: int = 0
    transaction_rows_consumed: int = 0
    physician_rows_consumed: int = 0
    facility_rows_consumed: int = 0

    def _invoice(self, invoice_no: int) -> _InvoiceState:
        st = self._invoices.get(invoice_no)
        if st is None:
            st = _InvoiceState()
            self._invoices[invoice_no] = st
        return st

    # ---- per-file row processors ----

    def process_invoice_row(self, row: InvoiceRow) -> None:
        """Record the invoice header: facility + payer linkage."""
        self.invoice_rows_consumed += 1
        st = self._invoice(row.invoice_no)
        st.ventra_facility_no = row.facility_no
        st.payer_class = normalize_payer_class(row.primary_ins_class)
        self.ventra_facilities.add(row.facility_no)

    def process_chargeline_row(self, row: ChargeLineRow) -> None:
        """Accumulate charge amount + RVU + billed NPI onto the invoice."""
        self.chargeline_rows_consumed += 1
        st = self._invoice(row.invoice_no)
        st.gross_charges += row.charge_amt
        st.charges.append(
            (
                row.posting_date,
                (row.primary_physician_npi or "").strip(),
                row.charge_amt,
                row.rvu,
                row.work_rvu,
            )
        )
        if row.posting_date is not None and (
            st.last_posting_date is None or row.posting_date > st.last_posting_date
        ):
            st.last_posting_date = row.posting_date

    def process_transaction_row(self, row: TransactionRow) -> None:
        """Accumulate a payment / adjustment / refund onto the invoice."""
        self.transaction_rows_consumed += 1
        st = self._invoice(row.invoice_no)
        bucket, amt = _classify_transaction(row)
        if bucket == "ignore":
            return
        setattr(st, bucket, getattr(st, bucket) + amt)
        # Payer for a transaction comes off the transaction's own class,
        # falling back to the invoice payer if blank.
        payer = (
            normalize_payer_class(row.insurance_class)
            if row.insurance_class.strip()
            else st.payer_class
        )
        tx_date = row.posting_dt or row.bank_deposit_dt
        st.txns.append((tx_date, payer, bucket, amt))

    def process_physician_row(self, row: PhysicianRow) -> None:
        """Reference: NPI -> doc type (name not needed for aggregates)."""
        self.physician_rows_consumed += 1
        if row.npi:
            self.physician_types[row.npi] = row.doc_type

    def process_facility_row(self, row: FacilityRow) -> None:
        """Reference: collect the Ventra FacilityNo for the FL-only check."""
        self.facility_rows_consumed += 1
        self.ventra_facilities.add(row.facility_no)

    # ---- join + emit ----

    def emit(
        self, facility_map: dict[int, int]
    ) -> tuple[
        list[CollectionsAggregate],
        list[ArSnapshotAggregate],
        list[PhysicianMonthlyAggregate],
    ]:
        """Join all accumulated state + resolve facilities + aggregate.

        ``facility_map`` maps Ventra FacilityNo -> HHA site_id. A FacilityNo
        absent from the map raises ValueError (validate_fl_only should have
        quarantined the drop first).
        """
        collections: dict[tuple[date, int, str], _CollAcc] = defaultdict(_CollAcc)
        ar: dict[tuple[date, int, str], Decimal] = defaultdict(lambda: Decimal(0))
        physician: dict[tuple[date, str, int], _PhysAcc] = defaultdict(_PhysAcc)
        physician_invoices: dict[tuple[date, str, int], set[int]] = defaultdict(set)

        for invoice_no, st in self._invoices.items():
            if st.ventra_facility_no is None:
                # Charge/transaction referencing an invoice with no header
                # row — skip (the invoice file is required; a missing header
                # is a join gap surfaced by row-count validation upstream).
                continue
            site_id = facility_map.get(st.ventra_facility_no)
            if site_id is None:
                raise ValueError(
                    f"unmapped Ventra FacilityNo {st.ventra_facility_no} "
                    f"(validate_fl_only should have caught this)"
                )

            # ---- collections: charges (by charge posting date + invoice payer) ----
            for posting_date, npi, charge_amt, rvu, work_rvu in st.charges:
                cdate = posting_date or self.drop_date
                ckey = (cdate, site_id, st.payer_class)
                collections[ckey].gross_charges += charge_amt
                # physician monthly grain
                if npi:
                    pkey = (_first_of_month(cdate), npi, site_id)
                    pacc = physician[pkey]
                    pacc.total_rvu += rvu
                    pacc.total_work_rvu += work_rvu
                    pacc.charge_total += charge_amt
                    physician_invoices[pkey].add(invoice_no)

            # ---- collections: payments/adjustments/refunds (by txn date + txn payer) ----
            for tx_date, payer, bucket, amt in st.txns:
                tdate = tx_date or self.drop_date
                tkey = (tdate, site_id, payer)
                setattr(
                    collections[tkey], bucket, getattr(collections[tkey], bucket) + amt
                )

            # ---- AR snapshot: per-invoice open balance + age ----
            # Buckets accumulate SIGNED amounts (reversals net within a
            # bucket); take the per-invoice magnitude so the accounting
            # formula reads in positive dollars: charges reduce by money
            # applied (payments + adjustments + write-offs) and re-open by
            # refunds paid back out.
            open_balance = (
                st.gross_charges
                - abs(st.payments_received)
                - abs(st.contractual_adjustments)
                - abs(st.write_offs)
                + abs(st.payer_refunds)
                + abs(st.patient_refunds)
            )
            if open_balance != 0:
                age_days = (
                    (self.drop_date - st.last_posting_date).days
                    if st.last_posting_date is not None
                    else 0
                )
                bucket = classify_aging_bucket(age_days, open_balance)
                ar[(self.drop_date, site_id, bucket)] += open_balance

        # ---- materialize collections ----
        # Each bucket is a SIGNED sum (reversals already netted). Payments
        # are expected to net non-negative under the assumed convention
        # (Payment +, reversal −); a negative net signals a sign-convention
        # mismatch or a data anomaly — fail closed (V10) rather than abs-flip
        # it and silently overstate collections. Refunds + adjustments are
        # stored as positive magnitudes (the fact columns are non-negative;
        # the net_revenue / AR formulas encode the direction).
        coll_rows: list[CollectionsAggregate] = []
        for (cdate, site_id, payer), acc in sorted(collections.items()):
            payments = acc.payments_received
            if payments < 0:
                raise ValidationError(
                    rule="V10",
                    safe_message=(
                        "payments net negative for a (date, facility, payer) "
                        "group — verify Ventra TranAmt sign convention"
                    ),
                    internal_details={
                        "date": cdate.isoformat(),
                        "facility_no": site_id,
                        "payer_class": payer,
                    },
                )
            payer_refunds = abs(acc.payer_refunds)
            patient_refunds = abs(acc.patient_refunds)
            net = payments - payer_refunds - patient_refunds
            coll_rows.append(
                CollectionsAggregate(
                    date=cdate,
                    facility_no=site_id,
                    payer_class=payer,
                    gross_charges=acc.gross_charges,
                    payments_received=payments,
                    contractual_adjustments=abs(acc.contractual_adjustments),
                    write_offs=abs(acc.write_offs),
                    payer_refunds=payer_refunds,
                    patient_refunds=patient_refunds,
                    net_revenue=net,
                )
            )

        # ---- materialize AR snapshot ----
        ar_rows = [
            ArSnapshotAggregate(
                snapshot_date=sdate,
                facility_no=site_id,
                aging_bucket=bucket,
                outstanding_amount=amount,
            )
            for (sdate, site_id, bucket), amount in sorted(ar.items())
        ]

        # ---- materialize physician monthly ----
        phys_rows = [
            PhysicianMonthlyAggregate(
                month=m,
                physician_npi=npi,
                facility_no=site_id,
                encounters_count=len(physician_invoices[(m, npi, site_id)]),
                total_rvu=acc.total_rvu,
                total_work_rvu=acc.total_work_rvu,
                # v1: billed charges attributed to the physician (dollars).
                # P2 refines to collected revenue once Ventra confirms whether
                # payments can be attributed to a charge line / NPI (the
                # TransactionsAlt file joins at invoice grain, not line/NPI).
                revenue_attributed=acc.charge_total,
            )
            for (m, npi, site_id), acc in sorted(physician.items())
        ]

        return coll_rows, ar_rows, phys_rows


@dataclass(slots=True)
class _CollAcc:
    gross_charges: Decimal = Decimal(0)
    payments_received: Decimal = Decimal(0)
    contractual_adjustments: Decimal = Decimal(0)
    write_offs: Decimal = Decimal(0)
    payer_refunds: Decimal = Decimal(0)
    patient_refunds: Decimal = Decimal(0)


@dataclass(slots=True)
class _PhysAcc:
    total_rvu: Decimal = Decimal(0)
    total_work_rvu: Decimal = Decimal(0)
    charge_total: Decimal = Decimal(0)


__all__ = [
    "Aggregator",
    "ArSnapshotAggregate",
    "CollectionsAggregate",
    "PhysicianMonthlyAggregate",
    "classify_aging_bucket",
]
