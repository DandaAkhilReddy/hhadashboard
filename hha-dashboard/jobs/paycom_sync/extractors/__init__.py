"""Paycom extractor registry.

When Paycom API access is granted, replace each `extract_*` stub with a
real implementation that calls the Paycom REST API and writes to the
appropriate fact table. Until then, the registry exists so the cron entry
point + tests have something to import.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from .headcount_daily import extract_headcount_daily
from .result import ExtractionResult
from .rvu_paycheck import extract_rvu_paycheck

__all__ = ["ROUTES", "ExtractionResult"]


# Registry — name → extractor callable. When the API client lands, point
# each entry at the real implementation in the same module.
ROUTES: dict[str, Callable[[AsyncSession], Awaitable[ExtractionResult]]] = {
    "headcount_daily": extract_headcount_daily,
    "rvu_paycheck": extract_rvu_paycheck,
}
