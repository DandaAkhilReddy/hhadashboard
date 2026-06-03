"""Manifest parser + V1-V4 validators for the row-level pipeline.

Mirrors the pre-aggregated path's manifest.py from PR #54 with deltas:

  - VENTRA_PREFIX = 'ventra/stdspec' (one level deeper).
  - KNOWN_FILE_NAMES = {'invoice.csv', 'guarantor.csv'} (row-level files,
    not the pre-aggregated trio).
  - Exceptions are the SafeMessageError-based ValidationError from
    ``exceptions.py``; error details carry only file/line/sha8 — never
    raw row content.
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import date

from pydantic import BaseModel, Field

from app.services import blob

from .exceptions import ValidationError

VENDOR_INBOUND_CONTAINER = "vendor-inbound"
VENTRA_STDSPEC_PREFIX = "ventra/stdspec"

MANIFEST_REQUIRED_COLUMNS = frozenset({"file_name", "sha256", "row_count"})

# Known data-file names HHA accepts in a stdspec drop. Anything else
# listed in the manifest is a V1 schema-drift quarantine.
KNOWN_FILE_NAMES = frozenset(
    {
        "invoice.csv",
        "guarantor.csv",
    }
)


class ManifestEntry(BaseModel):
    """One row in ``_MANIFEST.csv``."""

    file_name: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_count: int = Field(ge=0)


class Manifest(BaseModel):
    """Parsed manifest with metadata derived from the blob path."""

    drop_date: date
    entries: list[ManifestEntry]

    @property
    def total_rows(self) -> int:
        return sum(e.row_count for e in self.entries)

    @property
    def file_names(self) -> list[str]:
        return [e.file_name for e in self.entries]


def _drop_path(drop_date: date) -> str:
    """Folder path inside ``vendor-inbound`` for a given drop_date.

    Returns e.g. ``ventra/stdspec/2026-06-03``.
    """
    return f"{VENTRA_STDSPEC_PREFIX}/{drop_date.isoformat()}"


def parse_manifest_bytes(data: bytes, drop_date: date) -> Manifest:
    """V1 — parse ``_MANIFEST.csv`` content.

    Raises ``ValidationError(rule='V1')`` on:
      - UTF-8 decode failure
      - missing header
      - missing required column
      - malformed row (bad sha256, non-int row_count)
      - file_name not in KNOWN_FILE_NAMES
      - empty data section
      - duplicate file_name within a single manifest

    Error details are PHI-safe — they contain only line numbers, file
    names, sha256 prefixes, and the column names involved.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValidationError(
            rule="V1",
            safe_message="manifest is not valid UTF-8",
            internal_details={"decode_error": str(e)},
        ) from e

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValidationError(
            rule="V1",
            safe_message="manifest is empty (no header row)",
        )

    missing_cols = MANIFEST_REQUIRED_COLUMNS - set(reader.fieldnames)
    if missing_cols:
        raise ValidationError(
            rule="V1",
            safe_message="manifest is missing required columns",
            internal_details={
                "missing": sorted(missing_cols),
                "got": list(reader.fieldnames),
            },
        )

    entries: list[ManifestEntry] = []
    for line_no, row in enumerate(reader, start=2):
        try:
            entry = ManifestEntry(
                file_name=row["file_name"].strip(),
                sha256=row["sha256"].strip().lower(),
                row_count=int(row["row_count"]),
            )
        except (ValueError, KeyError) as e:
            raise ValidationError(
                rule="V1",
                safe_message=f"manifest row {line_no} is malformed",
                internal_details={"line_no": line_no, "error_class": type(e).__name__},
            ) from e

        if entry.file_name not in KNOWN_FILE_NAMES:
            raise ValidationError(
                rule="V1",
                safe_message=f"manifest references unknown file {entry.file_name!r}",
                internal_details={
                    "line_no": line_no,
                    "file_name": entry.file_name,
                    "known_files": sorted(KNOWN_FILE_NAMES),
                },
            )
        entries.append(entry)

    if not entries:
        raise ValidationError(
            rule="V1",
            safe_message="manifest has zero data rows",
        )

    names = [e.file_name for e in entries]
    if len(set(names)) != len(names):
        raise ValidationError(
            rule="V1",
            safe_message="manifest contains duplicate file_name entries",
            internal_details={"file_names": names},
        )

    return Manifest(drop_date=drop_date, entries=entries)


