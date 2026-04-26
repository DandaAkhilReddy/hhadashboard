"""Census-PDF extraction via Azure Document Intelligence.

Flow:
  1. Caller passes in raw PDF bytes + list of known site names
  2. We POST bytes to Document Intelligence prebuilt-layout
  3. DI returns structured tables + text
  4. For each table row, fuzzy-match the "site name" cell against known sites
  5. Extract the "census" cell (any cell with an integer 1-2000)
  6. Return matches + any unmatched rows for user review

Per ADR-001:
- The PDF bytes passed in MAY contain PHI (patient names, MRNs, DOBs)
- This function reads the DI response in memory, extracts ONLY the
  aggregate site/count pairs, and returns them
- The raw DI response is NOT persisted or logged
- Caller (cron job) writes only aggregates to Postgres
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field

from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeResult
from azure.core.credentials import AzureKeyCredential
from azure.identity.aio import DefaultAzureCredential
from rapidfuzz import fuzz, process

from ..settings import settings

log = logging.getLogger(__name__)

MIN_CENSUS = 0
MAX_CENSUS = 2000  # sanity bound — no HHA site has ever had >2000 concurrent inpatients
FUZZY_MATCH_THRESHOLD = 75  # 0-100; below this → unmatched


@dataclass
class SiteMatch:
    site_name: str  # canonical name from the known_sites list
    census: int
    confidence: int  # 0-100 rapidfuzz score
    raw_row: list[str] = field(default_factory=list)  # original cell values


@dataclass
class CensusExtractionResult:
    matches: list[SiteMatch] = field(default_factory=list)
    unmatched_rows: list[list[str]] = field(default_factory=list)
    table_count: int = 0
    pdf_sha256: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def rows_written(self) -> int:
        return len(self.matches)


def _build_di_client() -> DocumentIntelligenceClient:
    """Dev: API key. Prod: Managed Identity via DefaultAzureCredential."""
    endpoint = settings.azure_doc_intelligence_endpoint
    if not endpoint:
        raise RuntimeError(
            "AZURE_DOC_INTELLIGENCE_ENDPOINT not configured. "
            "Set it in .env for dev, or wire Managed Identity in prod."
        )
    api_key = settings.azure_doc_intelligence_api_key
    if api_key:
        return DocumentIntelligenceClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(api_key),
        )
    return DocumentIntelligenceClient(endpoint=endpoint, credential=DefaultAzureCredential())


def _cell_as_int(value: str) -> int | None:
    """Parse a cell value to an integer census count, or None if not valid."""
    if value is None:
        return None
    # Strip everything that isn't a digit
    stripped = re.sub(r"[^\d]", "", str(value))
    if not stripped:
        return None
    try:
        n = int(stripped)
    except ValueError:
        return None
    if MIN_CENSUS <= n <= MAX_CENSUS:
        return n
    return None


def _extract_tables_from_result(result: AnalyzeResult) -> list[list[list[str]]]:
    """Return [table][row][col] as strings."""
    tables: list[list[list[str]]] = []
    if not getattr(result, "tables", None):
        return tables
    for table in result.tables:
        rows_by_idx: dict[int, dict[int, str]] = {}
        for cell in table.cells:
            rows_by_idx.setdefault(cell.row_index, {})[cell.column_index] = (cell.content or "").strip()
        sorted_rows = []
        for r in sorted(rows_by_idx.keys()):
            cells = rows_by_idx[r]
            sorted_cells = [cells.get(c, "") for c in sorted(cells.keys())]
            sorted_rows.append(sorted_cells)
        if sorted_rows:
            tables.append(sorted_rows)
    return tables


def _match_row_to_site(
    row: list[str], known_sites: list[str]
) -> tuple[SiteMatch | None, bool]:
    """Try to identify (site_name, census) from a single row.

    Returns (SiteMatch or None, is_matched). If no cell fuzzy-matches a known
    site OR no cell parses as an integer, returns (None, False).
    """
    # Find the cell most likely to be the site name (try each)
    best_match: tuple[str, int, int] | None = None  # (site, score, cell_idx)
    for idx, cell in enumerate(row):
        if not cell or len(cell.strip()) < 3:
            continue
        result = process.extractOne(
            cell, known_sites, scorer=fuzz.token_set_ratio
        )
        if result is None:
            continue
        site_name, score, _ = result
        if score >= FUZZY_MATCH_THRESHOLD and (best_match is None or score > best_match[1]):
            best_match = (site_name, score, idx)

    if best_match is None:
        return None, False

    site_name, score, site_cell_idx = best_match

    # Find the most plausible census cell (any other cell that parses as int)
    # Prefer cells to the right of the site name cell (most census tables put count after name)
    candidate_cells = list(range(len(row)))
    candidate_cells.sort(key=lambda i: (i <= site_cell_idx, abs(i - site_cell_idx)))
    for idx in candidate_cells:
        if idx == site_cell_idx:
            continue
        n = _cell_as_int(row[idx])
        if n is not None:
            return SiteMatch(
                site_name=site_name,
                census=n,
                confidence=score,
                raw_row=list(row),
            ), True

    # Site matched but no integer cell → treat as unmatched so user can review
    return None, False


async def extract_census_from_pdf(
    pdf_bytes: bytes, known_sites: list[str]
) -> CensusExtractionResult:
    """Run Document Intelligence on the PDF bytes and extract site->census pairs.

    Args:
        pdf_bytes: the raw PDF file. MAY contain PHI — read-only, never persisted.
        known_sites: canonical names from masters.sites.name

    Returns:
        CensusExtractionResult with matches, unmatched rows, and pdf_sha256.
    """
    result = CensusExtractionResult(
        pdf_sha256=hashlib.sha256(pdf_bytes).hexdigest()
    )

    client = _build_di_client()
    try:
        poller = await client.begin_analyze_document(
            model_id="prebuilt-layout",
            body=pdf_bytes,
            content_type="application/pdf",
        )
        di_result: AnalyzeResult = await poller.result()
    finally:
        await client.close()

    tables = _extract_tables_from_result(di_result)
    result.table_count = len(tables)
    if not tables:
        result.warnings.append("No tables found in PDF. Check format or use manual entry.")
        return result

    seen_sites: set[str] = set()
    for table in tables:
        for row in table:
            match, ok = _match_row_to_site(row, known_sites)
            if ok and match is not None:
                # Skip duplicate matches for the same site (take the first/best)
                if match.site_name in seen_sites:
                    continue
                seen_sites.add(match.site_name)
                result.matches.append(match)
            else:
                # Only keep rows that look like they might have been census data
                # (more than 1 cell, at least one with >=3 chars, at least one int)
                if len(row) >= 2 and any(len(c) >= 3 for c in row) and any(_cell_as_int(c) is not None for c in row):
                    result.unmatched_rows.append(list(row))

    missing = [s for s in known_sites if s not in seen_sites]
    if missing:
        result.warnings.append(
            f"{len(missing)} site(s) not found in PDF: {', '.join(missing[:5])}"
            + ("..." if len(missing) > 5 else "")
        )

    log.info(
        "pdf_extract.done sha256=%s tables=%d matched=%d unmatched_rows=%d",
        result.pdf_sha256,
        result.table_count,
        len(result.matches),
        len(result.unmatched_rows),
    )
    return result


# ---------- Test-friendly synchronous shim ----------


def extract_census_sync(pdf_bytes: bytes, known_sites: list[str]) -> CensusExtractionResult:
    """Sync wrapper for scripts + tests."""
    return asyncio.run(extract_census_from_pdf(pdf_bytes, known_sites))
