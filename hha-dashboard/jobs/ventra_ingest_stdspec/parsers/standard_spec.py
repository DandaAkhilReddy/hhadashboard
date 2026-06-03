"""Streaming Pydantic parsers for the Standard Spec Invoice + Guarantor CSVs.

V15 layer 1 (pre-strip sanity) lives here: the header is inspected to
confirm Ventra is sending columns that LOOK like the Standard Spec we
expected (e.g. ``patient_id`` present in invoice.csv, ``guarantor_id``
present in guarantor.csv). Absence raises V5 (schema drift); the
operator coordinates with Ventra to confirm the file shape before
flipping the feed back on.

V15 layer 2 (post-strip assertion) is delegated to
``jobs.ventra_ingest_stdspec.phi.assert_no_phi_columns()`` and runs in
the aggregator (H9) on the dict that comes out of ``strip_phi_columns``.
The parser's responsibility is to (a) confirm presence of the expected
PHI columns in the raw header, (b) strip them, (c) produce a Pydantic
model from only the non-PHI fields HHA actually consumes.

Streaming contract:
  - ``parse_invoice(stream)`` and ``parse_guarantor(stream)`` are
    generators. The caller can break out early without exhausting the
    file (useful for unit tests).
  - Each yielded model carries the line number (1-indexed) for error
    correlation. A V5 ValidationError mid-stream raises immediately;
    the caller's outer try/except routes to quarantine.
  - The bytes-to-text decode is wrapped per row so a partial UTF-8 corrupt
    file fails on the corrupt row, not at the top.

PHI-safety contract:
  - The raw CSV row dict (which contains PHI columns) lives in memory
    for exactly one function call: ``strip_phi_columns(raw_row)``.
    After that, the stripped dict is what gets passed to the Pydantic
    model.
  - On ValidationError, the error's ``internal_details`` contains line
    number + file name + the SAFE columns that failed (never the
    stripped-out PHI columns and never the raw values).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from ..exceptions import ValidationError
from ..phi import is_forbidden_column, strip_phi_columns

# Pre-strip sanity — the columns HHA expects Ventra to send PHI in.
# If NONE of these are present in invoice.csv's header, the file is
# almost certainly not the Standard Spec (or Ventra changed the format
# without notice). Raise V5 — the operator coordinates with Ventra
# before re-enabling the feed.
_INVOICE_EXPECTED_PHI_PRESENT_HEADER_HINTS: frozenset[str] = frozenset(
    {"patient_id", "patient_name", "patient_dob", "subscriber_id"}
)
_GUARANTOR_EXPECTED_PHI_PRESENT_HEADER_HINTS: frozenset[str] = frozenset(
    {"guarantor_id", "guarantor_name", "guarantor_dob"}
)


# ============================================================================
# Invoice — the source of all 3 fact aggregates
# ============================================================================


class InvoiceRow(BaseModel):
    """One invoice/encounter line from Ventra's Standard Spec.

    Only the columns HHA actually aggregates are modeled — every PHI
    field Ventra sends is stripped before this model sees the dict.
    ``extra='ignore'`` is the belt-and-suspenders fallback in case a
    new non-PHI column slips through; the aggregator never touches
    fields not in this model.

    The ``line_no`` field is set by the parser, not parsed from CSV —
    it's the 1-indexed line number in the source file for forensic
    correlation.
    """

    model_config = ConfigDict(extra="ignore", strict=False)

    # 1-indexed line number set by the parser (NOT from CSV).
    line_no: int = Field(ge=2)  # header is line 1

    # Aggregation keys.
    service_date: date
    facility_no: int = Field(gt=0)
    payer_class: Literal[
        "commercial", "medicare", "medicaid", "selfpay", "other"
    ]

    # Money fields — must parse as Decimal, NEVER float.
    gross_charges: Decimal = Field(ge=0)
    payments_received: Decimal = Field(ge=0)
    contractual_adjustments: Decimal = Decimal(0)
    write_offs: Decimal = Decimal(0)
    payer_refunds: Decimal = Decimal(0)
    patient_refunds: Decimal = Decimal(0)

    # Physician attribution (rendering provider, NOT supervising).
    # Required so the aggregator can build fact_revenue_by_physician_mo.
    # NPI is Tier-B per ADR-001 (directory data, not PHI), so it stays
    # in the model — not on the PHI denylist.
    rendering_npi: str = Field(pattern=r"^[0-9]{10}$")

    # RVU fields for the physician-monthly aggregate.
    total_rvu: Decimal = Field(ge=0, default=Decimal(0))
    work_rvu: Decimal = Field(ge=0, default=Decimal(0))

    # AR-aging context — Ventra sends per-line outstanding amount + how
    # many days since service. The aggregator buckets these for the AR
    # snapshot.
    outstanding_amount: Decimal = Decimal(0)
    days_since_service: int = Field(ge=0, default=0)

    # Ventra's PM-system identifier (CB / MGS / VSQL / DUVA). Tier-A
    # forensic value; we accept anything but the writer discards it
    # (DB CHECK locks source_system to VENTRA_FL_STDSPEC_AGG).
    vendor_source_system: str = ""


# ============================================================================
# Guarantor — present for V15 sanity; not consumed by aggregator
# ============================================================================


class GuarantorRow(BaseModel):
    """One guarantor record from Ventra's Standard Spec.

    HHA does not aggregate guarantor data — the file is parsed only to
    confirm V15 layer 1 (the expected PHI columns are present, so we
    know we're reading the right format). All useful fields are PHI
    and stripped at the parser layer; only the row count survives to
    the aggregator (for V4 / V13 dedup arithmetic).
    """

    model_config = ConfigDict(extra="ignore", strict=False)

    line_no: int = Field(ge=2)

    # The only non-PHI column we read — the facility this guarantor is
    # associated with. Used to confirm V12 (FL-only invariant) extends
    # consistently across both files.
    facility_no: int = Field(gt=0)


# ============================================================================
# Streaming generators
# ============================================================================


def _validate_header(
    fieldnames: list[str] | None,
    file_name: str,
    expected_phi_hints: frozenset[str],
) -> None:
    """V5 + V15-layer-1 header sanity.

    Raises ``ValidationError(rule='V5')`` if:
      - the file has no header
      - none of the expected PHI columns are present (Ventra changed
        the format)
    """
    if not fieldnames:
        raise ValidationError(
            rule="V5",
            safe_message=f"{file_name} is empty (no header row)",
            internal_details={"file_name": file_name},
        )

    normalized = {f.strip().lower().replace("-", "_") for f in fieldnames}
    if not (normalized & expected_phi_hints):
        # None of the expected PHI columns are present — Ventra is
        # sending something other than the Standard Spec. Refuse the
        # file rather than guess at the new shape.
        raise ValidationError(
            rule="V5",
            safe_message=(
                f"{file_name} header missing all expected hint columns; "
                f"vendor schema appears to have drifted"
            ),
            internal_details={
                "file_name": file_name,
                # Column NAMES only (not values) are safe to log.
                "header_columns_count": len(fieldnames),
                "header_phi_hint_match_count": 0,
            },
        )


def _decode_stream(data: bytes, file_name: str) -> str:
    """UTF-8 decode the file bytes; raise V5 on failure."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValidationError(
            rule="V5",
            safe_message=f"{file_name} is not valid UTF-8",
            internal_details={"file_name": file_name, "decode_error": str(e)},
        ) from e


