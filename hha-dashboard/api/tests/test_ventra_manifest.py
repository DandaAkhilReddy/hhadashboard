"""Ventra manifest parser + V1-V4 validator tests.

V1: ``_MANIFEST.csv`` parses (required columns, valid sha256/row_count,
    known file names, no duplicates).
V2: every file in the manifest exists in the drop folder.
V3: SHA-256 of each blob matches the manifest digest.
V4: actual row count matches the manifest.

The async tests monkeypatch ``app.services.blob`` module functions; we
do not exercise real Azure Storage from unit tests.
"""

from __future__ import annotations

import hashlib
from datetime import date

import pytest
from jobs.ventra_ingest.exceptions import ValidationError
from jobs.ventra_ingest.manifest import (
    Manifest,
    ManifestEntry,
    parse_manifest_bytes,
    verify_manifest_checksums,
    verify_manifest_presence,
)

DROP = date(2026, 5, 15)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# =========================================================================
# V1 — parse_manifest_bytes
# =========================================================================


def test_v1_parses_well_formed_manifest() -> None:
    body = b"".join(
        [
            b"file_name,sha256,row_count\n",
            b"collections.csv," + _sha(b"abc").encode() + b",25\n",
            b"ar_snapshot.csv," + _sha(b"def").encode() + b",30\n",
        ]
    )
    m = parse_manifest_bytes(body, DROP)
    assert m.drop_date == DROP
    assert len(m.entries) == 2
    assert m.entries[0].file_name == "collections.csv"
    assert m.entries[0].row_count == 25
    assert m.total_rows == 55
    assert m.file_names == ["collections.csv", "ar_snapshot.csv"]


def test_v1_rejects_non_utf8() -> None:
    with pytest.raises(ValidationError) as exc:
        parse_manifest_bytes(b"\xff\xfe not utf-8", DROP)
    assert exc.value.rule == "V1"
    assert "UTF-8" in exc.value.message


def test_v1_rejects_missing_required_columns() -> None:
    body = b"file_name,sha256\ncollections.csv," + _sha(b"abc").encode() + b"\n"
    with pytest.raises(ValidationError) as exc:
        parse_manifest_bytes(body, DROP)
    assert exc.value.rule == "V1"
    assert "row_count" in exc.value.details["missing"]


def test_v1_rejects_empty_manifest() -> None:
    with pytest.raises(ValidationError) as exc:
        parse_manifest_bytes(b"file_name,sha256,row_count\n", DROP)
    assert exc.value.rule == "V1"
    assert "zero data rows" in exc.value.message


def test_v1_rejects_bad_sha_format() -> None:
    body = b"file_name,sha256,row_count\ncollections.csv,notahex,10\n"
    with pytest.raises(ValidationError) as exc:
        parse_manifest_bytes(body, DROP)
    assert exc.value.rule == "V1"


def test_v1_rejects_negative_row_count() -> None:
    body = b"file_name,sha256,row_count\ncollections.csv," + _sha(b"x").encode() + b",-1\n"
    with pytest.raises(ValidationError) as exc:
        parse_manifest_bytes(body, DROP)
    assert exc.value.rule == "V1"


def test_v1_rejects_unknown_file_name() -> None:
    body = b"file_name,sha256,row_count\nfoo.csv," + _sha(b"x").encode() + b",10\n"
    with pytest.raises(ValidationError) as exc:
        parse_manifest_bytes(body, DROP)
    assert exc.value.rule == "V1"
    assert exc.value.details["file_name"] == "foo.csv"


def test_v1_rejects_duplicate_file_names() -> None:
    body = (
        b"file_name,sha256,row_count\n"
        b"collections.csv," + _sha(b"a").encode() + b",10\n"
        b"collections.csv," + _sha(b"b").encode() + b",20\n"
    )
    with pytest.raises(ValidationError) as exc:
        parse_manifest_bytes(body, DROP)
    assert exc.value.rule == "V1"
    assert "duplicate" in exc.value.message


# =========================================================================
# V2 — verify_manifest_presence (monkeypatched list_by_prefix)
# =========================================================================


