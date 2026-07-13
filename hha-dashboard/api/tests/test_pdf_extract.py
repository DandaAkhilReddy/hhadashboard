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


# ---------- _build_di_client both auth branches (Phase 3 gap-fill) ----------


def test_build_di_client_raises_when_endpoint_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Endpoint is the one config that MUST be set — there is no sensible
    default. RuntimeError surfaces immediately rather than letting an
    Azure SDK call fail with a less informative error."""
    monkeypatch.setattr(pdf_extract.settings, "azure_doc_intelligence_endpoint", "", raising=False)

    with pytest.raises(RuntimeError, match="AZURE_DOC_INTELLIGENCE_ENDPOINT not configured"):
        pdf_extract._build_di_client()


def test_build_di_client_uses_api_key_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dev path: AZURE_DOC_INTELLIGENCE_API_KEY set → AzureKeyCredential.
    Avoids the DefaultAzureCredential IMDS round-trip that would fail in
    a laptop dev environment."""
    fake_client = MagicMock(name="DocumentIntelligenceClient-instance")
    fake_ctor = MagicMock(return_value=fake_client)
    fake_cred = MagicMock(name="AzureKeyCredential-instance")
    fake_cred_ctor = MagicMock(return_value=fake_cred)

    monkeypatch.setattr(
        pdf_extract.settings,
        "azure_doc_intelligence_endpoint",
        "https://hha-di.cognitiveservices.azure.com",
        raising=False,
    )
    monkeypatch.setattr(
        pdf_extract.settings,
        "azure_doc_intelligence_api_key",
        "dev-api-key",
        raising=False,
    )
    monkeypatch.setattr(pdf_extract, "DocumentIntelligenceClient", fake_ctor)
    monkeypatch.setattr(pdf_extract, "AzureKeyCredential", fake_cred_ctor)

    client = pdf_extract._build_di_client()

    assert client is fake_client
    fake_cred_ctor.assert_called_once_with("dev-api-key")
    fake_ctor.assert_called_once_with(
        endpoint="https://hha-di.cognitiveservices.azure.com",
        credential=fake_cred,
    )