def parse_invoice(data: bytes, file_name: str = "invoice.csv") -> Iterator[InvoiceRow]:
    """Stream-parse Ventra's invoice.csv, yielding ``InvoiceRow`` per row.

    The generator's first action is to validate the header (V5 + V15
    layer 1). If that passes, each row is:
      1. Loaded as a dict by csv.DictReader.
      2. Stripped of every PHI column by ``strip_phi_columns``.
      3. The line number injected as ``line_no``.
      4. Instantiated as ``InvoiceRow`` (Pydantic).
      5. Yielded to the caller.

    Pydantic errors on a row raise ``ValidationError(rule='V5')`` with a
    safe internal_details payload (line number + file name + Pydantic's
    error structure — keys + types, never values).
    """
    text = _decode_stream(data, file_name)
    reader = csv.DictReader(io.StringIO(text))
    _validate_header(
        reader.fieldnames,
        file_name,
        _INVOICE_EXPECTED_PHI_PRESENT_HEADER_HINTS,
    )

    for line_no, raw_row in enumerate(reader, start=2):
        stripped, _stripped_cols = strip_phi_columns(raw_row)
        stripped["line_no"] = line_no
        try:
            yield InvoiceRow(**stripped)
        except PydanticValidationError as pe:
            # PHI-safe error payload — Pydantic's errors carry loc + type
            # which are column names + Pydantic types (e.g. "decimal_parsing").
            # NEVER include the raw input value here.
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
                            # ``msg`` may carry the input value in some
                            # Pydantic error types — sanitize by extracting
                            # only the leading sentence (everything before
                            # the first colon).
                            "msg_head": str(e.get("msg", "")).split(":", 1)[0],
                        }
                        for e in pe.errors()
                    ],
                },
            ) from pe


def parse_guarantor(
    data: bytes, file_name: str = "guarantor.csv"
) -> Iterator[GuarantorRow]:
    """Stream-parse Ventra's guarantor.csv, yielding ``GuarantorRow`` per row.

    The guarantor file is parsed mostly for V15 sanity and row-count
    arithmetic — the aggregator does not consume guarantor data. PHI
    columns are stripped at the parser layer; only ``facility_no``
    survives into the model.
    """
    text = _decode_stream(data, file_name)
    reader = csv.DictReader(io.StringIO(text))
    _validate_header(
        reader.fieldnames,
        file_name,
        _GUARANTOR_EXPECTED_PHI_PRESENT_HEADER_HINTS,
    )

    for line_no, raw_row in enumerate(reader, start=2):
        stripped, _stripped_cols = strip_phi_columns(raw_row)
        stripped["line_no"] = line_no
        try:
            yield GuarantorRow(**stripped)
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


def check_invoice_header_has_no_unstripped_phi(fieldnames: list[str]) -> list[str]:
    """Sanity helper for tests + manifest checking.

    Returns the list of header columns that are PHI per the denylist.
    Used by H18's CI smoke test to confirm the PHI denial layer correctly
    identifies every column the fixture marks as ``PHI_CANARY_*``.
    """
    return [name for name in fieldnames if is_forbidden_column(name)]


__all__ = [
    "GuarantorRow",
    "InvoiceRow",
    "check_invoice_header_has_no_unstripped_phi",
    "parse_guarantor",
    "parse_invoice",
]
