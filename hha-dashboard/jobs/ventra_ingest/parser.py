"""Ventra FL monthly-aggregate CSV parser.

Per ADR-001, Ventra MUST hand us pre-aggregated monthly rows — no
claim-level data, no patient identifiers. The schema below is the contract
we agreed with Gilda Romero (one row per month, 12 numeric columns + period).

If Ventra's actual file ever ships with extra columns (claim_id, encounter_id,
patient_*, etc.), this parser must FAIL LOUDLY rather than silently include
PHI. The forbidden-column check is a hard gate.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import StringIO

log = logging.getLogger(__name__)

EXPECTED_COLUMNS: tuple[str, ...] = (
    "period_year",
    "period_month",
    "collections_usd",
    "ventra_fee_usd",
    "ar_total_usd",
    "ar_0_30_usd",
    "ar_31_60_usd",
    "ar_61_90_usd",
    "ar_91_120_usd",
    "ar_over_120_usd",
    "net_collection_rate_pct",
    "days_in_ar",
)

# Hard reject if any of these appear in the CSV header — Ventra must not send
# claim-level or patient data per ADR-001.
FORBIDDEN_COLUMNS: frozenset[str] = frozenset(
    {
        "claim_id",
        "encounter_id",
        "patient_id",
        "patient_name",
        "patient_dob",
        "patient_mrn",
        "mrn",
        "member_id",
        "subscriber_id",
        "subscriber_name",
        "guarantor_id",
        "guarantor_name",
        "dos",
        "date_of_service",
        "cpt",
        "cpt_code",
        "icd10",
        "ssn",
    }
)


class VentraParseError(ValueError):
    """Raised when the CSV violates the agreed schema or contains forbidden columns."""


@dataclass(frozen=True)
class VentraRow:
    """One parsed monthly aggregate row, ready to upsert."""

    year: int
    month: int
    collections_usd: Decimal
    ventra_fee_usd: Decimal
    ar_total_usd: Decimal
    ar_0_30_usd: Decimal
    ar_31_60_usd: Decimal
    ar_61_90_usd: Decimal
    ar_91_120_usd: Decimal
    ar_over_120_usd: Decimal
    net_collection_rate_pct: Decimal
    days_in_ar: Decimal


def _check_columns(fieldnames: list[str] | None) -> None:
    """Verify header — required columns present, no forbidden columns."""
    if not fieldnames:
        raise VentraParseError("CSV has no header row")

    header_lower = {f.lower().strip() for f in fieldnames}

    bad = header_lower & FORBIDDEN_COLUMNS
    if bad:
        # Do not log the offending column values — just names. Names alone are
        # not PHI but values would be.
        raise VentraParseError(
            f"Forbidden columns in Ventra CSV (PHI / per-claim leak): {sorted(bad)}. "
            "Per ADR-001, Ventra must pre-aggregate at the edge."
        )

    missing = set(EXPECTED_COLUMNS) - header_lower
    if missing:
        raise VentraParseError(f"Missing required columns: {sorted(missing)}")


def _decimal(value: str, field: str, row_idx: int) -> Decimal:
    try:
        return Decimal(value.strip())
    except (InvalidOperation, AttributeError) as e:
        raise VentraParseError(
            f"Row {row_idx}: column '{field}' is not a valid decimal: {value!r}"
        ) from e


def _int_in_range(value: str, field: str, row_idx: int, lo: int, hi: int) -> int:
    try:
        n = int(value.strip())
    except ValueError as e:
        raise VentraParseError(
            f"Row {row_idx}: column '{field}' is not an integer: {value!r}"
        ) from e
    if not (lo <= n <= hi):
        raise VentraParseError(
            f"Row {row_idx}: column '{field}' = {n} not in [{lo}, {hi}]"
        )
    return n


def parse_ventra_csv(text: str) -> list[VentraRow]:
    """Parse a Ventra FL monthly-aggregate CSV.

    Raises VentraParseError on any header / value violation. On success,
    returns one VentraRow per data row (typically 1 row per file, but the
    parser handles N-row backfills the same way).
    """
    reader = csv.DictReader(StringIO(text))
    _check_columns(reader.fieldnames)

    out: list[VentraRow] = []
    for idx, raw in enumerate(reader, start=2):  # row 1 is the header
        # Lower-case keys so the file can use Year / period_year / etc.
        row = {k.lower().strip(): (v or "") for k, v in raw.items()}

        year = _int_in_range(row["period_year"], "period_year", idx, 2020, 2100)
        month = _int_in_range(row["period_month"], "period_month", idx, 1, 12)

        out.append(
            VentraRow(
                year=year,
                month=month,
                collections_usd=_decimal(row["collections_usd"], "collections_usd", idx),
                ventra_fee_usd=_decimal(row["ventra_fee_usd"], "ventra_fee_usd", idx),
                ar_total_usd=_decimal(row["ar_total_usd"], "ar_total_usd", idx),
                ar_0_30_usd=_decimal(row["ar_0_30_usd"], "ar_0_30_usd", idx),
                ar_31_60_usd=_decimal(row["ar_31_60_usd"], "ar_31_60_usd", idx),
                ar_61_90_usd=_decimal(row["ar_61_90_usd"], "ar_61_90_usd", idx),
                ar_91_120_usd=_decimal(row["ar_91_120_usd"], "ar_91_120_usd", idx),
                ar_over_120_usd=_decimal(row["ar_over_120_usd"], "ar_over_120_usd", idx),
                net_collection_rate_pct=_decimal(
                    row["net_collection_rate_pct"], "net_collection_rate_pct", idx
                ),
                days_in_ar=_decimal(row["days_in_ar"], "days_in_ar", idx),
            )
        )

    log.info("ventra_parse.ok rows=%d", len(out))
    return out
