"""pdf_extract.py unit tests — SDK-layer behavior + edge cases.

Audit ticket T8 lock-in:
- `_extract_tables_from_result` must NOT crash when DI returns no tables
  (audit's "union-attr" finding at line 102 — None deref on result.tables).
- `_match_row_to_site` must store rapidfuzz's float score as int in
  SiteMatch.confidence (audit's "type-assignment" finding at line 136).
- `extract_census_from_pdf` must wrap pdf_bytes in AnalyzeDocumentRequest
  (audit's SDK overload mismatch at line 181) — the wrapper is what the
  v1.x SDK expects; bytes-direct doesn't match any overload.

These tests don't hit Document Intelligence — they mock the SDK or call
internal helpers directly.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import pdf_extract
from app.services.pdf_extract import (
    SiteMatch,
    _extract_tables_from_result,
    _match_row_to_site,
    extract_census_from_pdf,
)

# ---------- Empty-tables / no-tables PDF (audit line 102) ----------


def test_extract_tables_returns_empty_when_result_tables_is_none() -> None:
    """A PDF with zero tables → DI's AnalyzeResult has tables=None.
    Pre-fix this crashed on `for table in result.tables:` with TypeError.
    Post-fix it returns [] cleanly."""
    result = SimpleNamespace(tables=None)
    assert _extract_tables_from_result(result) == []  # type: ignore[arg-type]


def test_extract_tables_returns_empty_when_result_tables_is_empty_list() -> None:
    """Same shape as above but tables=[] explicitly. Should also no-op."""
    result = SimpleNamespace(tables=[])
    assert _extract_tables_from_result(result) == []  # type: ignore[arg-type]


def test_extract_tables_renders_one_table_correctly() -> None:
    """Sanity: a single table with 2 rows × 2 cols comes back as
    [[['A','B'], ['C','D']]]. Locks the cell-sort logic."""
    cells = [
        SimpleNamespace(row_index=0, column_index=0, content="A"),
        SimpleNamespace(row_index=0, column_index=1, content="B"),
        SimpleNamespace(row_index=1, column_index=0, content="C"),
        SimpleNamespace(row_index=1, column_index=1, content="D"),
    ]
    table = SimpleNamespace(cells=cells)
    result = SimpleNamespace(tables=[table])
    assert _extract_tables_from_result(result) == [[["A", "B"], ["C", "D"]]]  # type: ignore[arg-type]


# ---------- Match-row score type (audit line 136) ----------


def test_match_row_stores_score_as_int_in_confidence() -> None:
    """rapidfuzz returns float scores 0-100. SiteMatch.confidence must be int.
    The fix wraps the assignment in int() — locking that downstream code can
    rely on `confidence: int` without surprises."""
    row = ["Westside Regional", "198"]
    known = ["Westside Regional", "Woodmont Hospital"]
    match, ok = _match_row_to_site(row, known)
    assert ok is True
    assert match is not None
    assert isinstance(match.confidence, int)
    assert match.confidence >= 75  # FUZZY_MATCH_THRESHOLD


def test_match_row_returns_none_when_no_known_site_resembles_any_cell() -> None:
    row = ["Random Text", "42"]
    known = ["Westside Regional", "Woodmont Hospital"]
    match, ok = _match_row_to_site(row, known)
    assert match is None
    assert ok is False


# ---------- SDK call shape (audit line 181) ----------


@pytest.mark.asyncio
async def test_extract_census_from_pdf_wraps_bytes_in_analyze_document_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-fix the SDK call passed `body=pdf_bytes, content_type=...` which
    the v1.x SDK rejects (no matching overload). Post-fix it wraps in
    AnalyzeDocumentRequest(bytes_source=...). This test asserts the body
    arg is the right type at the SDK boundary — runtime crash on first
    real upload would otherwise be silent until prod."""
    from azure.ai.documentintelligence.models import AnalyzeDocumentRequest

    captured_body: dict[str, object] = {}

    fake_poller = MagicMock()
    fake_poller.result = AsyncMock(return_value=SimpleNamespace(tables=None))

    async def fake_begin_analyze(*, model_id: str, body: object) -> object:
        _ = model_id
        captured_body["body"] = body
        return fake_poller

    fake_client = MagicMock()
    fake_client.begin_analyze_document = fake_begin_analyze
    fake_client.close = AsyncMock()

    monkeypatch.setattr(
        pdf_extract, "_build_di_client", lambda: fake_client
    )

    out = await extract_census_from_pdf(b"%PDF-1.4 fake", ["Westside Regional"])

    assert isinstance(captured_body["body"], AnalyzeDocumentRequest)
    assert captured_body["body"].bytes_source == b"%PDF-1.4 fake"
    # No tables in the fake DI response → empty result + warning.
    assert out.matches == []
    assert any("No tables" in w for w in out.warnings)


def test_site_match_dataclass_default_values() -> None:
    """Sanity test on the dataclass default factories — protects against
    accidental shared-mutable-default regressions."""
    a = SiteMatch(site_name="Westside Regional", census=100, confidence=80)
    b = SiteMatch(site_name="Woodmont Hospital", census=50, confidence=70)
    a.raw_row.append("touched-a")
    assert b.raw_row == []  # not shared
