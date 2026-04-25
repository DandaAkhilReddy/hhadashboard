"""Ventra CSV parser tests.

Hard rejection on:
  - missing required columns
  - forbidden columns (PHI / per-claim leak)
  - bad numeric values
  - out-of-range year/month

Happy path: well-formed CSV → expected VentraRow objects.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from jobs.ventra_ingest.parser import (
    VentraParseError,
    VentraRow,
    parse_ventra_csv,
)

GOOD_HEADER = (
    "period_year,period_month,collections_usd,ventra_fee_usd,ar_total_usd,"
    "ar_0_30_usd,ar_31_60_usd,ar_61_90_usd,ar_91_120_usd,ar_over_120_usd,"
    "net_collection_rate_pct,days_in_ar"
)


def _good_csv(*data_rows: str) -> str:
    return GOOD_HEADER + "\n" + "\n".join(data_rows) + "\n"


def test_parses_one_row() -> None:
    csv = _good_csv(
        "2026,3,2280000.00,114000.00,5600000.00,1568000.00,1120000.00,"
        "784000.00,728000.00,1400000.00,43.00,39.90"
    )
    rows = parse_ventra_csv(csv)
    assert len(rows) == 1
    r = rows[0]
    assert r == VentraRow(
        year=2026,
        month=3,
        collections_usd=Decimal("2280000.00"),
        ventra_fee_usd=Decimal("114000.00"),
        ar_total_usd=Decimal("5600000.00"),
        ar_0_30_usd=Decimal("1568000.00"),
        ar_31_60_usd=Decimal("1120000.00"),
        ar_61_90_usd=Decimal("784000.00"),
        ar_91_120_usd=Decimal("728000.00"),
        ar_over_120_usd=Decimal("1400000.00"),
        net_collection_rate_pct=Decimal("43.00"),
        days_in_ar=Decimal("39.90"),
    )


def test_parses_multi_row_backfill() -> None:
    csv = _good_csv(
        "2026,1,1000000,50000,4000000,1000000,800000,700000,500000,1000000,42,40",
        "2026,2,1100000,55000,4200000,1200000,900000,700000,400000,1000000,44,38",
    )
    rows = parse_ventra_csv(csv)
    assert len(rows) == 2
    assert rows[0].month == 1
    assert rows[1].month == 2


def test_rejects_missing_required_column() -> None:
    bad_header = "period_year,collections_usd"  # most columns missing
    csv = bad_header + "\n2026,1000000\n"
    with pytest.raises(VentraParseError, match="Missing required columns"):
        parse_ventra_csv(csv)


def test_rejects_forbidden_claim_id_column() -> None:
    """Per ADR-001 — Ventra must pre-aggregate. A claim_id column = abort."""
    csv = (
        GOOD_HEADER + ",claim_id\n"
        "2026,3,1,1,1,1,1,1,1,1,1,1,CLM-12345\n"
    )
    with pytest.raises(VentraParseError, match="Forbidden columns"):
        parse_ventra_csv(csv)


def test_rejects_forbidden_patient_name_column() -> None:
    csv = (
        GOOD_HEADER + ",patient_name\n"
        "2026,3,1,1,1,1,1,1,1,1,1,1,Jane Doe\n"
    )
    with pytest.raises(VentraParseError, match="Forbidden columns"):
        parse_ventra_csv(csv)


def test_rejects_forbidden_dos_column() -> None:
    csv = (
        GOOD_HEADER + ",dos\n"
        "2026,3,1,1,1,1,1,1,1,1,1,1,2026-03-15\n"
    )
    with pytest.raises(VentraParseError, match="Forbidden columns"):
        parse_ventra_csv(csv)


def test_rejects_invalid_decimal() -> None:
    csv = _good_csv("2026,3,not-a-number,0,0,0,0,0,0,0,0,0")
    with pytest.raises(VentraParseError, match="not a valid decimal"):
        parse_ventra_csv(csv)


def test_rejects_out_of_range_month() -> None:
    csv = _good_csv("2026,13,1,1,1,1,1,1,1,1,1,1")
    with pytest.raises(VentraParseError, match="period_month"):
        parse_ventra_csv(csv)


def test_rejects_out_of_range_year() -> None:
    csv = _good_csv("1999,3,1,1,1,1,1,1,1,1,1,1")
    with pytest.raises(VentraParseError, match="period_year"):
        parse_ventra_csv(csv)


def test_rejects_empty_csv() -> None:
    with pytest.raises(VentraParseError, match="no header"):
        parse_ventra_csv("")


def test_header_case_insensitive() -> None:
    """Tolerate Period_Year, COLLECTIONS_USD, etc. — column names normalized to lower-case."""
    upper_header = GOOD_HEADER.upper()
    csv = upper_header + "\n2026,3,1000000,50000,1000000,200000,200000,200000,200000,200000,42,40\n"
    rows = parse_ventra_csv(csv)
    assert len(rows) == 1
    assert rows[0].year == 2026
