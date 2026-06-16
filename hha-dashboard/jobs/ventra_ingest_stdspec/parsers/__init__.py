"""Streaming parsers for Ventra's Standard Data Extract (5 files).

Per the 2026-06-15 reply HHA ingests **Invoice, ChargeLines, Physician,
Facility, TransactionsAlt** (files 1-4 + 5). Guarantor (#9) and 6-10 are
declined.

ROUTES maps the canonical (lowercased, no-extension) file stem -> parser.
The orchestrator (R5) normalizes each manifest ``file_name`` to its stem
before dispatching, so ``Invoice.csv`` / ``invoice.CSV`` / ``Invoice.txt``
all resolve to the same parser (exact delivered names/extensions are a
clarification ask to Ventra).

Each parser is a streaming generator — the aggregator consumes one row at
a time so a multi-million-row month never slurps into memory. PHI is
stripped (allowlist) BEFORE each row reaches its Pydantic model.
"""

from .standard_spec import (
    ChargeLineRow,
    FacilityRow,
    InvoiceRow,
    PhysicianRow,
    TransactionRow,
    parse_chargelines,
    parse_facility,
    parse_invoice,
    parse_physician,
    parse_transactions,
)

# Canonical stem -> parser. Stems are lowercase, extension-stripped.
ROUTES = {
    "invoice": parse_invoice,
    "chargelines": parse_chargelines,
    "physician": parse_physician,
    "facility": parse_facility,
    "transactionsalt": parse_transactions,
}

__all__ = [
    "ROUTES",
    "ChargeLineRow",
    "FacilityRow",
    "InvoiceRow",
    "PhysicianRow",
    "TransactionRow",
    "parse_chargelines",
    "parse_facility",
    "parse_invoice",
    "parse_physician",
    "parse_transactions",
]
