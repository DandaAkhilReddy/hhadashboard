"""Stub: pull paycheck-grain RVU rollups from Paycom → fact_rvu_paycheck.

When Paycom API access is granted, replace the body with:

  1. Fetch payroll runs for the trailing 14 days
     (`/api/v4/company/{company_id}/payroll?start_date=...`).
  2. For each pay date, pull the line items per physician.
  3. Filter to RVU-tagged earning codes (the Paycom code map is in the
     comp-agreements config — TBD, lives in masters.comp_agreements).
  4. Upsert one row per (pay_date, physician_id) into facts.fact_rvu_paycheck.

This is the source for Doctor Scorecards' "RVU Generated" tile. Until it's
wired, the scorecards UI shows the stub fixture from app/services/fake_data.py
for that metric.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .result import ExtractionResult


async def extract_rvu_paycheck(db: AsyncSession) -> ExtractionResult:
    """Stub. Replace once Paycom API access is granted."""
    _ = db
    return ExtractionResult(
        rows_written=0,
        warnings=["TODO: implement Paycom RVU paycheck extractor when API access is granted"],
    )