def _manifest_for(files: list[tuple[str, bytes, int]]) -> Manifest:
    """Helper: build a Manifest from (file_name, content_bytes, row_count) tuples."""
    return Manifest(
        drop_date=DROP,
        entries=[
            ManifestEntry(file_name=name, sha256=_sha(data), row_count=rc)
            for name, data, rc in files
        ],
    )


@pytest.mark.asyncio
async def test_v2_passes_when_all_files_present(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _manifest_for(
        [
            ("collections.csv", b"a\n1\n", 1),
            ("ar_snapshot.csv", b"a\n1\n", 1),
        ]
    )

    async def fake_list(container_name: str, prefix: str, *, include_metadata: bool = True) -> list[dict[str, object]]:  # noqa: ARG001
        assert prefix == "ventra/2026-05-15/"
        return [
            {"name": "ventra/2026-05-15/collections.csv", "size": 4, "last_modified": None, "metadata": {}},
            {"name": "ventra/2026-05-15/ar_snapshot.csv", "size": 4, "last_modified": None, "metadata": {}},
        ]

    monkeypatch.setattr("jobs.ventra_ingest.manifest.blob.list_by_prefix", fake_list)
    await verify_manifest_presence(manifest)  # no raise


@pytest.mark.asyncio
async def test_v2_rejects_missing_file(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _manifest_for(
        [
            ("collections.csv", b"a\n1\n", 1),
            ("ar_snapshot.csv", b"a\n1\n", 1),
        ]
    )

    async def fake_list(container_name: str, prefix: str, *, include_metadata: bool = True) -> list[dict[str, object]]:  # noqa: ARG001
        return [
            {"name": "ventra/2026-05-15/collections.csv", "size": 4, "last_modified": None, "metadata": {}},
        ]

    monkeypatch.setattr("jobs.ventra_ingest.manifest.blob.list_by_prefix", fake_list)
    with pytest.raises(ValidationError) as exc:
        await verify_manifest_presence(manifest)
    assert exc.value.rule == "V2"
    assert "ar_snapshot.csv" in exc.value.details["missing"]


# =========================================================================
# V3 + V4 — verify_manifest_checksums
# =========================================================================


@pytest.mark.asyncio
async def test_v3_v4_pass_on_matching_sha_and_count(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b"a,b\n1,2\n3,4\n"
    manifest = _manifest_for([("collections.csv", body, 2)])

    async def fake_download(container_name: str, blob_name: str) -> bytes:  # noqa: ARG001
        assert blob_name == "ventra/2026-05-15/collections.csv"
        return body

    monkeypatch.setattr("jobs.ventra_ingest.manifest.blob.download_bytes", fake_download)
    out = await verify_manifest_checksums(manifest)
    assert out["collections.csv"] == body


@pytest.mark.asyncio
async def test_v3_rejects_sha_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _manifest_for([("collections.csv", b"original", 1)])

    async def fake_download(container_name: str, blob_name: str) -> bytes:  # noqa: ARG001
        return b"tampered"

    monkeypatch.setattr("jobs.ventra_ingest.manifest.blob.download_bytes", fake_download)
    with pytest.raises(ValidationError) as exc:
        await verify_manifest_checksums(manifest)
    assert exc.value.rule == "V3"
    assert exc.value.details["file_name"] == "collections.csv"


@pytest.mark.asyncio
async def test_v4_rejects_row_count_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b"a,b\n1,2\n3,4\n"  # 1 header + 2 data rows
    manifest = Manifest(
        drop_date=DROP,
        entries=[ManifestEntry(file_name="collections.csv", sha256=_sha(body), row_count=99)],
    )

    async def fake_download(container_name: str, blob_name: str) -> bytes:  # noqa: ARG001
        return body

    monkeypatch.setattr("jobs.ventra_ingest.manifest.blob.download_bytes", fake_download)
    with pytest.raises(ValidationError) as exc:
        await verify_manifest_checksums(manifest)
    assert exc.value.rule == "V4"
    assert exc.value.details["expected_row_count"] == 99
    assert exc.value.details["actual_row_count"] == 2
