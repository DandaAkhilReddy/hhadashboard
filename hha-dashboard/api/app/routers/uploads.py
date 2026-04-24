"""Upload endpoints: POST file → Blob + upload_log row; GET recent."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import desc, select

from ..deps import CurrentUser, DBDep, UserDep, require_role
from ..models.uploads import UploadLog
from ..schemas.uploads import FileType, UploadAcceptedOut, UploadOut
from ..services import blob
from ..settings import settings

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])

# Any authenticated owner_* or admin can upload.
UploaderDep = Annotated[
    CurrentUser,
    Depends(
        require_role(
            "admin",
            "owner_ops",
            "owner_finance",
            "owner_clinical",
            "owner_hr",
        )
    ),
]


# ---------- Helpers ----------


def _allowed_extension(filename: str) -> str | None:
    """Return lowercase extension (without dot) if it's one we accept, else None."""
    ext = Path(filename).suffix.lstrip(".").lower()
    if ext in {"pdf", "xlsx", "xls", "csv"}:
        return ext
    return None


def _make_blob_name(upn: str, file_type: str, original_filename: str, sha256_hex: str) -> str:
    """Format: uploads/{type}/{YYYY-MM-DD}/{upn-sanitized}_{uuid8}_{sha8}.{ext}"""
    ext = _allowed_extension(original_filename) or "bin"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    upn_safe = upn.replace("@", "_at_").replace(".", "_")
    short_uuid = uuid.uuid4().hex[:8]
    short_sha = sha256_hex[:8]
    return f"{file_type}/{today}/{upn_safe}_{short_uuid}_{short_sha}.{ext}"


# ---------- POST /uploads ----------


@router.post(
    "",
    response_model=UploadAcceptedOut,
    status_code=status.HTTP_201_CREATED,
)
async def stage_upload(
    db: DBDep,
    user: UploaderDep,
    file: Annotated[UploadFile, File(description="The PDF / XLSX / CSV to upload")],
    file_type: Annotated[FileType, Form(description="Categorization — routes to the right extractor")],
) -> UploadAcceptedOut:
    # --- Basic validation ---
    if file.content_type and file.content_type not in settings.upload_allowed_mime_types:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported content type '{file.content_type}'. "
            f"Accepted: {', '.join(settings.upload_allowed_mime_types)}",
        )

    original_filename = file.filename or "unnamed"
    if _allowed_extension(original_filename) is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file extension in '{original_filename}'. Accepted: .pdf, .xlsx, .xls, .csv",
        )

    # --- Read bytes + size/hash check ---
    # FastAPI's UploadFile streams — we need bytes in memory to hash + upload.
    data = await file.read()
    size = len(data)
    if size == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    if size > settings.upload_max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File too large ({size} bytes). Max: {settings.upload_max_bytes} bytes.",
        )
    sha256_hex = hashlib.sha256(data).hexdigest()

    # --- Compose blob path + upload ---
    blob_name = _make_blob_name(user.upn, file_type.value, original_filename, sha256_hex)

    # Ensure container exists (idempotent) — safe to call on every upload in dev.
    # In prod, Bicep provisions this; call becomes a no-op.
    await blob.ensure_container(settings.azure_storage_uploads_container)

    await blob.upload_bytes(
        settings.azure_storage_uploads_container,
        blob_name,
        data,
        content_type=file.content_type or "application/octet-stream",
        metadata={
            "type": file_type.value,
            "uploaded_by_upn": user.upn,
            "original_filename": original_filename,
            "status": "uploaded",
            "sha256": sha256_hex,
        },
    )

    # --- Queue row in upload_log ---
    row = UploadLog(
        uploaded_by_upn=user.upn,
        file_type=file_type.value,
        original_filename=original_filename,
        blob_name=blob_name,
        size_bytes=size,
        sha256=sha256_hex,
        status="uploaded",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    return UploadAcceptedOut(
        id=row.id,
        status=row.status,
        file_type=row.file_type,
    )


# ---------- GET /uploads ----------


@router.get("", response_model=list[UploadOut])
async def list_recent_uploads(
    db: DBDep,
    user: UserDep,
    since_id: int | None = Query(default=None, description="Only return rows with id > since_id"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[UploadLog]:
    """List recent uploads. Any authenticated user can see (no PHI in rows)."""
    _ = user
    stmt = select(UploadLog).order_by(desc(UploadLog.id)).limit(limit)
    if since_id is not None:
        stmt = stmt.where(UploadLog.id > since_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())
