"""Clinical XLSX extractor — STUB. Real implementation lands in Session 4.

Expected contract: parses weekly chart audit results (H&P/DC timeliness %,
LOS by site) from Dr. Aneja / Dr. Reddy's audit spreadsheet, upserts to
entries.weekly_clinical.
"""

from app.models.uploads import UploadLog
from sqlalchemy.ext.asyncio import AsyncSession

from .census_pdf import ExtractionResult


async def extract_clinical_xlsx(
    data: bytes, upload_row: UploadLog, db: AsyncSession
) -> ExtractionResult:
    raise NotImplementedError(
        "clinical_xlsx extractor is not yet implemented. "
        "Lands in Session 4 alongside the weekly-clinical workflow."
    )
