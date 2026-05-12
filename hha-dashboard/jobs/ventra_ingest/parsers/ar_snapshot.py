"""AR snapshot file parser — entries.fact_ar_snapshot source rows.

Per ADR-006, Ventra writes one ``ar_snapshot.csv`` per drop with grain
(snapshot_date, facility_no, aging_bucket). The bucket enum matches the
DB CHECK constraint on ``fact_ar_snapshot.aging_bucket`` from migration
0011.

This module owns V5 (schema match) and the per-row V9 component
(non-negative outstanding except in the credit bucket). The cross-row
V9 (per-(snapshot_date, facility_no) buckets sum within $1 tolerance)
lives in ``validators.py`` because it requires the full row list.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ._loop import parse_csv_rows


class ARSnapshotRow(BaseModel):
    """One ``ar_snapshot.csv`` row."""

    model_config = ConfigDict(extra="forbid", strict=False)

    snapshot_date: date
    facility_no: int = Field(gt=0)
    aging_bucket: Literal[
        "0-30", "31-60", "61-90", "91-120", "120+", "credit"
    ]
    outstanding_amount: Decimal
    # Ventra's PM-system tag — accepted, discarded at write (see
    # CollectionsRow docstring for the rationale).
    source_system: str

    @model_validator(mode="after")
    def _v9_per_row_sign(self) -> "ARSnapshotRow":
        """V9 (per-row component) — only the 'credit' bucket may hold a
        negative balance. All other buckets must be non-negative.

        The cross-row V9 (buckets sum to expected total within tolerance)
        is enforced separately in ``validators.validate_ar_buckets_sum``.
        """
        if self.aging_bucket != "credit" and self.outstanding_amount < 0:
            raise ValueError(
                f"V9: aging_bucket={self.aging_bucket!r} has negative "
                f"outstanding_amount={self.outstanding_amount}; only "
                f"the 'credit' bucket may be negative"
            )
        return self


def parse_ar_snapshot(data: bytes) -> list[ARSnapshotRow]:
    """Parse ``ar_snapshot.csv`` bytes into ``ARSnapshotRow`` instances."""
    return parse_csv_rows(data, ARSnapshotRow, "ar_snapshot.csv")