async def verify_manifest_presence(manifest: Manifest) -> None:
    """V2 — every file in the manifest exists in the drop folder."""
    drop_dir = _drop_path(manifest.drop_date)
    listed = await blob.list_by_prefix(
        container_name=VENDOR_INBOUND_CONTAINER,
        prefix=f"{drop_dir}/",
        include_metadata=False,
    )
    existing = {b["name"].rsplit("/", 1)[-1] for b in listed}
    expected = {e.file_name for e in manifest.entries}
    missing = expected - existing
    if missing:
        raise ValidationError(
            rule="V2",
            safe_message="manifest references files not present in drop folder",
            internal_details={
                "missing": sorted(missing),
                "present": sorted(existing),
                "drop_path": drop_dir,
            },
        )


async def verify_manifest_checksums(manifest: Manifest) -> dict[str, bytes]:
    """V3 + V4 — download each file, verify SHA-256 + row count.

    Returns ``{file_name: bytes}`` so the caller does not re-download
    for parsing. Bytes are released to GC after the aggregator consumes
    them; never persisted.
    """
    drop_dir = _drop_path(manifest.drop_date)
    out: dict[str, bytes] = {}

    for entry in manifest.entries:
        blob_path = f"{drop_dir}/{entry.file_name}"
        data = await blob.download_bytes(
            container_name=VENDOR_INBOUND_CONTAINER, blob_name=blob_path
        )

        actual_sha = hashlib.sha256(data).hexdigest()
        if actual_sha != entry.sha256:
            raise ValidationError(
                rule="V3",
                safe_message=f"sha256 mismatch on {entry.file_name}",
                internal_details={
                    "file_name": entry.file_name,
                    # 8-char prefixes — full hashes can hint at content.
                    "expected_sha256_prefix": entry.sha256[:8],
                    "actual_sha256_prefix": actual_sha[:8],
                },
            )

        actual_rows = max(0, len(data.splitlines()) - 1)
        if actual_rows != entry.row_count:
            raise ValidationError(
                rule="V4",
                safe_message=f"row_count mismatch on {entry.file_name}",
                internal_details={
                    "file_name": entry.file_name,
                    "expected_row_count": entry.row_count,
                    "actual_row_count": actual_rows,
                },
            )

        out[entry.file_name] = data

    return out


async def load_manifest(
    drop_date: date, manifest_blob_path: str
) -> tuple[Manifest, dict[str, bytes]]:
    """V1 + V2 + V3 + V4 in one call.

    ``manifest_blob_path`` is the full blob path from the Event Grid
    event subject (e.g. ``ventra/stdspec/2026-06-03/_MANIFEST.csv``).
    Caller extracted ``drop_date`` from that path; we trust it.
    """
    manifest_bytes = await blob.download_bytes(
        container_name=VENDOR_INBOUND_CONTAINER, blob_name=manifest_blob_path
    )
    manifest = parse_manifest_bytes(manifest_bytes, drop_date)
    await verify_manifest_presence(manifest)
    file_bytes = await verify_manifest_checksums(manifest)
    return manifest, file_bytes


__all__ = [
    "KNOWN_FILE_NAMES",
    "MANIFEST_REQUIRED_COLUMNS",
    "VENDOR_INBOUND_CONTAINER",
    "VENTRA_STDSPEC_PREFIX",
    "Manifest",
    "ManifestEntry",
    "load_manifest",
    "parse_manifest_bytes",
    "verify_manifest_checksums",
    "verify_manifest_presence",
]
