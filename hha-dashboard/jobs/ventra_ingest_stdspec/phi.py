"""PHI denial + redaction for the row-level Ventra ingest pipeline.

This module is the security boundary for ADR-001 in the row-level path.
Every other module in ``jobs/ventra_ingest_stdspec/`` defers to these
functions before any data flows to a sink (DB, log, telemetry, email,
quarantine sidecar).

Three layers of defense in this file:

  1. **Forbidden-column denial** — ``is_forbidden_column()`` answers
     "is this column name something HHA must never store?". Backed by
     ``FORBIDDEN_COLUMN_EXACT`` (literal denylist) + ``FORBIDDEN_COLUMN_PATTERNS``
     (regex for unknown variants like ``patient_dob_alt`` or
     ``guarantor_address_line_3``). Case-insensitive, underscore-vs-hyphen
     tolerant.

  2. **Strip** — ``strip_phi_columns()`` takes a parsed row dict and
     returns a NEW dict with every forbidden key removed. The original
     dict is not mutated; the strip event is counted so the caller can
     emit a telemetry value for forensic forensics.

  3. **Value-level scrub** — ``scrub_value()`` redacts substrings that
     LOOK like PHI even when the column name doesn't trigger the denial
     (e.g. a free-text comment field that contains an SSN). Used by the
     structlog processor in ``logging.py`` for output redaction.

The denylist mirrors ADR-001's column-name forbidden list verbatim,
extended with the row-level Standard Spec column families Ventra's
spec sheet documents. Every addition to this file requires an ADR
update — security-critical surface.
"""

from __future__ import annotations

import re
from typing import Any

# ============================================================================
# Layer 1 — Forbidden column denial
# ============================================================================

# Exact literal names that may NEVER reach HHA's DB / logs / telemetry.
# Mirrors ADR-001's denylist plus the row-level extensions from Ventra's
# Standard Spec. All keys are pre-lowercased; the matcher normalizes the
# input before comparing.
FORBIDDEN_COLUMN_EXACT: frozenset[str] = frozenset(
    {
        # ADR-001 baseline.
        "claim_id",
        "encounter_id",
        "mrn",
        "member_id",
        "dos",
        "dos_per_line",
        "cpt_per_line",
        # Ventra Standard Spec — patient identifiers.
        "patient_id",
        "patient_name",
        "patient_first_name",
        "patient_last_name",
        "patient_middle_name",
        "patient_dob",
        "patient_ssn",
        "patient_phone",
        "patient_email",
        "patient_address",
        "patient_address_line_1",
        "patient_address_line_2",
        "patient_city",
        "patient_state",
        "patient_zip",
        "patient_zipcode",
        "patient_postal_code",
        # Ventra Standard Spec — guarantor identifiers.
        "guarantor_id",
        "guarantor_name",
        "guarantor_first_name",
        "guarantor_last_name",
        "guarantor_dob",
        "guarantor_ssn",
        "guarantor_phone",
        "guarantor_email",
        "guarantor_address",
        "guarantor_address_line_1",
        "guarantor_address_line_2",
        # Ventra Standard Spec — subscriber identifiers (insurance).
        "subscriber_id",
        "subscriber_name",
        "subscriber_first_name",
        "subscriber_last_name",
        "subscriber_dob",
        "subscriber_ssn",
        "subscriber_member_id",
        # Generic 18-HIPAA-identifier set.
        "ssn",
        "social_security_number",
        "dob",
        "date_of_birth",
        "drivers_license",
        "drivers_license_number",
        "biometric_id",
        "device_id",
        "ip_address",
        "url",
        "face_photo",
        "fingerprint",
    }
)

# Explicit allowlist for aggregate column names that LOOK like PHI by
# pattern but are confirmed Tier-A aggregates by ADR-001 schema review.
# These bypass both the exact denylist and the regex patterns. Every
# entry here requires a sign-off from the data-classification reviewer:
#
#   ``patient_refunds``  — aggregate $ amount refunded to patients
#                          across the (date, facility, payer) group.
#                          No patient identifier; just a sum.
#
# Adding to this set is a one-way door — undoing it would re-classify a
# column as PHI and require migration. Treat as security-critical.
KNOWN_SAFE_AGGREGATE_COLUMNS: frozenset[str] = frozenset(
    {
        "patient_refunds",
    }
)

# Regex patterns to catch unknown variants. Each pattern is anchored on
# the full normalized column name (no partial matches against legitimate
# names like ``payer_class`` or ``facility_no``). The matcher applies
# these AFTER the exact set misses AND after the allowlist bypass.
FORBIDDEN_COLUMN_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Anything starting with patient_, guarantor_, subscriber_ that's not
    # already in the exact list above.
    re.compile(r"^patient_.+$"),
    re.compile(r"^guarantor_.+$"),
    re.compile(r"^subscriber_.+$"),
    # Common email/phone/address variants Ventra might rename.
    re.compile(r".*_email(?:_address)?$"),
    re.compile(r".*_phone(?:_number)?$"),
    re.compile(r".*_ssn$"),
    re.compile(r".*_dob$"),
    re.compile(r".*_(?:home|cell|mobile|work)_phone$"),
    # Name fields that are not the physician name we DO allow.
    # ``physician_name`` is NOT forbidden — it's a Tier-B directory field.
    # Other ``*_name`` variants are.
    re.compile(r"^(?:patient|guarantor|subscriber|member)_.*name$"),
)


