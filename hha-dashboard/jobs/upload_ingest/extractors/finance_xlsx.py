"""Finance XLSX extractor — STUB. Real implementation lands in Session 4.

Expected contract (when implemented): parses monthly collections +
AR aging from Ventra export or Sandy's internal Excel, upserts to
entries.monthly_finance_manual and/or facts.fact_collections_daily.
"""

from app.models.uploads import UploadLog
from sqlalchemy.ext.asyncio import AsyncSession

from .census_pdf import ExtractionResult  # reuse the dataclass


async def extract_finance_xlsx(
    data: bytes, upload_row: UploadLog, db: AsyncSession
) -> ExtractionResult:
    raise NotImplementedError(
        "finance_xlsx extractor is not yet implemented. "
        "Lands in Session 4 alongside Sandy's monthly-finance workflow."
    )
