"""Structlog configuration with HIPAA-conscious PII redaction.

Defense-in-depth: even though no production code today logs raw user data,
a careless `log.info("user", **user.model_dump())` would dump UPN + email
into Log Analytics. The redaction processor below catches that case.

What's redacted:
- Anything matching common credential / token / session key names.
- Anything matching directory keys (email, upn).
- Anything matching forbidden PHI keys (mrn, patient_*, etc — same list as
  test_schema_classification.py FORBIDDEN_COLUMN_NAMES).

What's NOT redacted:
- Aggregate metrics (counts, percentages, timestamps).
- Operational identifiers (correlation_id, request_id).
- HHA staff first names / site names (deliberately public).
"""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any

import structlog

# Keys whose values must never end up in logs. Match is case-insensitive
# and prefix-based — `patient_dob` is caught by `patient_`, `Authorization`
# by `authorization`. Order doesn't matter; redaction is one pass.
_REDACTED_KEY_PATTERNS: tuple[str, ...] = (
    # Credentials / sessions
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "auth_header",
    "cookie",
    "session",
    "api_key",
    "apikey",
    "client_secret",
    "private_key",
    "access_key",
    # Directory PII
    "email",
    "upn",
    "preferred_username",
    "user_email",
    # PHI / forbidden columns (mirror test_schema_classification.py)
    "mrn",
    "member_id",
    "subscriber_id",
    "subscriber_name",
    "guarantor_id",
    "guarantor_name",
    "policy_number",
    "patient_",
    "claim_id",
    "encounter_id",
)

_REDACTED_VALUE = "[REDACTED]"


def _redact_pii_processor(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor — walks the event dict once and redacts values for
    any key matching `_REDACTED_KEY_PATTERNS`.

    Recursive into dicts so nested structures (e.g., `request={"headers": {...}}`)
    don't bypass redaction. Lists are handled by recursing into dict elements;
    string-only lists pass through unchanged.
    """
    return _redact_dict(dict(event_dict))


def _redact_dict(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        k_lower = str(k).lower()
        if _is_pii_key(k_lower):
            out[k] = _REDACTED_VALUE
        elif isinstance(v, dict):
            out[k] = _redact_dict(v)
        elif isinstance(v, list):
            out[k] = [_redact_dict(x) if isinstance(x, dict) else x for x in v]
        else:
            out[k] = v
    return out


def _is_pii_key(key_lower: str) -> bool:
    return any(pattern in key_lower for pattern in _REDACTED_KEY_PATTERNS)


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog for JSON output (prod) or console (dev via LOG_LEVEL=DEBUG).

    The `_redact_pii_processor` runs FIRST in the chain so downstream processors
    (TimeStamper, JSONRenderer) only ever see redacted dicts.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", level=log_level)

    structlog.configure(
        processors=[
            _redact_pii_processor,  # runs first — defense in depth
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
