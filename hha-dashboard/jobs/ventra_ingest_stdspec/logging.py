"""PHI-safe structlog pipeline for the row-level ingest job.

Wraps ``app.core.logging.configure_logging()`` (which sets up the base
JSON pipeline + contextvar merge) with two additional processors:

  1. ``redact_phi_keys`` — drops any key whose name matches the
     forbidden-column denylist in ``phi.py``. Catches the obvious
     accidental ``log.info("processed", patient_id=...)`` shape.

  2. ``scrub_phi_values`` — runs ``phi.scrub_record()`` over every log
     record so SSN-shaped / DOB-shaped / email-shaped substrings in any
     value get replaced with redaction markers before serialization.

The processors run AFTER the structlog formatter has the dict built but
BEFORE the JSON encoder. Any caller that bypasses structlog (e.g. raw
``print()``, raw ``logging.Logger``) escapes this scrub — the project's
ruff config bans both in jobs/.

Test contract: ``api/tests/test_ventra_stdspec_logging.py`` (H13 sibling)
asserts that a known PHI canary (``PHI_CANARY_SSN``, ``PHI_CANARY_DOB``)
never reaches the rendered JSON output through any code path that goes
through ``configure_logging_for_stdspec()``.
"""

from __future__ import annotations

from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger

from app.core.logging import configure_logging

from .phi import is_forbidden_column, scrub_record

# Keys that bypass the value-level scrub (because they're known PHI-free
# by the producer and would otherwise be over-scrubbed — e.g. ``drop_date``
# matches the DOB regex if rendered as YYYY-MM-DD). The whitelist is
# narrow: every key here must be guaranteed non-PHI by the call sites
# that emit it.
SCRUB_BYPASS_KEYS: frozenset[str] = frozenset(
    {
        "drop_date",
        "snapshot_date",
        "month",
        "ingested_at",
        "started_at",
        "completed_at",
        "timestamp",
        "ts",
        "run_id",
        "correlation_id",
        "sha256",
        "file_name",
        "rule",
        "rows_in",
        "rows_out",
        "facility_no",
        "physician_npi",
        "payer_class",
        "aging_bucket",
        "source_system",
        "event",
        "level",
        "logger",
    }
)


def redact_phi_keys(
    _logger: WrappedLogger, _name: str, event_dict: EventDict
) -> EventDict:
    """Drop any key whose name matches the forbidden-column denylist.

    Structlog processor signature. The leading args are required by the
    processor protocol but unused here.

    A dropped key gets replaced with a sentinel so the operator sees
    something happened — silent drops would hide bugs in the call sites.
    """
    out: EventDict = {}
    dropped: list[str] = []
    for key, value in event_dict.items():
        if is_forbidden_column(key):
            dropped.append(key)
            continue
        out[key] = value
    if dropped:
        out["_phi_keys_redacted"] = dropped
    return out


def scrub_phi_values(
    _logger: WrappedLogger, _name: str, event_dict: EventDict
) -> EventDict:
    """Scrub PHI-shaped substrings out of every string value.

    Keys in ``SCRUB_BYPASS_KEYS`` are emitted verbatim. The narrow
    whitelist is the trade-off — over-scrubbing the drop_date is noisy
    in operator logs, but under-scrubbing risks a PHI leak. Adding a
    new bypass key requires the caller to prove the value is PHI-free.
    """
    # Walk every key/value. For bypassed keys, pass through unchanged.
    # For everything else, apply value-level scrubbing.
    out: EventDict = {}
    for key, value in event_dict.items():
        if key in SCRUB_BYPASS_KEYS:
            out[key] = value
        elif isinstance(value, dict):
            out[key] = scrub_record(value)
        else:
            # scrub_record handles dicts; for top-level scalars/lists we
            # apply scrub_value via a single-key wrapper.
            scrubbed = scrub_record({"v": value})
            out[key] = scrubbed["v"]
    return out


def configure_logging_for_stdspec(log_level: str = "INFO") -> None:
    """Install the base structlog pipeline + the two PHI processors.

    Must be called once at job startup, before any other module emits
    a log line. The ``main.py`` orchestrator calls this immediately
    after ``setup_telemetry()`` so the OTel/App-Insights export gets
    scrubbed records too (the same processor chain feeds both).

    Idempotent — repeated calls reconfigure structlog without raising.
    """
    # First lay down the project's base pipeline (JSON renderer,
    # contextvar merge, timestamp, etc.). Inherits any project-wide
    # PII processors from ``app.core.logging`` for free.
    configure_logging(log_level=log_level)

    # Re-fetch the current structlog config so we can splice our two
    # PHI processors in BEFORE the JSON renderer.
    current_config = structlog.get_config()
    processors: list[Any] = list(current_config.get("processors", []))

    # The JSON renderer (or any final renderer) is typically the LAST
    # processor in the chain. Insert our two PHI processors just before
    # it so they see the fully-merged event dict.
    if processors:
        # Splice at len(processors) - 1 so the final renderer stays last.
        processors.insert(len(processors) - 1, redact_phi_keys)
        processors.insert(len(processors) - 1, scrub_phi_values)
    else:
        # No existing chain (unexpected) — install the two processors
        # alongside a basic JSON renderer as a fallback.
        processors = [
            redact_phi_keys,
            scrub_phi_values,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        context_class=current_config.get("context_class", dict),
        logger_factory=current_config.get(
            "logger_factory", structlog.PrintLoggerFactory()
        ),
        wrapper_class=current_config.get("wrapper_class", structlog.BoundLogger),
        cache_logger_on_first_use=True,
    )


__all__ = [
    "SCRUB_BYPASS_KEYS",
    "configure_logging_for_stdspec",
    "redact_phi_keys",
    "scrub_phi_values",
]
