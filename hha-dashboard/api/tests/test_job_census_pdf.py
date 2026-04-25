"""Census-PDF extractor unit test.

The real extractor (jobs/upload_ingest/extractors/census_pdf.py) wires together:
  - Site roster lookup (sites_by_name)
  - services.pdf_extract.extract_census_from_pdf (Document Intelligence)
  - pg_insert(DailyEntry).on_conflict_do_update (Postgres upsert)

The Postgres upsert is a native primitive we trust. What we want to verify:

  - When DI returns 3 matches for 3 known sites, the extractor issues 3
    insert statements with the correct site_id + census values.
  - Unknown site names from DI are silently dropped (safer than crashing).
  - An empty DI result returns rows_written=0 + a warning.

We use an AsyncMock session so we don't need Postgres running.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.pdf_extract import CensusExtractionResult, SiteMatch


def _mock_sites(sites: dict[str, int]) -> MagicMock:
    """Build a scalars().all() result shaped like a Site-roster load."""
    site_objs = [SimpleNamespace(id=sid, name=name) for name, sid in sites.items()]
    scalars = MagicMock()
    scalars.all.return_value = site_objs
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _mock_upload_row(upn: str = "crystal@hhamedicine.com") -> SimpleNamespace:
    return SimpleNamespace(
        blob_name="uploads/census_pdf/2026-04-24/foo.pdf",
        uploaded_by_upn=upn,
        uploaded_at=datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_extractor_writes_one_row_per_matched_site() -> None:
    from jobs.upload_ingest.extractors import census_pdf as extractor

    sites = {"Westside Regional": 1, "Woodmont Hospital": 2, "Palms West Hospital": 3}
    db = MagicMock()
    db.execute = AsyncMock(return_value=_mock_sites(sites))

    di_result = CensusExtractionResult(
        matches=[
            SiteMatch(site_name="Westside Regional", census=198, confidence=92),
            SiteMatch(site_name="Woodmont Hospital", census=142, confidence=88),
            SiteMatch(site_name="Palms West Hospital", census=201, confidence=95),
        ],
        unmatched_rows=[],
        pdf_sha256="abc123",
    )

    with patch.object(extractor, "extract_census_from_pdf", AsyncMock(return_value=di_result)):
        # Re-wire db.execute: 1st call = site roster, subsequent calls = upsert stmts
        call_count = {"n": 0}
        first_result = _mock_sites(sites)
        upsert_result = MagicMock()

        async def execute_side_effect(*_args, **_kwargs):
            call_count["n"] += 1
            return first_result if call_count["n"] == 1 else upsert_result

        db.execute = AsyncMock(side_effect=execute_side_effect)

        out = await extractor.extract_census_pdf(
            pdf_bytes=b"%PDF-1.4 fake",
            upload_row=_mock_upload_row(),
            db=db,
        )

    assert out.rows_written == 3
    # 1 roster SELECT + 3 upsert INSERTs = 4 calls
    assert db.execute.await_count == 4


@pytest.mark.asyncio
async def test_extractor_drops_unknown_site_names() -> None:
    """A DI match for a site not in the known roster is silently skipped."""
    from jobs.upload_ingest.extractors import census_pdf as extractor

    sites = {"Westside Regional": 1}  # only one known site
    di_result = CensusExtractionResult(
        matches=[
            SiteMatch(site_name="Westside Regional", census=198, confidence=92),
            SiteMatch(site_name="Some Other Hospital", census=50, confidence=70),
        ],
        pdf_sha256="abc123",
    )

    db = MagicMock()
    call_count = {"n": 0}
    roster = _mock_sites(sites)
    upsert_result = MagicMock()

    async def execute_side_effect(*_args, **_kwargs):
        call_count["n"] += 1
        return roster if call_count["n"] == 1 else upsert_result

    db.execute = AsyncMock(side_effect=execute_side_effect)

    with patch.object(extractor, "extract_census_from_pdf", AsyncMock(return_value=di_result)):
        out = await extractor.extract_census_pdf(
            pdf_bytes=b"%PDF",
            upload_row=_mock_upload_row(),
            db=db,
        )

    assert out.rows_written == 1  # only Westside
    assert db.execute.await_count == 2  # 1 roster + 1 upsert


@pytest.mark.asyncio
async def test_extractor_returns_empty_on_no_matches() -> None:
    from jobs.upload_ingest.extractors import census_pdf as extractor

    sites = {"Westside Regional": 1}
    di_result = CensusExtractionResult(
        matches=[],
        unmatched_rows=[["Mystery Row", "42"]],
        warnings=["No tables found"],
        pdf_sha256="abc123",
    )

    db = MagicMock()
    db.execute = AsyncMock(return_value=_mock_sites(sites))

    with patch.object(extractor, "extract_census_from_pdf", AsyncMock(return_value=di_result)):
        out = await extractor.extract_census_pdf(
            pdf_bytes=b"%PDF",
            upload_row=_mock_upload_row(),
            db=db,
        )

    assert out.rows_written == 0
    assert any("No site/census" in w for w in out.warnings)
    assert any("No tables found" in w for w in out.warnings)
    # Only the roster SELECT, no upserts
    assert db.execute.await_count == 1
