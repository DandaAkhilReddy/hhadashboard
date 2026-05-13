"""Collections file parser — entries.fact_collections_daily source rows.

Per the ADR-006 spec, Ventra writes one ``collections.csv`` per drop
with grain (date, facility_no, payer_class). This module owns V5 (schema
match), V10 (collections sanity), and V11-N/A. V6 (date drift vs the
drop folder name) lives in ``validators.py`` because it needs the
drop_date context the parser does not carry.

Ventra's ``source_system`` column carries their PM-system identifier
(CB / MGS / VSQL / DUVA). We accept any string here; the C12 writer
discards the value because the fact table's DB CHECK locks
``source_system = 'VENTRA_FL_ATHENA'``. The vendor value is captured in
the ``ventra.ingest_complete`` App Insights event for forensic queries.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ._loop import parse_csv_rows


class CollectionsRow(BaseModel):
    """One ``collections.csv`` row.

    ``extra='forbid'`` rejects any unknown column as a V5 schema-drift
    quarantine. Ventra must coordinate column additions per the schema-
    evolution policy in Phase 1A.A8.
    """

    model_config = ConfigDict(extra="forbid", strict=False)

    date: date
    facility_no: int = Field(gt=0)
    payer_class: Literal[
        "commercial", "medicare", "medicaid", "selfpay", "other"
    ]
    gross_charges: Decimal = Field(ge=0)
    payments_received: Decimal = Field(ge=0)
    contractual_adjustments: Decimal = Decimal(0)
    write_offs: Decimal = Decimal(0)
    payer_refunds: Decimal = Decimal(0)
    patient_refunds: Decimal = Decimal(0)
    net_revenue: Decimal
    # Ventra's PM-system tag (CB / MGS / VSQL / DUVA). Captured in
    # telemetry; discarded at write time (DB CHECK locks our source_system
    # column to VENTRA_FL_ATHENA).
    source_system: str

    @model_validator(mode="after")
    def _v10_collections_sanity(self) -> "CollectionsRow":
        """V10 — gross_charges + write_offs >= payments_received.

        Justification: if same-day payments exceed gross charges + bad-
        debt write-offs, the vendor's posting math is internally
        inconsistent (e.g. duplicate payment posting, or a write-off was
        booked against a different day's charges and the daily row is
        out of step). Either way, do not write the row — flag for
        vendor follow-up.
        """
        if self.gross_charges + self.write_offs < self.payments_received:
            raise ValueError(
                f"V10: payments_received={self.payments_received} exceeds "
                f"gross_charges + write_offs "
                f"({self.gross_charges} + {self.write_offs} = "
                f"{self.gross_charges + self.write_offs})"
            )
        return self


def parse_collections(data: bytes) -> list[CollectionsRow]:
    """Parse ``collections.csv`` bytes into ``CollectionsRow`` instances.

    See ``parsers._loop.parse_csv_rows`` for the full V5/V10 routing.
    """
    return parse_csv_rows(data, CollectionsRow, "collections.csv")
