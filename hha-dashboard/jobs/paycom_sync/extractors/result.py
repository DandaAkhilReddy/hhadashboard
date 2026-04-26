"""Shared result type for paycom_sync extractors.

Lives in its own module so individual extractor modules can import it
without circular dependency on the registry in __init__.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractionResult:
    """One run of a Paycom extractor.

    rows_written: int  - 0 from stubs; real count from real implementations
    warnings: list[str] - notes (TODOs from stubs, anomalies from real impls)
    """

    rows_written: int
    warnings: list[str]
