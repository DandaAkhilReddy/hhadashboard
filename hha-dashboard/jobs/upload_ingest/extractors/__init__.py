"""Extractor registry. ROUTES maps FileType.value -> async callable.

Each extractor has signature:
    async def extract(
        pdf_or_excel_bytes: bytes,
        upload_row: UploadLog,
        db: AsyncSession,
    ) -> ExtractionResult

`ExtractionResult` just needs `rows_written: int` and `warnings: list[str]`.
"""

from .census_pdf import extract_census_pdf
from .clinical_xlsx import extract_clinical_xlsx
from .finance_xlsx import extract_finance_xlsx
from .hr_xlsx import extract_hr_xlsx

ROUTES = {
    "census_pdf": extract_census_pdf,
    "finance_xlsx": extract_finance_xlsx,
    "clinical_xlsx": extract_clinical_xlsx,
    "hr_xlsx": extract_hr_xlsx,
}

__all__ = ["ROUTES"]
