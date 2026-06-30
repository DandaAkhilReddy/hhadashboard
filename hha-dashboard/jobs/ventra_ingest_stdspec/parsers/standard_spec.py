"""Streaming Pydantic parsers for Ventra's Standard Data Extract (5 files).

Rewritten 2026-06-16 against Ventra's real spec sheet (``Standard Data
Extract - Files Specifications.xlsx``) after the 2026-06-15 reply. HHA
ingests files 1-4 + 5 (per the locked decision): **Invoice, ChargeLines,
Physician, Facility, TransactionsAlt**. Guarantor (#9) and 6-10 are
declined.

Security posture — ALLOWLIST first (R2). Each parser declares the small
set of non-PHI columns it keeps; ``keep_safe_columns`` drops everything
else BEFORE the row reaches a Pydantic model. A new PHI column Ventra adds
next quarter is dropped by default. The denylist is the defense-in-depth
tripwire behind it.

Join model (from the spec's "File Joins" tab) — handled by the aggregator
(R4), not here:
  Invoice.InvoiceNo  == ChargeLines.InvoiceNo == TransactionsAlt.InvoiceNo
  ChargeLines.PrimaryPhysicianNPI == Physician.NPI
  Invoice.FacilityNo == Facility.FacilityNo
``InvoiceNo`` is a transient in-memory join key — it is KEPT in the parsed
model so the aggregator can correlate files, but it is NEVER persisted to
the DB or written to a log (the aggregate rows carry only date / HHA
site_id / payer_class + Decimal sums).

PHI-handled-elsewhere notes:
  - ``DOS`` (date of service) is PHI — NOT kept. The daily grain + AR aging
    use ``PostingDate`` (when the charge posted) / ``PostingDt`` (when the
    transaction posted), which are operational dates, not clinical.
  - Physician ``DocFName`` / ``DocLName`` are PROVIDER names — Tier-B
    directory data, not patient PHI — so they ARE kept.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic import ValidationError as PydanticValidationError

from ..exceptions import ValidationError
from ..phi import keep_safe_columns

# ============================================================================
# Per-file allowlists — the ONLY columns each parser keeps (normalized:
# lowercased, spaces/hyphens -> underscores). Everything else is dropped by
# keep_safe_columns before Pydantic sees the row.
# ============================================================================

INVOICE_ALLOWLIST = frozenset(
    {"invoiceno", "facilityno", "primaryinsclass", "sourcesystem"}
)
CHARGELINE_ALLOWLIST = frozenset(
    {
        "invoiceno",
        "chargeamt",
        "rvu",
        "workrvu",
        "primaryphysiciannpi",
        "postingdate",
        "arperiod",
        "sourcesystem",
    }
)
PHYSICIAN_ALLOWLIST = frozenset(
    {"npi", "docfname", "doclname", "doctype", "sourcesystem"}
)
FACILITY_ALLOWLIST = frozenset(
    {"facilityno", "facilityname", "clientno", "clientname", "sourcesystem"}
)
TRANSACTION_ALLOWLIST = frozenset(
    {
        "invoiceno",
        "trantype",
        "tranamt",
        "transource",
        "insuranceclass",
        "trancomment",
        "postingdt",
        "bankdepositdt",
        "arperiod",
        "sourcesystem",
    }
)

# Required safe columns per file — their absence in the header means Ventra
# sent the wrong file / changed the format (V5 schema drift). Normalized.
_INVOICE_REQUIRED = frozenset({"invoiceno", "facilityno"})
_CHARGELINE_REQUIRED = frozenset({"invoiceno", "chargeamt"})
_PHYSICIAN_REQUIRED = frozenset({"npi"})
_FACILITY_REQUIRED = frozenset({"facilityno"})
_TRANSACTION_REQUIRED = frozenset({"invoiceno", "trantype", "tranamt"})


# ============================================================================
# Shared coercion helpers
# ============================================================================


def _parse_flex_date(value: object) -> date | None:
    """Coerce Ventra's date/datetime strings to a ``date``.

    Accepts ISO (``2026-06-10``), US slash (``06/10/2026``), and datetime
    forms (``2026-06-10 14:30:00`` / ``2026-06-10T14:30:00``). Empty/None
    returns None. Raises ``ValueError`` on an unparseable non-empty value so
    Pydantic surfaces it as a schema error (V5).
    """
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    if not s:
        return None
    # Take the date portion if a time is appended.
    head = s.replace("T", " ").split(" ", 1)[0]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {head!r}")


def _parse_decimal(value: object) -> Decimal:
    """Coerce a currency/decimal string to ``Decimal``.

    Tolerates ``$``, thousands commas, and parentheses-for-negative
    accounting notation (``(123.45)`` -> ``-123.45``). Empty -> 0.
    """
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    s = str(value).strip()
    if not s:
        return Decimal(0)
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("$", "").replace(",", "").strip()
    if not s:
        return Decimal(0)
    try:
        d = Decimal(s)
    except InvalidOperation as e:
        raise ValueError(f"unparseable decimal: {value!r}") from e
    return -d if neg else d


# ============================================================================
# Row models — only the columns HHA aggregates (+ transient join key)
# ============================================================================


class InvoiceRow(BaseModel):
    """Invoice header — links InvoiceNo -> FacilityNo + payer class.

    Most of Ventra's Invoice file is patient PHI (MRN, Pat*, SSN, policy
    IDs); the allowlist drops all of it. Only the linkage columns survive.
    ``invoice_no`` is the transient join key (never persisted).
    """

    model_config = ConfigDict(extra="ignore", strict=False)

    line_no: int = Field(ge=2)
    invoice_no: int = Field(alias="InvoiceNo", gt=0)
    facility_no: int = Field(alias="FacilityNo", gt=0)
    primary_ins_class: str = Field(alias="PrimaryInsClass", default="")
    source_system: str = Field(alias="SourceSystem", default="")


class ChargeLineRow(BaseModel):
    """Charge line — gross charges + RVU + billed-physician NPI.

    CPT / Modifiers / ICD diagnosis codes / DOS are PHI and dropped by the
    allowlist. ``posting_date`` (operational) drives the date + month +
    aging grain in place of DOS.
    """

    model_config = ConfigDict(extra="ignore", strict=False)

    line_no: int = Field(ge=2)
    invoice_no: int = Field(alias="InvoiceNo", gt=0)
    charge_amt: Decimal = Field(alias="ChargeAmt", default=Decimal(0))
    rvu: Decimal = Field(alias="RVU", default=Decimal(0))
    work_rvu: Decimal = Field(alias="WorkRVU", default=Decimal(0))
    primary_physician_npi: str = Field(alias="PrimaryPhysicianNPI", default="")
    posting_date: date | None = Field(alias="PostingDate", default=None)
    ar_period: int | None = Field(alias="ARPeriod", default=None)
    source_system: str = Field(alias="SourceSystem", default="")

    @field_validator("charge_amt", "rvu", "work_rvu", mode="before")
    @classmethod
    def _coerce_decimal(cls, v: object) -> Decimal:
        return _parse_decimal(v)

    @field_validator("posting_date", mode="before")
    @classmethod
    def _coerce_date(cls, v: object) -> date | None:
        return _parse_flex_date(v)

    @field_validator("primary_physician_npi")
    @classmethod
    def _validate_npi(cls, v: str) -> str:
        v = (v or "").strip()
        if v and not (len(v) == 10 and v.isdigit()):
            raise ValueError(f"V11: NPI not 10 digits: {len(v)} chars")
        return v


class PhysicianRow(BaseModel):
    """Physician reference — NPI -> provider name + type. Tier-B directory."""

    model_config = ConfigDict(extra="ignore", strict=False)

    line_no: int = Field(ge=2)
    npi: str = Field(alias="NPI", default="")
    doc_fname: str = Field(alias="DocFName", default="")
    doc_lname: str = Field(alias="DocLName", default="")
    doc_type: str = Field(alias="DocType", default="")
    source_system: str = Field(alias="SourceSystem", default="")


class FacilityRow(BaseModel):
    """Facility reference — FacilityNo -> name + client. Non-PHI reference."""

    model_config = ConfigDict(extra="ignore", strict=False)

    line_no: int = Field(ge=2)
    facility_no: int = Field(alias="FacilityNo", gt=0)
    facility_name: str = Field(alias="FacilityName", default="")
    client_no: int | None = Field(alias="ClientNo", default=None)
    client_name: str = Field(alias="ClientName", default="")
    source_system: str = Field(alias="SourceSystem", default="")


class TransactionRow(BaseModel):
    """Transaction — payment / adjustment / refund. THE collections source.

    ``tran_type`` in {Payment, Adjustment, Refund, Transfer}; ``tran_source``
    in {Patient, Insurance}; ``tran_comment`` carries the adjustment subtype
    (Contract Adjustment, Bad Debt Adjustment, ...). The aggregator maps
    these to payments / contractual_adjustments / write_offs / refunds.
    """

    model_config = ConfigDict(extra="ignore", strict=False)

    line_no: int = Field(ge=2)
    invoice_no: int = Field(alias="InvoiceNo", gt=0)
    tran_type: str = Field(alias="TranType", default="")
    tran_amt: Decimal = Field(alias="TranAmt", default=Decimal(0))
    tran_source: str = Field(alias="TranSource", default="")
    insurance_class: str = Field(alias="InsuranceClass", default="")
    tran_comment: str = Field(alias="TranComment", default="")
    posting_dt: date | None = Field(alias="PostingDt", default=None)
    bank_deposit_dt: date | None = Field(alias="BankDepositDt", default=None)
    ar_period: int | None = Field(alias="ARPeriod", default=None)
    source_system: str = Field(alias="SourceSystem", default="")

    @field_validator("tran_amt", mode="before")
    @classmethod
    def _coerce_decimal(cls, v: object) -> Decimal:
        return _parse_decimal(v)

    @field_validator("posting_dt", "bank_deposit_dt", mode="before")
    @classmethod
    def _coerce_date(cls, v: object) -> date | None:
        return _parse_flex_date(v)


# ============================================================================
# Payer-class normalizer
# ============================================================================

_PAYER_CLASSES = frozenset(
    {"commercial", "medicare", "medicaid", "selfpay", "other"}
)


def normalize_payer_class(raw: str) -> str:
    """Map a free-text Ventra InsClass / InsuranceClass to HHA's payer set.

    HHA's fact tables CHECK payer_class in {commercial, medicare, medicaid,
    selfpay, other}. Ventra ships a free string whose exact vocabulary is
    NOT in the spec sheet — this heuristic is conservative (default
    ``other``) and MUST be confirmed against the first real sample drop
    (tracked in the Ventra reply's clarification asks).
    """
    s = (raw or "").strip().lower()
    if not s:
        return "other"
    if "medicare" in s:
        return "medicare"
    if "medicaid" in s:
        return "medicaid"
    if "self" in s or s in {"sp", "pat", "patient"}:
        return "selfpay"
    if "commercial" in s or "comm" in s:
        return "commercial"
    return "other"


# ============================================================================
# Streaming generators
# ============================================================================


def _decode(data: bytes, file_name: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValidationError(
            rule="V5",
            safe_message=f"{file_name} is not valid UTF-8",
            internal_details={"file_name": file_name, "decode_error": str(e)},
        ) from e


def _validate_header(
    fieldnames: list[str] | None, file_name: str, required: frozenset[str]
) -> None:
    """V5 — header must exist and contain every required SAFE column.

    Note we assert on SAFE columns now (not "PHI present"): a header missing
    ``InvoiceNo``/``FacilityNo``/etc. is the wrong file or a format change.
    """
    if not fieldnames:
        raise ValidationError(
            rule="V5",
            safe_message=f"{file_name} is empty (no header row)",
            internal_details={"file_name": file_name},
        )
    normalized = {f.strip().lower().replace("-", "_").replace(" ", "_") for f in fieldnames}
    missing = required - normalized
    if missing:
        raise ValidationError(
            rule="V5",
            safe_message=f"{file_name} header missing required columns",
            internal_details={
                "file_name": file_name,
                "missing_required": sorted(missing),
                "header_column_count": len(fieldnames),
            },
        )


def _stream(
    data: bytes,
    file_name: str,
    allowlist: frozenset[str],
    required: frozenset[str],
    model: type[BaseModel],
) -> Iterator[BaseModel]:
    """Shared per-row loop: decode -> header check -> allowlist-strip ->
    model -> yield. PHI is stripped BEFORE the model sees the row; Pydantic
    errors carry loc + type only, never the raw value."""
    text = _decode(data, file_name)
    reader = csv.DictReader(io.StringIO(text))
    _validate_header(reader.fieldnames, file_name, required)

    for line_no, raw_row in enumerate(reader, start=2):
        kept, _dropped = keep_safe_columns(raw_row, allowlist)
        kept["line_no"] = line_no
        try:
            yield model(**kept)
        except PydanticValidationError as pe:
            raise ValidationError(
                rule="V5",
                safe_message=f"{file_name} line {line_no} schema mismatch",
                internal_details={
                    "file_name": file_name,
                    "line_no": line_no,
                    "errors": [
                        {
                            "loc": list(e["loc"]),
                            "type": e["type"],
                            "msg_head": str(e.get("msg", "")).split(":", 1)[0],
                        }
                        for e in pe.errors()
                    ],
                },
            ) from pe


def parse_invoice(data: bytes, file_name: str = "Invoice.csv") -> Iterator[InvoiceRow]:
    """Stream Invoice rows (InvoiceNo -> FacilityNo + payer linkage)."""
    yield from _stream(data, file_name, INVOICE_ALLOWLIST, _INVOICE_REQUIRED, InvoiceRow)  # type: ignore[misc]


def parse_chargelines(
    data: bytes, file_name: str = "ChargeLines.csv"
) -> Iterator[ChargeLineRow]:
    """Stream ChargeLine rows (charges + RVU + billed NPI)."""
    yield from _stream(data, file_name, CHARGELINE_ALLOWLIST, _CHARGELINE_REQUIRED, ChargeLineRow)  # type: ignore[misc]


def parse_physician(
    data: bytes, file_name: str = "Physician.csv"
) -> Iterator[PhysicianRow]:
    """Stream Physician reference rows (NPI -> name + type)."""
    yield from _stream(data, file_name, PHYSICIAN_ALLOWLIST, _PHYSICIAN_REQUIRED, PhysicianRow)  # type: ignore[misc]


def parse_facility(
    data: bytes, file_name: str = "Facility.csv"
) -> Iterator[FacilityRow]:
    """Stream Facility reference rows (FacilityNo -> name + client)."""
    yield from _stream(data, file_name, FACILITY_ALLOWLIST, _FACILITY_REQUIRED, FacilityRow)  # type: ignore[misc]


def parse_transactions(
    data: bytes, file_name: str = "TransactionsAlt.csv"
) -> Iterator[TransactionRow]:
    """Stream Transaction rows (payments / adjustments / refunds)."""
    yield from _stream(data, file_name, TRANSACTION_ALLOWLIST, _TRANSACTION_REQUIRED, TransactionRow)  # type: ignore[misc]


__all__ = [
    "ChargeLineRow",
    "FacilityRow",
    "InvoiceRow",
    "PhysicianRow",
    "TransactionRow",
    "normalize_payer_class",
    "parse_chargelines",
    "parse_facility",
    "parse_invoice",
    "parse_physician",
    "parse_transactions",
]
