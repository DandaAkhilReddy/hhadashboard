"""paycom_sync stub tests.

Verifies:
  - When Paycom credentials aren't set, run() exits 0 without touching the DB.
  - Each extractor stub returns rows_written=0 + a TODO warning.
  - The registry exposes both extractors under expected keys.

These tests don't require a Postgres connection — the stubs short-circuit
before any DB work, and we mock the AsyncSession for the extractor tests.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from jobs.paycom_sync.extractors import ROUTES, ExtractionResult
from jobs.paycom_sync.extractors.headcount_daily import extract_headcount_daily
from jobs.paycom_sync.extractors.rvu_paycheck import extract_rvu_paycheck
from jobs.paycom_sync.main import run

pytestmark = pytest.mark.asyncio


async def test_run_exits_zero_when_paycom_not_configured() -> None:
    """The stub state — settings.paycom_configured is False by default."""
    with patch("jobs.paycom_sync.main.settings") as mock_settings:
        mock_settings.paycom_configured = False
        exit_code = await run()
    assert exit_code == 0


async def test_headcount_extractor_stub_returns_todo_warning() -> None:
    result = await extract_headcount_daily(db=None)  # type: ignore[arg-type]
    assert isinstance(result, ExtractionResult)
    assert result.rows_written == 0
    assert any("TODO" in w for w in result.warnings)


async def test_rvu_paycheck_extractor_stub_returns_todo_warning() -> None:
    result = await extract_rvu_paycheck(db=None)  # type: ignore[arg-type]
    assert isinstance(result, ExtractionResult)
    assert result.rows_written == 0
    assert any("TODO" in w for w in result.warnings)


def test_registry_exposes_both_extractors() -> None:
    assert "headcount_daily" in ROUTES
    assert "rvu_paycheck" in ROUTES
