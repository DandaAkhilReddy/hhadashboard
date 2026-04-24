"""HR XLSX extractor — STUB. Real implementation lands in Session 4.

Expected contract: parses Andrea's weekly HR export (headcount W-2 vs 1099,
open positions by site, turnover), upserts to entries.weekly_hr_manual and/or
facts.fact_headcount_daily.
"""

from app.models.uploads import UploadLog
from sqlalchemy.ext.asyncio import AsyncSession

from .census_pdf import ExtractionResult


async def extract_hr_xlsx(
    data: bytes, upload_row: UploadLog, db: AsyncSession
) -> ExtractionResult:
    raise NotImplementedError(
        "hr_xlsx extractor is not yet implemented. "
        "Lands in Session 4 alongside the weekly-HR workflow."
    )
