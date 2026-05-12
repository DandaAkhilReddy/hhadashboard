"""Shared per-row CSV parse loop with Pydantic → ValidationError mapping.

Every per-file parser in this package follows the same shape: decode
UTF-8, DictReader over rows, instantiate a per-file Pydantic model, wrap
any error as our ``jobs.ventra_ingest.exceptions.ValidationError`` with
the right V-rule label. This module owns that loop so the per-file
parsers stay tiny.

V-rule routing: model_validators on the per-file Pydantic models raise
``ValueError`` with a literal ``'V7:'`` / ``'V9:'`` / ``'V10:'`` / ``'V11:'``
prefix. Pydantic wraps each as ``{"msg": "Value error, V10: ..."}``; we
strip the Pydantic prefix and check the rule prefix. Anything that does
not match falls through to V5 (schema / type / unknown column).
"""

from __future__ import annotations

import csv
import io
from typing import TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from ..exceptions import ValidationError

T = TypeVar("T", bound=BaseModel)


# Rule prefixes our model_validators emit. Order does not matter — the
# first match wins per row.
_RULE_PREFIXES = ("V7", "V9", "V10", "V11")


def _classify_rule(pe: PydanticValidationError) -> str:
    """Inspect each pydantic error and map back to a V-rule.

    Returns ``'V5'`` as the catch-all for schema / type / unknown-column
    issues — everything not raised by a model_validator with the known
    prefix.
    """
    for err in pe.errors():
        msg = err.get("msg", "")
        # Pydantic v2 prefixes value-error messages with "Value error, ".
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, "):]
        for prefix in _RULE_PREFIXES:
            if msg.startswith(f"{prefix}:"):
                return prefix
    return "V5"


def parse_csv_rows(
    data: bytes, model: type[T], file_name: str
) -> list[T]:
    """Decode UTF-8, parse CSV with header, instantiate ``model`` per row.

    Raises ``ValidationError(rule='V5', ...)`` for:
      - UTF-8 decode failure
      - empty file (no header)
      - any row that fails Pydantic schema validation (unknown column with
        ``extra='forbid'``, missing required column, type mismatch)

    Raises ``ValidationError(rule=<V7|V9|V10|V11>, ...)`` when the row
    parses structurally but a model_validator rejects it.

    Returns: a list of validated row models. The list may be empty if
    the file has only a header — V5 only enforces presence of the header
    row; emptiness of data is allowed (some files only exist on
    month-close days, etc.).
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValidationError(
            rule="V5",
            message=f"{file_name} is not valid UTF-8",
            details={"decode_error": str(e)},
        ) from e

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValidationError(
            rule="V5",
            message=f"{file_name} is empty (no header row)",
        )

    rows: list[T] = []
    for line_no, raw_row in enumerate(reader, start=2):  # 1 = header
        try:
            rows.append(model(**raw_row))
        except PydanticValidationError as pe:
            rule = _classify_rule(pe)
            raise ValidationError(
                rule=rule,
                message=f"{file_name} line {line_no} failed {rule}",
                details={
                    "line_no": line_no,
                    "file_name": file_name,
                    "row": {k: v for k, v in raw_row.items() if v is not None},
                    "errors": [
                        {
                            "loc": list(e["loc"]),
                            "msg": e["msg"],
                            "type": e["type"],
                        }
                        for e in pe.errors()
                    ],
                },
            ) from pe

    return rows
