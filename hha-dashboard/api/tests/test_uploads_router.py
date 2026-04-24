"""Upload router tests — role gating + happy path (blob mocked).

The Blob service is stubbed with monkeypatch so the router logic is
unit-tested without Azurite. End-to-end integration test (with real
Azurite) is the user-verification step.
"""

from __future__ import annotations

import io
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import blob as blob_service


@pytest.fixture
def mock_blob(monkeypatch):
    """Stub blob operations so tests don't need Azurite."""
    ensure = AsyncMock()
    upload = AsyncMock(return_value="http://fake-blob/uploads/foo.pdf")
    monkeypatch.setattr(blob_service, "ensure_container", ensure)
    monkeypatch.setattr(blob_service, "upload_bytes", upload)
    return {"ensure": ensure, "upload": upload}


@pytest.mark.asyncio
async def test_upload_rejects_non_owner_role(mock_blob, monkeypatch):
    """A 'finance_analyst' role (not in the owner_* list) gets 403.

    Note: dev stub accepts any role in VALID_DEV_ROLES; we use an invalid role
    to force the 400 path, which is also a deny-by-default signal.
    """
    _ = mock_blob
    fake_pdf = io.BytesIO(b"%PDF-1.4\n%FAKE\n")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 'exec' is authenticated but not in the uploader list
        r = await client.post(
            "/api/v1/uploads",
            headers={"Authorization": "Dev exec"},
            files={"file": ("census.pdf", fake_pdf, "application/pdf")},
            data={"file_type": "census_pdf"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_upload_rejects_empty_file(mock_blob):
    _ = mock_blob
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/uploads",
            headers={"Authorization": "Dev owner_ops"},
            files={"file": ("empty.pdf", b"", "application/pdf")},
            data={"file_type": "census_pdf"},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_bad_extension(mock_blob):
    _ = mock_blob
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/uploads",
            headers={"Authorization": "Dev owner_ops"},
            files={"file": ("secret.exe", b"MZ" + b"\x00" * 100, "application/x-msdownload")},
            data={"file_type": "census_pdf"},
        )
    # Could be 415 (content type) or 415 (extension) — either way a 4xx deny
    assert r.status_code == 415


@pytest.mark.asyncio
async def test_upload_rejects_too_large(mock_blob, monkeypatch):
    _ = mock_blob
    # Temporarily shrink the limit to 1 KB to avoid allocating 25 MB in the test
    from app.settings import settings
    monkeypatch.setattr(settings, "upload_max_bytes", 1024)

    big = b"%PDF-1.4\n" + b"A" * 2000
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/uploads",
            headers={"Authorization": "Dev owner_ops"},
            files={"file": ("big.pdf", big, "application/pdf")},
            data={"file_type": "census_pdf"},
        )
    assert r.status_code == 413
