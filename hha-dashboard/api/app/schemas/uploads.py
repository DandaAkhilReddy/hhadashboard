from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class FileType(StrEnum):
    CENSUS_PDF = "census_pdf"
    FINANCE_XLSX = "finance_xlsx"
    CLINICAL_XLSX = "clinical_xlsx"
    HR_XLSX = "hr_xlsx"
    UNKNOWN = "unknown"


class UploadStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    ERROR = "error"
    EXPIRED = "expired"


class UploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uploaded_by_upn: str
    uploaded_at: datetime
    file_type: str
    original_filename: str
    blob_name: str
    size_bytes: int
    sha256: str
    status: str
    processing_started_at: datetime | None
    processing_finished_at: datetime | None
    rows_written: int | None
    error_message: str | None
    retry_count: int


class UploadAcceptedOut(BaseModel):
    """Response when a file is successfully uploaded + queued."""

    id: int
    status: str
    file_type: str
    message: str = "Upload accepted. Will be processed within 15 minutes."
