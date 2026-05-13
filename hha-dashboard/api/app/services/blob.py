"""Azure Blob Storage wrapper.

Auth strategy:
- Prod: DefaultAzureCredential picks up Managed Identity → no secrets
- Dev: settings.azure_storage_connection_string points at Azurite emulator

All operations are async via azure-storage-blob.aio.

Per ADR-001: blobs may contain PHI in raw form (census PDFs with patient
names), but this module is used ONLY to:
- store raw bytes as-is (upload endpoint)
- fetch bytes for the cron extractor (in-memory only, never to disk)
- tag metadata (status, sha256, processed_at)
- list unprocessed blobs

The extractor discards the bytes after aggregation. The Azure Blob
lifecycle policy (configured in Bicep, Session 7) deletes blobs 7 days
after they're tagged status=processed.
"""

from __future__ import annotations

import logging
from typing import Any

from azure.core.exceptions import ResourceExistsError
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobServiceClient, ContainerClient

from ..settings import settings

log = logging.getLogger(__name__)


def _build_client() -> BlobServiceClient:
    """Dev uses connection string → Azurite. Prod uses Managed Identity → real Azure."""
    conn_str = settings.azure_storage_connection_string
    if conn_str:
        return BlobServiceClient.from_connection_string(conn_str)
    return BlobServiceClient(
        account_url=settings.azure_storage_account_url,
        credential=DefaultAzureCredential(),
    )


async def ensure_container(container_name: str) -> None:
    """Create the container if it doesn't exist. Safe to call repeatedly."""
    client = _build_client()
    try:
        try:
            await client.create_container(container_name)
            log.info("blob.container_created name=%s", container_name)
        except ResourceExistsError:
            pass
    finally:
        await client.close()


async def upload_bytes(
    container_name: str,
    blob_name: str,
    data: bytes,
    *,
    content_type: str,
    metadata: dict[str, str] | None = None,
    overwrite: bool = False,
) -> str:
    """Upload raw bytes to a blob. Returns the blob URL."""
    client = _build_client()
    try:
        container = client.get_container_client(container_name)
        blob = container.get_blob_client(blob_name)
        await blob.upload_blob(
            data,
            overwrite=overwrite,
            content_type=content_type,
            metadata=metadata or {},
        )
        return blob.url
    finally:
        await client.close()


async def download_bytes(container_name: str, blob_name: str) -> bytes:
    """Read a blob into memory. Never writes to disk. Caller is responsible
    for discarding the returned bytes after use (GC will take it)."""
    client = _build_client()
    try:
        container = client.get_container_client(container_name)
        blob = container.get_blob_client(blob_name)
        stream = await blob.download_blob()
        return await stream.readall()
    finally:
        await client.close()


async def set_metadata(
    container_name: str,
    blob_name: str,
    metadata: dict[str, str],
) -> None:
    """Replace (not merge) a blob's metadata. Used to flip status=uploaded → processed."""
    client = _build_client()
    try:
        container = client.get_container_client(container_name)
        blob = container.get_blob_client(blob_name)
        await blob.set_blob_metadata(metadata)
    finally:
        await client.close()


async def get_metadata(container_name: str, blob_name: str) -> dict[str, str]:
    client = _build_client()
    try:
        container = client.get_container_client(container_name)
        blob = container.get_blob_client(blob_name)
        props = await blob.get_blob_properties()
        return dict(props.metadata or {})
    finally:
        await client.close()


async def list_by_prefix(
    container_name: str,
    prefix: str,
    *,
    include_metadata: bool = True,
) -> list[dict[str, Any]]:
    """List blobs under a prefix (e.g. 'uploads/census_pdf/')."""
    client = _build_client()
    out: list[dict[str, Any]] = []
    try:
        container: ContainerClient = client.get_container_client(container_name)
        include = ["metadata"] if include_metadata else None
        async for blob in container.list_blobs(name_starts_with=prefix, include=include):
            out.append(
                {
                    "name": blob.name,
                    "size": blob.size,
                    "last_modified": blob.last_modified,
                    "metadata": dict(blob.metadata or {}),
                }
            )
        return out
    finally:
        await client.close()


async def delete_blob(container_name: str, blob_name: str) -> None:
    """Immediate delete. Prefer letting the lifecycle policy handle retention."""
    client = _build_client()
    try:
        container = client.get_container_client(container_name)
        await container.delete_blob(blob_name)
    finally:
        await client.close()


async def copy_blob(
    source_container: str,
    source_blob: str,
    dest_container: str,
    dest_blob: str,
) -> None:
    """Server-side copy within the same storage account.

    Used by the Ventra quarantine flow (jobs/ventra_ingest/quarantine.py)
    to move failed-validation drops from vendor-inbound to vendor-quarantine
    without re-uploading bytes from the client. Idempotent: a second copy
    to the same dest overwrites.

    For same-account copies on Azure Blob the operation is synchronous
    from the server's perspective — start_copy_from_url returns when the
    copy is complete for small blobs (< 256 MiB). Pre-aggregated Ventra
    CSVs are < 1 MiB total, so we do not poll for completion.
    """
    client = _build_client()
    try:
        source_url = (
            f"{client.url}{source_container}/{source_blob}"
        )
        dest = client.get_container_client(dest_container).get_blob_client(dest_blob)
        await dest.start_copy_from_url(source_url)
    finally:
        await client.close()
