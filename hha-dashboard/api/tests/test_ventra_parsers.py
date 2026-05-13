"""Per-file parser tests for the Ventra ingest pipeline.

Covers V5, V7, V9 (per-row component), V10, V11. The cross-file
validators (V6 drop-date drift, V9 bucket-sum tolerance, V12 FL invariant,
V13 dedup) are tested separately in ``test_ventra_validators.py``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from jobs.ventra_ingest.exceptions import ValidationError
from jobs.ventra_ingest.parsers import (
    parse_ar_snapshot,
    parse_collections,
    parse_file,
    parse_physician_monthly,
)

# =========================================================================
# collections.csv — V5 (schema) + V10 (sanity)
# =========================================================================


def _collections_csv(*rows: str) -> bytes:
    header = (
        "date,facility_no,payer_class,gross_charges,payments_received,"
        "contractual_adjustments,write_offs,payer_refunds,patient_refunds,"
        "net_revenue,source_system"
    )
    return ("\n".join([header, *rows]) + "\n").encode("utf-8")


def test_collections_parses_well_formed_row() -> None:
    body = _collections_csv(
        "2026-05-15,901,commercial,10000.00,8000.00,500.00,200.00,0,0,7300.00,CB"
    )
    rows = parse_collections(body)
    assert len(rows) == 1
    r = rows[0]
    assert r.facility_no == 901
    assert r.payer_class == "commercial"
    assert r.gross_charges == Decimal("10000.00")
    assert r.source_system == "CB"


def test_collections_v5_rejects_unknown_column() -> None:
    body = (
        b"date,facility_no,payer_class,gross_charges,payments_received,"
        b"contractual_adjustments,write_offs,payer_refunds,patient_refunds,"
        b"net_revenue,source_system,patient_mrn\n"
        b"2026-05-15,901,commercial,10000,8000,0,0,0,0,7500,CB,12345\n"
    )
    with pytest.raises(ValidationError) as exc:
        parse_collections(body)
    assert exc.value.rule == "V5"
    assert exc.value.details["line_no"] == 2


def test_collections_v5_rejects_invalid_payer_class() -> None:
    body = _collections_csv(
        "2026-05-15,901,bogus_payer,10000,8000,0,0,0,0,7500,CB"
    )
    with pytest.raises(ValidationError) as exc:
        parse_collections(body)
    assert exc.value.rule == "V5"


def test_collections_v5_rejects_missing_required_column() -> None:
    body = (
        b"date,facility_no,payer_class,gross_charges\n"
        b"2026-05-15,901,commercial,10000\n"
    )
    with pytest.raises(ValidationError) as exc:
        parse_collections(body)
    assert exc.value.rule == "V5"


def test_collections_v5_rejects_negative_gross_charges() -> None:
    body = _collections_csv(
        "2026-05-15,901,commercial,-100,0,0,0,0,0,0,CB"
    )
    with pytest.raises(ValidationError) as exc:
        parse_collections(body)
    assert exc.value.rule == "V5"


def test_collections_v10_rejects_payments_exceed_charges_plus_writeoffs() -> None:
    # payments_received=15000 > gross_charges (10000) + write_offs (0)
    body = _collections_csv(
        "2026-05-15,901,commercial,10000,15000,0,0,0,0,7500,CB"
    )
    with pytest.raises(ValidationError) as exc:
        parse_collections(body)
    assert exc.value.rule == "V10"


def test_collections_v10_passes_when_writeoffs_cover_gap() -> None:
    # gross + write_offs = 10000 + 5000 = 15000 >= payments_received 14000 OK
    body = _collections_csv(
        "2026-05-15,901,commercial,10000,14000,0,5000,0,0,9000,CB"
    )
    rows = parse_collections(body)
    assert len(rows) == 1


def test_collections_v5_rejects_bad_utf8() -> None:
    with pytest.raises(ValidationError) as exc:
        parse_collections(b"\xff\xfe garbage")
    assert exc.value.rule == "V5"


def test_collections_v5_rejects_empty() -> None:
    with pytest.raises(ValidationError) as exc:
        parse_collections(b"")
    assert exc.value.rule == "V5"


def test_collections_empty_after_header_is_allowed() -> None:
    body = _collections_csv()  # header only, no rows
    assert parse_collections(body) == []


# =========================================================================
# ar_snapshot.csv — V5 (schema) + V9 (per-row sign)
# =========================================================================


def _ar_csv(*rows: str) -> bytes:
    header = (
        "snapshot_date,facility_no,aging_bucket,outstanding_amount,source_system"
    )
    return ("\n".join([header, *rows]) + "\n").encode("utf-8")


def test_ar_snapshot_parses_well_formed_row() -> None:
    body = _ar_csv("2026-05-15,901,0-30,50000.00,CB")
    rows = parse_ar_snapshot(body)
    assert len(rows) == 1
    assert rows[0].aging_bucket == "0-30"
    assert rows[0].outstanding_amount == Decimal("50000.00")


def test_ar_snapshot_v5_rejects_invalid_aging_bucket() -> None:
    body = _ar_csv("2026-05-15,901,180+,50000,CB")
    with pytest.raises(ValidationError) as exc:
        parse_ar_snapshot(body)
    assert exc.value.rule == "V5"


def test_ar_snapshot_v9_rejects_negative_non_credit() -> None:
    body = _ar_csv("2026-05-15,901,0-30,-100,CB")
    with pytest.raises(ValidationError) as exc:
        parse_ar_snapshot(body)
    assert exc.value.rule == "V9"


def test_ar_snapshot_v9_allows_negative_credit() -> None:
    body = _ar_csv("2026-05-15,901,credit,-5000.00,CB")
    rows = parse_ar_snapshot(body)
    assert rows[0].aging_bucket == "credit"
    assert rows[0].outstanding_amount == Decimal("-5000.00")


# =========================================================================
# physician_monthly.csv — V5 (schema) + V7 (first-of-month) + V11 (NPI/RVU)
# =========================================================================


def _phys_csv(*rows: str) -> bytes:
    header = (
        "month,physician_npi,facility_no,encounters_count,"
        "total_rvu,total_work_rvu,revenue_attributed,source_system"
    )
    return ("\n".join([header, *rows]) + "\n").encode("utf-8")


def test_physician_monthly_parses_well_formed_row() -> None:
    body = _phys_csv("2026-05-01,1234567890,901,50,123.50,98.40,75000.00,CB")
    rows = parse_physician_monthly(body)
    assert len(rows) == 1
    r = rows[0]
    assert r.physician_npi == "1234567890"
    assert r.encounters_count == 50
    assert r.total_rvu == Decimal("123.50")


def test_physician_monthly_v7_rejects_non_first_of_month() -> None:
    body = _phys_csv("2026-05-15,1234567890,901,50,100,80,75000,CB")
    with pytest.raises(ValidationError) as exc:
        parse_physician_monthly(body)
    assert exc.value.rule == "V7"


def test_physician_monthly_v11_rejects_short_npi() -> None:
    body = _phys_csv("2026-05-01,12345,901,50,100,80,75000,CB")
    with pytest.raises(ValidationError) as exc:
        parse_physician_monthly(body)
    assert exc.value.rule == "V5"  # Pydantic Field(pattern=...) failures are V5


def test_physician_monthly_v11_rejects_non_numeric_npi() -> None:
    body = _phys_csv("2026-05-01,123abc7890,901,50,100,80,75000,CB")
    with pytest.raises(ValidationError) as exc:
        parse_physician_monthly(body)
    assert exc.value.rule == "V5"


def test_physician_monthly_v11_rejects_negative_encounters() -> None:
    body = _phys_csv("2026-05-01,1234567890,901,-1,100,80,75000,CB")
    with pytest.raises(ValidationError) as exc:
        parse_physician_monthly(body)
    # Pydantic Field(ge=0) maps to V5 (schema-level constraint).
    assert exc.value.rule == "V5"


def test_physician_monthly_v11_rejects_negative_rvu() -> None:
    body = _phys_csv("2026-05-01,1234567890,901,50,-1,80,75000,CB")
    with pytest.raises(ValidationError) as exc:
        parse_physician_monthly(body)
    assert exc.value.rule == "V5"


# =========================================================================
# dispatch — parse_file()
# =========================================================================


def test_dispatch_routes_collections() -> None:
    body = _collections_csv(
        "2026-05-15,901,commercial,1000,800,0,0,0,0,750,CB"
    )
    rows = parse_file("collections.csv", body)
    assert len(rows) == 1


def test_dispatch_routes_ar_snapshot() -> None:
    body = _ar_csv("2026-05-15,901,31-60,30000,CB")
    rows = parse_file("ar_snapshot.csv", body)
    assert len(rows) == 1


def test_dispatch_routes_physician_monthly() -> None:
    body = _phys_csv("2026-05-01,1234567890,901,50,100,80,75000,CB")
    rows = parse_file("physician_monthly.csv", body)
    assert len(rows) == 1


def test_dispatch_keyerror_on_unknown_file_name() -> None:
    # Caller is responsible for filtering via manifest.KNOWN_FILE_NAMES (V1);
    # a KeyError here is a programmer bug, not a vendor data issue.
    with pytest.raises(KeyError):
        parse_file("totally_unknown.csv", b"a\n")
