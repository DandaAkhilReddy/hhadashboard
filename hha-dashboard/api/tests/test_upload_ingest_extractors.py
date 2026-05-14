"""Unit tests for ``jobs/upload_ingest/extractors/`` — the registry +
census_pdf extractor (the only one with real behavior; the three xlsx
files are explicit stubs that raise NotImplementedError until Session 4).

This file plugs the original Phase 3 plan's ``upload_ingest`` greenfield
gap. Pure-Python: every Azure SDK + DB interaction is mocked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from jobs.upload_ingest.extractors import ROUTES
from jobs.upload_ingest.extractors.census_pdf import (
    ExtractionResult,
    extract_census_pdf,
)
from jobs.upload_ingest.extractors.clinical_xlsx import extract_clinical_xlsx
from jobs.upload_ingest.extractors.finance_xlsx import extract_finance_xlsx
from jobs.upload_ingest.extractors.hr_xlsx import extract_hr_xlsx

# ---------- Registry shape ----------


class TestExtractorRegistry:
    def test_routes_has_exactly_four_file_types(self) -> None:
        assert set(ROUTES.keys()) == {
            "census_pdf",
            "finance_xlsx",
            "clinical_xlsx",
            "hr_xlsx",
        }

    def test_route_callables_are_the_module_exports(self) -> None:
        assert ROUTES["census_pdf"] is extract_census_pdf
        assert ROUTES["clinical_xlsx"] is extract_clinical_xlsx
        assert ROUTES["finance_xlsx"] is extract_finance_xlsx
        assert ROUTES["hr_xlsx"] is extract_hr_xlsx

    def test_every_route_is_callable(self) -> None:
        for fn in ROUTES.values():
            assert callable(fn)


# ---------- Stub extractors ----------


class TestStubExtractors:
    @pytest.mark.parametrize(
        ("fn", "expected_msg_substring"),
        [
            (extract_clinical_xlsx, "clinical_xlsx extractor is not yet implemented"),
            (extract_finance_xlsx, "finance_xlsx extractor is not yet implemented"),
            (extract_hr_xlsx, "hr_xlsx extractor is not yet implemented"),
        ],
    )
    async def test_stub_raises_not_implemented_with_helpful_message(
        self, fn, expected_msg_substring: str
    ) -> None:
        with pytest.raises(NotImplementedError, match=expected_msg_substring):
            await fn(b"any bytes", MagicMock(), MagicMock())


# ---------- ExtractionResult dataclass ----------


class TestExtractionResult:
    def test_defaults_are_zero_rows_no_warnings(self) -> None:
        result = ExtractionResult()
        assert result.rows_written == 0
        assert result.warnings == []

    def test_warnings_default_factory_isolation(self) -> None:
        # The mutable default must not leak across instances.
        a = ExtractionResult()
        b = ExtractionResult()
        a.warnings.append("a-only")
        assert b.warnings == []

    def test_explicit_construction(self) -> None:
        result = ExtractionResult(rows_written=3, warnings=["check row 7"])
        assert result.rows_written == 3
        assert result.warnings == ["check row 7"]


# ---------- Census PDF extractor ----------


def _make_db_with_sites(sites: list[tuple[int, str]]) -> AsyncMock:
    """Build a mock AsyncSession where SELECT Site returns the given rows."""
    db = AsyncMock()

    class _Site:
        def __init__(self, sid: int, name: str) -> None:
            self.id = sid
            self.name = name

    select_result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = [_Site(sid, name) for sid, name in sites]
    select_result.scalars.return_value = scalars

    db.execute = AsyncMock(return_value=select_result)
    return db


def _upload_row(blob_name: str = "uploads/2026-05-14/census.pdf") -> MagicMock:
    row = MagicMock()
    row.uploaded_by_upn = "crystal@hhamedicine.com"
    row.uploaded_at = datetime(2026, 5, 14, 15, 0, tzinfo=UTC)
    row.blob_name = blob_name
    return row


class TestExtractCensusPdf:
    async def test_returns_empty_result_when_no_matches(self, monkeypatch) -> None:
        # Mock the DI client wrapper to return zero matches.
        async def _fake_extract(_pdf_bytes: bytes, _known_names: list[str]):
            r = MagicMock()
            r.matches = []
            r.unmatched_rows = []
            r.warnings = ["No tables found"]
            r.pdf_sha256 = "abc"
            return r

        monkeypatch.setattr(
            "jobs.upload_ingest.extractors.census_pdf.extract_census_from_pdf",
            _fake_extract,
        )

        db = _make_db_with_sites([(1, "Westside Regional")])
        result = await extract_census_pdf(b"%PDF-stub", _upload_row(), db)

        assert result.rows_written == 0
        # Warning prefix + the DI-side warnings appended.
        assert any("No site/census matches" in w for w in result.warnings)
        assert "No tables found" in result.warnings

    async def test_writes_one_upsert_per_matched_site(self, monkeypatch) -> None:
        """Happy path: 2 matches → 1 SELECT (sites) + 2 pg_inserts. Each
        upsert carries the matched site_id + entry_date derived from
        uploaded_at."""

        async def _fake_extract(_pdf_bytes: bytes, _known_names: list[str]):
            r = MagicMock()
            m1 = MagicMock()
            m1.site_name = "Westside Regional"
            m1.census = 198
            m2 = MagicMock()
            m2.site_name = "JFK Main Med Ctr"
            m2.census = 262
            r.matches = [m1, m2]
            r.unmatched_rows = []
            r.warnings = []
            r.pdf_sha256 = "deadbeef"
            return r

        monkeypatch.setattr(
            "jobs.upload_ingest.extractors.census_pdf.extract_census_from_pdf",
            _fake_extract,
        )

        db = _make_db_with_sites(
            [(1, "Westside Regional"), (2, "JFK Main Med Ctr"), (3, "Other")]
        )
        result = await extract_census_pdf(b"%PDF-stub", _upload_row(), db)

        assert result.rows_written == 2
        # 1 SELECT for the site roster + 2 upserts = 3 db.execute calls
        assert db.execute.call_count == 3

    async def test_skips_match_whose_site_not_in_roster(self, monkeypatch) -> None:
        """A DI match for a name NOT in masters.sites is silently dropped —
        only known sites can land in daily_entries."""

        async def _fake_extract(_pdf_bytes: bytes, _known_names: list[str]):
            r = MagicMock()
            ghost = MagicMock()
            ghost.site_name = "Phantom Hospital"
            ghost.census = 50
            r.matches = [ghost]
            r.unmatched_rows = []
            r.warnings = []
            r.pdf_sha256 = "ghost"
            return r

        monkeypatch.setattr(
            "jobs.upload_ingest.extractors.census_pdf.extract_census_from_pdf",
            _fake_extract,
        )

        db = _make_db_with_sites([(1, "Westside Regional")])
        result = await extract_census_pdf(b"%PDF-stub", _upload_row(), db)

        # 0 rows written even though DI returned a match — the site is unknown.
        assert result.rows_written == 0
        # Only the SELECT happened; no upsert.
        assert db.execute.call_count == 1

    async def test_uses_uploaded_at_date_for_entry_date(self, monkeypatch) -> None:
        """The upsert's entry_date comes from upload_row.uploaded_at.date()."""

        captured: dict[str, object] = {}

        async def _fake_extract(_pdf_bytes: bytes, _known_names: list[str]):
            r = MagicMock()
            m = MagicMock()
            m.site_name = "Westside Regional"
            m.census = 200
            r.matches = [m]
            r.unmatched_rows = []
            r.warnings = []
            r.pdf_sha256 = "x"
            return r

        monkeypatch.setattr(
            "jobs.upload_ingest.extractors.census_pdf.extract_census_from_pdf",
            _fake_extract,
        )

        # Custom DB: first execute returns the site roster; subsequent ones
        # capture the upsert statement.
        class _Site:
            id = 1
            name = "Westside Regional"

        db = MagicMock()
        async def execute_dispatch(stmt):
            if "params" in captured:
                return MagicMock()
            if "captured" not in captured:
                captured["captured"] = True
                r = MagicMock()
                r.scalars.return_value.all.return_value = [_Site()]
                return r
            try:
                captured["params"] = stmt.compile().params
            except Exception:
                captured["params"] = {}
            return MagicMock()

        db.execute = execute_dispatch

        upload = _upload_row()
        # Force a specific uploaded_at so the test pin is stable.
        upload.uploaded_at = datetime(2026, 5, 14, 12, 30, tzinfo=UTC)

        result = await extract_census_pdf(b"%PDF-stub", upload, db)

        assert result.rows_written == 1
        params = captured.get("params") or {}
        # The upsert values include entry_date = 2026-05-14
        assert params.get("entry_date") is not None
        assert str(params["entry_date"]).startswith("2026-05-14")

    async def test_propagates_di_warnings_into_result(self, monkeypatch) -> None:
        """Even on success, any DI warnings flow through to the caller."""

        async def _fake_extract(_pdf_bytes: bytes, _known_names: list[str]):
            r = MagicMock()
            m = MagicMock()
            m.site_name = "Westside Regional"
            m.census = 198
            r.matches = [m]
            r.unmatched_rows = [["mystery row", "?"]]
            r.warnings = ["1 row could not be matched"]
            r.pdf_sha256 = "sha"
            return r

        monkeypatch.setattr(
            "jobs.upload_ingest.extractors.census_pdf.extract_census_from_pdf",
            _fake_extract,
        )

        db = _make_db_with_sites([(1, "Westside Regional")])
        result = await extract_census_pdf(b"%PDF-stub", _upload_row(), db)

        assert result.rows_written == 1
        assert "1 row could not be matched" in result.warnings