def test_build_di_client_falls_back_to_managed_identity_when_no_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prod path: no API key → DefaultAzureCredential. Critical that we
    never silently fall back to API-key=None (the SDK would attempt no
    auth, fail mysteriously)."""
    fake_client = MagicMock(name="DocumentIntelligenceClient-instance")
    fake_ctor = MagicMock(return_value=fake_client)
    fake_mi = MagicMock(name="DefaultAzureCredential-instance")
    fake_mi_factory = MagicMock(return_value=fake_mi)

    monkeypatch.setattr(
        pdf_extract.settings,
        "azure_doc_intelligence_endpoint",
        "https://hha-di.cognitiveservices.azure.com",
        raising=False,
    )
    monkeypatch.setattr(pdf_extract.settings, "azure_doc_intelligence_api_key", "", raising=False)
    monkeypatch.setattr(pdf_extract, "DocumentIntelligenceClient", fake_ctor)
    monkeypatch.setattr(pdf_extract, "DefaultAzureCredential", fake_mi_factory)

    client = pdf_extract._build_di_client()

    assert client is fake_client
    fake_mi_factory.assert_called_once_with()
    fake_ctor.assert_called_once_with(
        endpoint="https://hha-di.cognitiveservices.azure.com",
        credential=fake_mi,
    )


# ---------- _cell_as_int edge cases ----------


def test_cell_as_int_returns_none_for_none_input() -> None:
    """Cells from DI can legitimately be None when an empty cell is parsed.
    Must not crash with AttributeError."""
    assert pdf_extract._cell_as_int(None) is None  # type: ignore[arg-type]


def test_cell_as_int_returns_none_for_empty_string() -> None:
    """Stripping non-digits from an empty/whitespace cell leaves nothing."""
    assert pdf_extract._cell_as_int("") is None
    assert pdf_extract._cell_as_int("   ") is None
    assert pdf_extract._cell_as_int("abc") is None  # no digits at all


def test_cell_as_int_returns_none_for_above_max_census() -> None:
    """MAX_CENSUS is 2000. Above that → reject (typo or wrong column)."""
    assert pdf_extract._cell_as_int("2001") is None
    assert pdf_extract._cell_as_int("99999") is None


def test_cell_as_int_returns_int_for_valid_range() -> None:
    """0 ≤ n ≤ 2000 → return the int."""
    assert pdf_extract._cell_as_int("0") == 0
    assert pdf_extract._cell_as_int("100") == 100
    assert pdf_extract._cell_as_int("2000") == 2000


def test_cell_as_int_strips_non_digits() -> None:
    """Cells may include commas, percent signs, or units."""
    assert pdf_extract._cell_as_int("1,234") == 1234
    assert pdf_extract._cell_as_int("100 beds") == 100


# ---------- _extract_tables skips empty rows ----------


def test_extract_tables_skips_table_with_no_rows() -> None:
    """If a table has zero cells (or all cells are empty-string), the
    sorted_rows loop produces no entries → outer if sorted_rows skips."""
    # Empty cells array → no rows_by_idx entries → sorted_rows stays empty
    table = SimpleNamespace(cells=[])
    result = SimpleNamespace(tables=[table])

    out = _extract_tables_from_result(result)  # type: ignore[arg-type]
    assert out == []


# ---------- _match_row_to_site edge cases ----------


def test_match_row_skips_cells_under_3_chars() -> None:
    """Short cells (<3 chars after strip) are ignored — too noisy for
    fuzzy match. A row like ['x', '5', '100'] never matches a site name."""
    row = ["x", "5", "100"]
    match, ok = _match_row_to_site(row, ["Westside Regional"])

    assert ok is False
    assert match is None


def test_match_row_returns_none_when_site_matches_but_no_int_cell() -> None:
    """If a site name fuzzy-matches but no other cell parses to an int
    in the valid census range, treat the row as unmatched (line 167)."""
    row = ["Westside Regional", "no number here", "nope either"]
    match, ok = _match_row_to_site(row, ["Westside Regional"])

    assert ok is False
    assert match is None


def test_match_row_returns_none_for_empty_known_sites_list() -> None:
    """rapidfuzz returns None when the choices list is empty — line 140."""
    row = ["Westside Regional", "100"]
    match, ok = _match_row_to_site(row, [])

    assert ok is False
    assert match is None


# ---------- CensusExtractionResult.rows_written property ----------


def test_rows_written_returns_match_count() -> None:
    """The cron writes rows_written rows to entries.daily_entries — used
    by the upload-status endpoint to show 'extracted N rows'."""
    r = pdf_extract.CensusExtractionResult()
    assert r.rows_written == 0

    r.matches.append(SiteMatch(site_name="A", census=10, confidence=80))
    r.matches.append(SiteMatch(site_name="B", census=20, confidence=85))
    assert r.rows_written == 2


# ---------- extract_census_from_pdf full happy path ----------


def _di_table(rows: list[list[str]]) -> object:
    """Build a DI-shaped table from a [[cells]] grid for use in fakes."""
    cells = [
        SimpleNamespace(row_index=r, column_index=c, content=v)
        for r, row in enumerate(rows)
        for c, v in enumerate(row)
    ]
    return SimpleNamespace(cells=cells)


@pytest.mark.asyncio
async def test_extract_census_full_path_matches_writes_warnings_and_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end with mocked DI: 1 table, 3 rows. Two rows match known
    sites; one is unmatched (junk text). Plus one known site never appears
    → warnings call out the missing one."""
    table = _di_table(
        [
            ["Westside Regional", "198"],
            ["Woodmont Hospital", "142"],
            ["unrelated row", "extra cell that is not an int"],
        ]
    )

    fake_poller = MagicMock()
    fake_poller.result = AsyncMock(return_value=SimpleNamespace(tables=[table]))

    async def fake_begin_analyze(*, model_id: str, body: object) -> object:
        _ = (model_id, body)
        return fake_poller

    fake_client = MagicMock()
    fake_client.begin_analyze_document = fake_begin_analyze
    fake_client.close = AsyncMock()
    monkeypatch.setattr(pdf_extract, "_build_di_client", lambda: fake_client)

    known = ["Westside Regional", "Woodmont Hospital", "Northpoint Care"]
    out = await extract_census_from_pdf(b"%PDF-1.4 fake-content", known)

    assert out.table_count == 1
    matched_names = {m.site_name for m in out.matches}
    assert matched_names == {"Westside Regional", "Woodmont Hospital"}
    # Northpoint Care is in known_sites but never appeared → warnings
    assert any("Northpoint Care" in w for w in out.warnings)
    # SHA256 of input bytes is captured
    assert len(out.pdf_sha256) == 64
    assert out.pdf_sha256 != ""


