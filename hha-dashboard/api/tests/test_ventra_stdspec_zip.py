"""Phase 4Z — zip-drop loader + signed TranAmt + PHI-canary acceptance gate.

Pure-Python (no DB): drives the row-level (stdspec) pipeline from raw zip
bytes through parse -> aggregate -> emit. The PHI-canary test is the H18
safety gate brought forward to the R/Z series — it proves no ``PHI_CANARY_``
marker injected into the PHI columns survives the allowlist strip into any
emitted aggregate.

``emit`` takes a facility_map dict directly, so the DB-bound
``validate_fl_only`` is bypassed and these tests need no Postgres.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from jobs.ventra_ingest_stdspec.aggregator import Aggregator
from jobs.ventra_ingest_stdspec.exceptions import ValidationError
from jobs.ventra_ingest_stdspec.manifest import (
    drop_date_from_zip_name,
    file_stem,
    unzip_drop,
)
from jobs.ventra_ingest_stdspec.parsers.standard_spec import (
    parse_chargelines,
    parse_facility,
    parse_invoice,
    parse_physician,
    parse_transactions,
)

CANARY = "PHI_CANARY"
ZIP_NAME = "ventra/stdspec/HHA_Extact_20260610.zip"
DROP = date(2026, 6, 10)
FMAP = {2289: 1}  # Ventra FacilityNo -> HHA site_id


# ---------------------------------------------------------------------------
# Fixture builders — the 5 files, with PHI columns carrying canary markers
# ---------------------------------------------------------------------------


def _csv(header: list[str], rows: list[list[str]]) -> bytes:
    lines = [",".join(header)]
    lines.extend(",".join(str(c) for c in r) for r in rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _invoice_csv() -> bytes:
    # Pat*/MRN/SSN/PolicyID are PHI and NOT in INVOICE_ALLOWLIST -> dropped.
    return _csv(
        ["InvoiceNo", "FacilityNo", "PrimaryInsClass", "SourceSystem",
         "PatFName", "PatLName", "MRN", "SSN", "PrimaryPolicyID", "PatBirthDate"],
        [
            ["1", "2289", "Commercial", "CB",
             f"{CANARY}_FNAME", f"{CANARY}_LNAME", f"{CANARY}_MRN",
             f"{CANARY}_SSN", f"{CANARY}_POLICY", f"{CANARY}_DOB"],
            ["2", "2289", "Medicare", "CB",
             f"{CANARY}_FNAME2", f"{CANARY}_LNAME2", f"{CANARY}_MRN2",
             f"{CANARY}_SSN2", f"{CANARY}_POLICY2", f"{CANARY}_DOB2"],
        ],
    )


def _chargelines_csv() -> bytes:
    # CPT/ICD/DOS are PHI and NOT in CHARGELINE_ALLOWLIST -> dropped.
    return _csv(
        ["InvoiceNo", "ChargeAmt", "RVU", "WorkRVU", "PrimaryPhysicianNPI",
         "PostingDate", "SourceSystem", "CPT", "ICD10_1", "DOS"],
        [
            ["1", "200", "2.0", "1.5", "1234567890", "2026-06-10", "CB",
             f"{CANARY}_CPT", f"{CANARY}_ICD", f"{CANARY}_DOS"],
            ["2", "100", "1.0", "0.8", "1234567890", "2026-06-10", "CB",
             f"{CANARY}_CPT2", f"{CANARY}_ICD2", f"{CANARY}_DOS2"],
        ],
    )


def _physician_csv() -> bytes:
    return _csv(
        ["NPI", "DocFName", "DocLName", "DocType", "SourceSystem"],
        [["1234567890", "Jane", "Doe", "MD", "CB"]],
    )


def _facility_csv() -> bytes:
    return _csv(
        ["FacilityNo", "FacilityName", "ClientNo", "SourceSystem"],
        [["2289", "HCA Florida Westside Hospital", "100", "CB"]],
    )


def _transactions_csv() -> bytes:
    # HospAcctNo is PHI and NOT in TRANSACTION_ALLOWLIST -> dropped.
    # Invoice 1: payment 150 then a -50 reversal (nets to 100); a 20 payer refund.
    # Invoice 2: payment 80.
    return _csv(
        ["InvoiceNo", "TranType", "TranAmt", "TranSource", "InsuranceClass",
         "TranComment", "PostingDt", "SourceSystem", "HospAcctNo"],
        [
            ["1", "Payment", "150", "Insurance", "Commercial", "Payment",
             "2026-06-10", "CB", f"{CANARY}_ACCT"],
            ["1", "Payment", "-50", "Insurance", "Commercial", "Payment",
             "2026-06-10", "CB", f"{CANARY}_ACCT"],
            ["1", "Refund", "-20", "Insurance", "Commercial", "Refund",
             "2026-06-10", "CB", f"{CANARY}_ACCT"],
            ["2", "Payment", "80", "Insurance", "Medicare", "Payment",
             "2026-06-10", "CB", f"{CANARY}_ACCT2"],
        ],
    )


def _all_files() -> dict[str, bytes]:
    return {
        "Invoice.csv": _invoice_csv(),
        "ChargeLines.csv": _chargelines_csv(),
        "Physician.csv": _physician_csv(),
        "Facility.csv": _facility_csv(),
        "TransactionsAlt.csv": _transactions_csv(),
    }


def _make_zip(files: dict[str, bytes], extra: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# drop_date_from_zip_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("HHA_Extact_20260610.zip", date(2026, 6, 10)),
        ("HHA_Extract_20260610.zip", date(2026, 6, 10)),  # corrected spelling
        ("ventra/stdspec/2026-06-10/HHA_Extact_20260610.zip", date(2026, 6, 10)),
    ],
)
def test_drop_date_from_zip_name(name: str, expected: date) -> None:
    assert drop_date_from_zip_name(name) == expected


def test_drop_date_missing_raises_v1() -> None:
    with pytest.raises(ValidationError) as ei:
        drop_date_from_zip_name("no_date_here.zip")
    assert ei.value.rule == "V1"


def test_drop_date_invalid_calendar_raises_v1() -> None:
    with pytest.raises(ValidationError) as ei:
        drop_date_from_zip_name("HHA_Extact_20261345.zip")  # month 13, day 45
    assert ei.value.rule == "V1"


# ---------------------------------------------------------------------------
# unzip_drop — happy + failure paths
# ---------------------------------------------------------------------------


def test_unzip_happy_path() -> None:
    drop = unzip_drop(_make_zip(_all_files()), ZIP_NAME)
    assert drop.drop_date == DROP
    assert set(drop.file_bytes) == set(_all_files())
    assert len(drop.zip_sha256) == 64
    assert drop.zip_file_name == "HHA_Extact_20260610.zip"
    # data rows (header excluded): invoice 2 + charge 2 + phys 1 + fac 1 + txn 4
    assert drop.total_rows == 10


def test_unzip_tolerates_macos_noise() -> None:
    extra = {"__MACOSX/._Invoice.csv": b"junk", ".DS_Store": b"junk"}
    drop = unzip_drop(_make_zip(_all_files(), extra=extra), ZIP_NAME)
    assert set(drop.file_bytes) == set(_all_files())


def test_unzip_missing_file_raises_v2() -> None:
    files = {k: v for k, v in _all_files().items() if k != "TransactionsAlt.csv"}
    with pytest.raises(ValidationError) as ei:
        unzip_drop(_make_zip(files), ZIP_NAME)
    assert ei.value.rule == "V2"


def test_unzip_unknown_member_raises_v1() -> None:
    with pytest.raises(ValidationError) as ei:
        unzip_drop(_make_zip(_all_files(), extra={"Carrier.csv": b"x\n"}), ZIP_NAME)
    assert ei.value.rule == "V1"


def test_unzip_not_a_zip_raises_v1() -> None:
    with pytest.raises(ValidationError) as ei:
        unzip_drop(b"this is not a zip file", ZIP_NAME)
    assert ei.value.rule == "V1"


def test_unzip_no_date_in_name_raises_v1() -> None:
    with pytest.raises(ValidationError) as ei:
        unzip_drop(_make_zip(_all_files()), "ventra/stdspec/no_date.zip")
    assert ei.value.rule == "V1"


def test_unzip_corrupt_member_fails_closed_v1() -> None:
    raw = bytearray(_make_zip(_all_files()))
    # Flip bytes in the compressed-data region to break a member's CRC /
    # deflate stream. Any decode/decompress failure must map to V1.
    for i in range(60, 160):
        if i < len(raw):
            raw[i] ^= 0xFF
    with pytest.raises(ValidationError) as ei:
        unzip_drop(bytes(raw), ZIP_NAME)
    assert ei.value.rule == "V1"


# ---------------------------------------------------------------------------
# Signed TranAmt — netting + V10 guard
# ---------------------------------------------------------------------------


def _aggregate(files: dict[str, bytes]) -> Aggregator:
    drop = unzip_drop(_make_zip(files), ZIP_NAME)
    agg = Aggregator(drop_date=DROP)
    routing = {
        "invoice": (parse_invoice, agg.process_invoice_row),
        "chargelines": (parse_chargelines, agg.process_chargeline_row),
        "physician": (parse_physician, agg.process_physician_row),
        "facility": (parse_facility, agg.process_facility_row),
        "transactionsalt": (parse_transactions, agg.process_transaction_row),
    }
    for fname, data in drop.file_bytes.items():
        parser, processor = routing[file_stem(fname)]
        for row in parser(data):
            processor(row)
    return agg


def test_signed_payment_reversal_nets() -> None:
    collections, _ar, _phys = _aggregate(_all_files()).emit(FMAP)
    by_payer = {c.payer_class: c for c in collections}
    commercial = by_payer["commercial"]
    # invoice 1: payment 150 + reversal -50 -> net 100; refund -20 -> magnitude 20
    assert commercial.payments_received == Decimal("100")
    assert commercial.payer_refunds == Decimal("20")
    assert commercial.net_revenue == Decimal("80")
    assert commercial.gross_charges == Decimal("200")


def test_ar_open_balance_uses_magnitudes() -> None:
    _collections, ar_rows, _phys = _aggregate(_all_files()).emit(FMAP)
    # Both invoices map to site 1 + age 0 -> the same 0-30 bucket:
    #   invoice 1: 200 charges - 100 payments + 20 refund = 120
    #   invoice 2: 100 charges - 80 payments              =  20
    #   bucket total                                       = 140
    assert any(r.outstanding_amount == Decimal("140") for r in ar_rows), [
        str(r.outstanding_amount) for r in ar_rows
    ]


def test_net_negative_payments_raises_v10() -> None:
    files = dict(_all_files())
    files["TransactionsAlt.csv"] = _csv(
        ["InvoiceNo", "TranType", "TranAmt", "TranSource", "InsuranceClass",
         "TranComment", "PostingDt", "SourceSystem"],
        [
            ["1", "Payment", "50", "Insurance", "Commercial", "Payment",
             "2026-06-10", "CB"],
            ["1", "Payment", "-90", "Insurance", "Commercial", "Payment",
             "2026-06-10", "CB"],
        ],
    )
    with pytest.raises(ValidationError) as ei:
        _aggregate(files).emit(FMAP)
    assert ei.value.rule == "V10"


def test_transfer_is_ignored() -> None:
    files = dict(_all_files())
    files["TransactionsAlt.csv"] = _csv(
        ["InvoiceNo", "TranType", "TranAmt", "TranSource", "InsuranceClass",
         "TranComment", "PostingDt", "SourceSystem"],
        [
            ["1", "Payment", "40", "Insurance", "Commercial", "Payment",
             "2026-06-10", "CB"],
            ["1", "Transfer", "999", "Insurance", "Commercial", "Transfer",
             "2026-06-10", "CB"],
        ],
    )
    collections, _ar, _phys = _aggregate(files).emit(FMAP)
    commercial = next(c for c in collections if c.payer_class == "commercial")
    assert commercial.payments_received == Decimal("40")


# ---------------------------------------------------------------------------
# PHI canary acceptance gate (H18 brought forward)
# ---------------------------------------------------------------------------


def test_phi_canary_present_in_raw_input() -> None:
    # Sanity: the fixture genuinely carries PHI, so the absence test below
    # is meaningful (not passing by an empty fixture).
    blob = b"".join(_all_files().values())
    assert CANARY.encode() in blob


def test_phi_canary_never_reaches_aggregates() -> None:
    agg = _aggregate(_all_files())
    collections, ar_rows, phys_rows = agg.emit(FMAP)

    haystacks: list[str] = []
    for row in (*collections, *ar_rows, *phys_rows):
        haystacks.append(repr(row))
    # The transient join keys + physician directory are internal state, but
    # none should carry a patient canary either.
    haystacks.append(repr(agg.physician_types))

    blob = "\n".join(haystacks)
    assert CANARY not in blob, "PHI canary marker survived into an aggregate"

    # And there should be real, non-empty aggregates (not vacuously clean).
    assert collections, "expected collections aggregates"
    assert phys_rows, "expected physician aggregates"
