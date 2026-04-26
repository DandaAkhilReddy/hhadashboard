"""Stub: pull active employee count + open positions from Paycom → fact_headcount_daily.

When Paycom API access is granted (currently 4–6 wk pending), replace the
body of `extract_headcount_daily` with:

  1. Fetch the employee roster (`/api/v4/company/{company_id}/employee?status=Active`)
     paginated, into memory.
  2. Fetch the open-requisitions endpoint (or compute from job postings).
  3. Aggregate by site (mapping employee.work_location → masters.sites.id).
  4. Upsert one row per (date, site_id) into facts.fact_headcount_daily.

For now this is a stub so the registry has something to point at. The cron
entry point treats `paycom_configured=False` as "no work to do today" and
exits 0 cleanly — never invokes the extractor. Tests verify the no-op path.

When the credential lands, drop it in Key Vault as `paycom-client-secret`,
wire the corresponding KV reference into the Container Apps Job env, and
the cron starts consuming it on the next run.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .result import ExtractionResult


async def extract_headcount_daily(db: AsyncSession) -> ExtractionResult:
    """Stub. Replace once Paycom API access is granted."""
    _ = db
    return ExtractionResult(
        rows_written=0,
        warnings=["TODO: implement Paycom headcount extractor when API access is granted"],
    )