@pytest.mark.asyncio
async def test_extract_census_skips_duplicate_site_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a site appears in two rows (e.g. DI duplicates a header), keep
    only the first match. Subsequent rows for the same site are silently
    skipped (line 212-213)."""
    table = _di_table(
        [
            ["Westside Regional", "198"],
            ["Westside Regional", "999"],  # duplicate — should be ignored
        ]
    )

    fake_poller = MagicMock()
    fake_poller.result = AsyncMock(return_value=SimpleNamespace(tables=[table]))

    async def fake_begin_analyze(*, model_id: str, body: object) -> object:
        _ = (model_id, body)
        return fake_poller

    fake_client = MagicMock()
    fake_client.begin_analyze_document = fake_begin_analyze
    fake_client.close = AsyncMock()
    monkeypatch.setattr(pdf_extract, "_build_di_client", lambda: fake_client)

    out = await extract_census_from_pdf(b"%PDF", ["Westside Regional"])

    assert len(out.matches) == 1
    assert out.matches[0].census == 198  # first match kept, not 999


@pytest.mark.asyncio
async def test_extract_census_captures_unmatched_row_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rows that don't match a known site but LOOK like census data
    (≥2 cells, ≥1 cell with ≥3 chars, ≥1 int-parseable cell) end up in
    unmatched_rows for operator review."""
    table = _di_table(
        [["Unknown Facility Name", "75"]]  # unknown but census-shaped
    )

    fake_poller = MagicMock()
    fake_poller.result = AsyncMock(return_value=SimpleNamespace(tables=[table]))

    async def fake_begin_analyze(*, model_id: str, body: object) -> object:
        _ = (model_id, body)
        return fake_poller

    fake_client = MagicMock()
    fake_client.begin_analyze_document = fake_begin_analyze
    fake_client.close = AsyncMock()
    monkeypatch.setattr(pdf_extract, "_build_di_client", lambda: fake_client)

    out = await extract_census_from_pdf(b"%PDF", ["Westside Regional"])

    assert out.matches == []
    assert len(out.unmatched_rows) == 1
    assert out.unmatched_rows[0] == ["Unknown Facility Name", "75"]


# ---------- extract_census_sync wrapper ----------


def test_extract_census_sync_runs_async_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sync shim calls asyncio.run on the async extractor. Used by
    scripts/test fixtures that aren't already in an async event loop."""
    fake_poller = MagicMock()
    fake_poller.result = AsyncMock(return_value=SimpleNamespace(tables=None))

    async def fake_begin_analyze(*, model_id: str, body: object) -> object:
        _ = (model_id, body)
        return fake_poller

    fake_client = MagicMock()
    fake_client.begin_analyze_document = fake_begin_analyze
    fake_client.close = AsyncMock()
    monkeypatch.setattr(pdf_extract, "_build_di_client", lambda: fake_client)

    out = pdf_extract.extract_census_sync(b"%PDF", ["Westside Regional"])

    assert isinstance(out, pdf_extract.CensusExtractionResult)
    assert out.matches == []
    # No tables in the fake → warning
    assert any("No tables" in w for w in out.warnings)