def _normalize_column(name: str) -> str:
    """Lowercase + replace hyphens with underscores.

    Ventra's CSVs vary in their column casing across files; HHA accepts
    any common variant and normalizes before matching. Hyphens are
    treated as underscores so ``patient-dob`` and ``patient_dob`` collide.
    """
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def is_forbidden_column(name: str) -> bool:
    """True when ``name`` matches the denylist or a forbidden regex.

    Case-insensitive, underscore-vs-hyphen tolerant. The check runs
    against every column the parsers see — once per file at parse-time
    (V15 layer 1: pre-strip sanity) and again per record after strip
    (V15 layer 2: post-strip assertion).

    Resolution order:
      1. Known-safe aggregate allowlist (``patient_refunds``, etc.) →
         not forbidden.
      2. Exact denylist match → forbidden.
      3. Regex pattern match → forbidden.
      4. Otherwise → not forbidden.
    """
    norm = _normalize_column(name)
    if norm in KNOWN_SAFE_AGGREGATE_COLUMNS:
        return False
    if norm in FORBIDDEN_COLUMN_EXACT:
        return True
    return any(pattern.match(norm) for pattern in FORBIDDEN_COLUMN_PATTERNS)


# ============================================================================
# Layer 2 — Strip
# ============================================================================


def strip_phi_columns(row: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Return a new dict with every PHI column removed + the list of
    column names that were stripped.

    The original ``row`` is NOT mutated — callers can rely on the input
    surviving the call. The returned list of stripped column names is
    counted into telemetry by the aggregator (``ventra_stdspec.phi_columns_stripped``
    event with the column count) for forensic visibility, never the
    values themselves.

    Raises ``ValueError`` if ``row`` is not a dict-like mapping — defensive
    against parser bugs that might pass a list/tuple.
    """
    if not isinstance(row, dict):
        raise ValueError(
            f"strip_phi_columns expects a dict; got {type(row).__name__}"
        )
    stripped: list[str] = []
    out: dict[str, Any] = {}
    for key, value in row.items():
        if is_forbidden_column(key):
            stripped.append(_normalize_column(key))
            continue
        out[key] = value
    return out, stripped


def assert_no_phi_columns(row: dict[str, Any]) -> None:
    """Raise ``PHILeakError`` if any key in ``row`` is forbidden.

    Called at V15 layer 2 (after strip — should be unreachable) and
    layer 4 (pre-DB-write). Any hit is a code bug, not a data quality
    issue, and routes to the incident path in ``main.py``.
    """
    # Local import to avoid the exceptions module having a cycle through
    # phi for any future utility.
    from .exceptions import PHILeakError

    offenders = [k for k in row if is_forbidden_column(k)]
    if offenders:
        raise PHILeakError(
            layer="post_strip" if len(offenders) == 1 else "post_strip_multi",
            safe_message=f"{len(offenders)} forbidden column(s) survived strip",
            internal_details={
                "offending_columns": [_normalize_column(c) for c in offenders],
            },
        )


# ============================================================================
# Layer 3 — Value-level scrub for free-text fields
# ============================================================================

# Value-level regex patterns. Used by ``scrub_value()`` to redact PHI-shaped
# substrings inside string values (the column-name denylist catches the
# obvious cases; this catches a comment field that happens to contain a
# raw SSN or DOB).
PHI_VALUE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # SSN: NNN-NN-NNNN with optional separators.
    (re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"), "[REDACTED:SSN]"),
    # Phone: US 10-digit, parenthesized or dashed.
    (
        re.compile(r"\(?\d{3}\)?[-\.\s]?\d{3}[-\.\s]?\d{4}\b"),
        "[REDACTED:PHONE]",
    ),
    # DOB: YYYY-MM-DD or MM/DD/YYYY.
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "[REDACTED:DATE]"),
    (re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b"), "[REDACTED:DATE]"),
    # Email.
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED:EMAIL]",
    ),
)


def scrub_value(value: Any) -> Any:
    """Return ``value`` with PHI-shaped substrings replaced by markers.

    Non-string values pass through unchanged. The structlog processor in
    ``logging.py`` calls this on every leaf value before serialization,
    so even a record key that wasn't on the denylist gets its values
    scrubbed of accidental PHI leakage.

    Notes:
      - Date redaction is aggressive (any YYYY-MM-DD or MM/DD/YYYY string).
        This is intentional — we'd rather scrub a benign drop_date in a
        log line than miss a patient DOB. Log readers can recover the
        drop_date from the structured ``drop_date`` field that the
        aggregator emits with the column name (whitelisted at higher
        scrub-bypass layers in ``logging.py``).
      - The function operates on a single value, not a record. Use
        ``scrub_record()`` to walk a nested mapping.
    """
    if not isinstance(value, str):
        return value
    out = value
    for pattern, replacement in PHI_VALUE_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def scrub_record(record: dict[str, Any]) -> dict[str, Any]:
    """Recursively scrub every string value in a mapping.

    Used by ``logging.py``'s structlog processor. Walks one level deep
    into nested dicts (sufficient for typical log payloads). Lists and
    tuples are scrubbed element-wise.
    """
    out: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, dict):
            out[key] = scrub_record(value)
        elif isinstance(value, (list, tuple)):
            out[key] = type(value)(scrub_value(v) for v in value)
        else:
            out[key] = scrub_value(value)
    return out


__all__ = [
    "FORBIDDEN_COLUMN_EXACT",
    "FORBIDDEN_COLUMN_PATTERNS",
    "KNOWN_SAFE_AGGREGATE_COLUMNS",
    "PHI_VALUE_PATTERNS",
    "assert_no_phi_columns",
    "is_forbidden_column",
    "scrub_record",
    "scrub_value",
    "strip_phi_columns",
]
