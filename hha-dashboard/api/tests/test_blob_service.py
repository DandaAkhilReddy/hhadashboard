"""Unit tests for app.services.blob.

Every function is a thin async wrapper around azure.storage.blob.aio. We
patch _build_client() to return a MagicMock chain so the SDK paths run
without hitting Azurite or live Azure — the tests prove our argument
forwarding, error handling, and finally-close cleanup are correct.

The shape of the fake mirrors the real SDK call chain:
    BlobServiceClient
      .get_container_client(name)        → ContainerClient
      .get_container_client(name).get_blob_client(name) → BlobClient

Each leaf method (upload_blob, download_blob, etc.) is an AsyncMock so
the `await` in production code resolves cleanly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from azure.core.exceptions import ResourceExistsError

from app.services import blob as blob_module


def _make_fake_client() -> tuple[MagicMock, MagicMock, MagicMock]:
    """Build a (service_client, container_client, blob_client) chain. The
    BlobServiceClient.close() is awaitable so the `finally: await
    client.close()` in production runs without RuntimeError."""
    blob_client = MagicMock(name="BlobClient")
    blob_client.upload_blob = AsyncMock(return_value=None)
    blob_client.download_blob = AsyncMock()
    blob_client.set_blob_metadata = AsyncMock(return_value=None)
    blob_client.get_blob_properties = AsyncMock()
    blob_client.start_copy_from_url = AsyncMock(return_value=None)
    blob_client.url = "https://fake.blob.core.windows.net/c/b"

    container_client = MagicMock(name="ContainerClient")
    container_client.get_blob_client = MagicMock(return_value=blob_client)
    container_client.delete_blob = AsyncMock(return_value=None)

    service_client = MagicMock(name="BlobServiceClient")
    service_client.get_container_client = MagicMock(return_value=container_client)
    service_client.create_container = AsyncMock(return_value=None)
    service_client.close = AsyncMock(return_value=None)
    service_client.url = "https://fake.blob.core.windows.net/"

    return service_client, container_client, blob_client


# ----- _build_client() branches -----


def test_build_client_uses_connection_string_when_set() -> None:
    """Dev/local path: settings.azure_storage_connection_string is non-empty
    → BlobServiceClient.from_connection_string. Must NOT call
    DefaultAzureCredential (would hit IMDS and fail in dev)."""
    fake_client = MagicMock(name="BlobServiceClient")
    fake_from_cs = MagicMock(return_value=fake_client)
    fake_mi_factory = MagicMock(name="DefaultAzureCredential-factory")

    with (
        patch.object(
            blob_module.settings,
            "azure_storage_connection_string",
            "DefaultEndpointsProtocol=https;AccountName=x;AccountKey=k",
        ),
        patch(
            "azure.storage.blob.aio.BlobServiceClient.from_connection_string",
            fake_from_cs,
        ),
        patch("azure.identity.aio.DefaultAzureCredential", fake_mi_factory),
    ):
        client = blob_module._build_client()

    assert client is fake_client
    fake_from_cs.assert_called_once()
    fake_mi_factory.assert_not_called()


def test_build_client_falls_back_to_managed_identity_when_no_conn_str() -> None:
    """Prod path: empty connection_string → DefaultAzureCredential.

    Patch the names AS IMPORTED in app.services.blob (not at their origin)
    so the real BlobServiceClient init does not try to load aiohttp."""
    fake_credential = MagicMock(name="DefaultAzureCredential-instance")
    fake_credential_factory = MagicMock(return_value=fake_credential)
    fake_service_client = MagicMock(name="BlobServiceClient")
    fake_service_ctor = MagicMock(return_value=fake_service_client)

    with (
        patch.object(blob_module.settings, "azure_storage_connection_string", ""),
        patch.object(
            blob_module.settings,
            "azure_storage_account_url",
            "https://hha.blob.core.windows.net",
        ),
        patch.object(
            blob_module, "DefaultAzureCredential", fake_credential_factory
        ),
        patch.object(blob_module, "BlobServiceClient", fake_service_ctor),
    ):
        client = blob_module._build_client()

    assert client is fake_service_client
    fake_credential_factory.assert_called_once_with()
    fake_service_ctor.assert_called_once_with(
        account_url="https://hha.blob.core.windows.net",
        credential=fake_credential,
    )


# ----- ensure_container -----


@pytest.mark.asyncio
async def test_ensure_container_creates_when_missing() -> None:
    service_client, _, _ = _make_fake_client()

    with patch.object(blob_module, "_build_client", return_value=service_client):
        await blob_module.ensure_container("uploads")

    service_client.create_container.assert_awaited_once_with("uploads")
    service_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_container_silently_swallows_resource_exists_error() -> None:
    """Idempotent: a second call when the container already exists must
    not raise. ResourceExistsError → pass."""
    service_client, _, _ = _make_fake_client()
    service_client.create_container = AsyncMock(
        side_effect=ResourceExistsError("already exists")
    )

    with patch.object(blob_module, "_build_client", return_value=service_client):
        # No raise
        await blob_module.ensure_container("uploads")

    # close() still runs from finally even on the ResourceExistsError path
    service_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_container_still_closes_on_unexpected_error() -> None:
    """finally must run for any exception, not just ResourceExistsError."""
    service_client, _, _ = _make_fake_client()
    service_client.create_container = AsyncMock(side_effect=RuntimeError("boom"))

    with (
        patch.object(blob_module, "_build_client", return_value=service_client),
        pytest.raises(RuntimeError, match="boom"),
    ):
        await blob_module.ensure_container("uploads")

    service_client.close.assert_awaited_once()


# ----- upload_bytes -----


@pytest.mark.asyncio
async def test_upload_bytes_forwards_data_content_type_and_metadata() -> None:
    service_client, _, blob_client = _make_fake_client()

    with patch.object(blob_module, "_build_client", return_value=service_client):
        url = await blob_module.upload_bytes(
            container_name="uploads",
            blob_name="census_pdf/2026-05-13/sample.pdf",
            data=b"%PDF-fake",
            content_type="application/pdf",
            metadata={"status": "uploaded", "sha256": "deadbeef"},
            overwrite=True,
        )

    assert url == blob_client.url
    blob_client.upload_blob.assert_awaited_once_with(
        b"%PDF-fake",
        overwrite=True,
        content_type="application/pdf",
        metadata={"status": "uploaded", "sha256": "deadbeef"},
    )
    service_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_bytes_defaults_metadata_to_empty_dict() -> None:
    """metadata=None must reach the SDK as {} — passing None would make
    the SDK reject the request."""
    service_client, _, blob_client = _make_fake_client()

    with patch.object(blob_module, "_build_client", return_value=service_client):
        await blob_module.upload_bytes(
            container_name="uploads",
            blob_name="x",
            data=b"x",
            content_type="text/plain",
        )

    call_kwargs = blob_client.upload_blob.await_args.kwargs
    assert call_kwargs["metadata"] == {}
    assert call_kwargs["overwrite"] is False  # documented default


# ----- download_bytes -----


@pytest.mark.asyncio
async def test_download_bytes_returns_stream_readall_result() -> None:
    service_client, _, blob_client = _make_fake_client()
    fake_stream = MagicMock(name="StorageStreamDownloader")
    fake_stream.readall = AsyncMock(return_value=b"hello world")
    blob_client.download_blob = AsyncMock(return_value=fake_stream)

    with patch.object(blob_module, "_build_client", return_value=service_client):
        result = await blob_module.download_bytes("uploads", "x.txt")

    assert result == b"hello world"
    blob_client.download_blob.assert_awaited_once()
    fake_stream.readall.assert_awaited_once()
    service_client.close.assert_awaited_once()


# ----- set_metadata -----


@pytest.mark.asyncio
async def test_set_metadata_replaces_blob_metadata() -> None:
    service_client, _, blob_client = _make_fake_client()

    with patch.object(blob_module, "_build_client", return_value=service_client):
        await blob_module.set_metadata(
            "uploads", "x.pdf", {"status": "processed", "extractor": "v2"}
        )

    blob_client.set_blob_metadata.assert_awaited_once_with(
        {"status": "processed", "extractor": "v2"}
    )
    service_client.close.assert_awaited_once()


# ----- get_metadata -----


@pytest.mark.asyncio
async def test_get_metadata_returns_dict_copy() -> None:
    service_client, _, blob_client = _make_fake_client()
    fake_props = MagicMock(metadata={"status": "uploaded", "sha256": "abc"})
    blob_client.get_blob_properties = AsyncMock(return_value=fake_props)

    with patch.object(blob_module, "_build_client", return_value=service_client):
        result = await blob_module.get_metadata("uploads", "x.pdf")

    assert result == {"status": "uploaded", "sha256": "abc"}
    # Mutating result must not mutate the SDK's props.metadata view —
    # dict() copy contract.
    result["status"] = "mutated"
    assert fake_props.metadata == {"status": "uploaded", "sha256": "abc"}


@pytest.mark.asyncio
async def test_get_metadata_returns_empty_dict_when_sdk_has_none() -> None:
    """Defensive: dict(props.metadata or {}) handles the SDK returning
    metadata=None (happens when a blob has never had metadata set)."""
    service_client, _, blob_client = _make_fake_client()
    fake_props = MagicMock(metadata=None)
    blob_client.get_blob_properties = AsyncMock(return_value=fake_props)

    with patch.object(blob_module, "_build_client", return_value=service_client):
        result = await blob_module.get_metadata("uploads", "x.pdf")

    assert result == {}


# ----- list_by_prefix -----


class _FakeBlobItem:
    """The pieces of azure.storage.blob.BlobProperties we read in
    list_by_prefix. Minimal — only what production code touches."""

    def __init__(
        self,
        name: str,
        size: int,
        last_modified: datetime,
        metadata: dict[str, str] | None,
    ) -> None:
        self.name = name
        self.size = size
        self.last_modified = last_modified
        self.metadata = metadata


def _async_iter(items: list[Any]) -> Any:
    """Build an async-iterable that yields each item."""

    class _AI:
        def __init__(self) -> None:
            self._items = iter(items)

        def __aiter__(self) -> _AI:
            return self

        async def __anext__(self) -> Any:
            try:
                return next(self._items)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    return _AI()


@pytest.mark.asyncio
async def test_list_by_prefix_with_metadata_yields_entry_per_blob() -> None:
    service_client, container_client, _ = _make_fake_client()
    ts = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    items = [
        _FakeBlobItem("census_pdf/a.pdf", 1024, ts, {"status": "uploaded"}),
        _FakeBlobItem("census_pdf/b.pdf", 2048, ts, None),
    ]
    container_client.list_blobs = MagicMock(return_value=_async_iter(items))

    with patch.object(blob_module, "_build_client", return_value=service_client):
        result = await blob_module.list_by_prefix(
            "uploads", "census_pdf/", include_metadata=True
        )

    assert len(result) == 2
    assert result[0]["name"] == "census_pdf/a.pdf"
    assert result[0]["size"] == 1024
    assert result[0]["last_modified"] == ts
    assert result[0]["metadata"] == {"status": "uploaded"}
    # Second item had metadata=None → defensive dict(...) gives {}
    assert result[1]["metadata"] == {}

    container_client.list_blobs.assert_called_once_with(
        name_starts_with="census_pdf/", include=["metadata"]
    )


@pytest.mark.asyncio
async def test_list_by_prefix_without_metadata_passes_include_none() -> None:
    """include_metadata=False → include=None (don't fetch metadata over
    the wire, faster for large-list operations)."""
    service_client, container_client, _ = _make_fake_client()
    container_client.list_blobs = MagicMock(return_value=_async_iter([]))

    with patch.object(blob_module, "_build_client", return_value=service_client):
        await blob_module.list_by_prefix(
            "uploads", "census_pdf/", include_metadata=False
        )

    container_client.list_blobs.assert_called_once_with(
        name_starts_with="census_pdf/", include=None
    )


@pytest.mark.asyncio
async def test_list_by_prefix_returns_empty_on_no_matches() -> None:
    service_client, container_client, _ = _make_fake_client()
    container_client.list_blobs = MagicMock(return_value=_async_iter([]))

    with patch.object(blob_module, "_build_client", return_value=service_client):
        result = await blob_module.list_by_prefix("uploads", "no-such-prefix/")

    assert result == []


# ----- delete_blob -----


@pytest.mark.asyncio
async def test_delete_blob_forwards_to_container_client() -> None:
    service_client, container_client, _ = _make_fake_client()

    with patch.object(blob_module, "_build_client", return_value=service_client):
        await blob_module.delete_blob("uploads", "stale.pdf")

    container_client.delete_blob.assert_awaited_once_with("stale.pdf")
    service_client.close.assert_awaited_once()


# ----- copy_blob -----


@pytest.mark.asyncio
async def test_copy_blob_starts_server_side_copy_with_constructed_url() -> None:
    """The quarantine flow relies on this for vendor-inbound →
    vendor-quarantine. URL must be built from the service client's URL +
    container/blob, not from a different storage account."""
    service_client, container_client, blob_client = _make_fake_client()

    with patch.object(blob_module, "_build_client", return_value=service_client):
        await blob_module.copy_blob(
            source_container="vendor-inbound",
            source_blob="ventra/2026-05-13/collections.csv",
            dest_container="vendor-quarantine",
            dest_blob="ventra/2026-05-13/collections.csv",
        )

    # The destination is on vendor-quarantine
    service_client.get_container_client.assert_called_with("vendor-quarantine")
    container_client.get_blob_client.assert_called_with(
        "ventra/2026-05-13/collections.csv"
    )

    blob_client.start_copy_from_url.assert_awaited_once()
    source_url = blob_client.start_copy_from_url.await_args.args[0]
    assert source_url.startswith("https://fake.blob.core.windows.net/")
    assert "vendor-inbound" in source_url
    assert "ventra/2026-05-13/collections.csv" in source_url


@pytest.mark.asyncio
async def test_copy_blob_closes_client_even_when_copy_raises() -> None:
    """Server-side copy can fail (e.g. source missing). finally still runs."""
    service_client, _, blob_client = _make_fake_client()
    blob_client.start_copy_from_url = AsyncMock(
        side_effect=RuntimeError("source missing")
    )

    with (
        patch.object(blob_module, "_build_client", return_value=service_client),
        pytest.raises(RuntimeError, match="source missing"),
    ):
        await blob_module.copy_blob(
            source_container="vendor-inbound",
            source_blob="missing.csv",
            dest_container="vendor-quarantine",
            dest_blob="missing.csv",
        )

    service_client.close.assert_awaited_once()
