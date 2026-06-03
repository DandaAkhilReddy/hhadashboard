"""Streaming parsers for Ventra's row-level Standard Data Extract.

Two file types ship in each drop:

  ``invoice.csv``    — one row per claim/encounter line. Source of the
                       collections + AR-snapshot + physician-monthly
                       aggregates (H9 derives all three).
  ``guarantor.csv``  — one row per guarantor. Read mostly for V15
                       schema-presence sanity (Ventra promised these
                       columns); the aggregator doesn't actually
                       consume guarantor data — collections / AR /
                       physician aggregates all derive from invoice rows.

Both parsers are streaming generators — they yield rows lazily so a
multi-million-row month of claims doesn't slurp into memory. The
aggregator (H9) consumes the generator one row at a time and updates
its in-memory accumulator. The PHI columns Ventra sends in each row
are stripped BEFORE the row reaches the Pydantic model, so even a
parser bug cannot leak PHI further downstream.

ROUTES maps file_name -> parser callable. The orchestrator (H13) reads
the manifest and dispatches by file_name.
"""

from .standard_spec import (
    GuarantorRow,
    InvoiceRow,
    parse_guarantor,
    parse_invoice,
)

ROUTES = {
    "invoice.csv": parse_invoice,
    "guarantor.csv": parse_guarantor,
}

__all__ = [
    "ROUTES",
    "GuarantorRow",
    "InvoiceRow",
    "parse_guarantor",
    "parse_invoice",
]
