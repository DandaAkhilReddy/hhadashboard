"""Manifest parser + V1-V4 validators for the Ventra ingest pipeline.

Per ADR-006 the vendor writes ``_MANIFEST.csv`` as the LAST file in each
``vendor-inbound/ventra/YYYY-MM-DD/`` folder. The manifest contains one
row per data file with the file name, its SHA-256 hex digest, and its
row count (excluding header). The ``manifest-last`` pattern means a
partial drop never triggers the job — Event Grid only fires on the
manifest blob create event.

This module owns V1-V4:

  V1: ``_MANIFEST.csv`` parses; has columns ``file_name, sha256, row_count``
  V2: every file listed in the manifest exists in the drop folder
  V3: SHA-256 of each blob's bytes matches the manifest digest
  V4: actual row count of each file matches the manifest

V5-V11 (per-file schema + content validation) live in ``parsers/*``.
V12-V13 (cross-file FL-only + dedup) live in ``validators.py``.
V14 (source_system invariant) is enforced by the DB CHECK constraint
from migration 0011.
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
VENTRA_PREFIX = "ventra"

MANIFEST_REQUIRED_COLUMNS = frozenset({"file_name", "sha256", "row_count"})

# Known data-file names HHA accepts in a Ventra drop. Anything else listed
# in the manifest is a V2 schema-drift quarantine.
KNOWN_FILE_NAMES = frozenset(
    {
        "collections.csv",
        "ar_snapshot.csv",
        "physician_monthly.csv",
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
    """Folder path inside ``vendor-inbound`` for a given drop_date."""
    return f"{VENTRA_PREFIX}/{drop_date.isoformat()}"


def parse_manifest_bytes(data: bytes, drop_date: date) -> Manifest:
    """V1 — parse ``_MANIFEST.csv`` content.

    Raises ``ValidationError(rule='V1', ...)`` if:
      - the bytes do not decode as UTF-8
      - the CSV header lacks any of ``file_name, sha256, row_count``
      - any row has a malformed sha256 (not 64 hex chars)
      - any row has a non-numeric or negative row_count
      - any ``file_name`` is not in the known-files allowlist
      - the manifest is empty (zero data rows)
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValidationError(
            rule="V1",
            message="manifest is not valid UTF-8",
            details={"decode_error": str(e)},
        ) from e

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValidationError(
            rule="V1",
            message="manifest is empty (no header row)",
        )

    missing_cols = MANIFEST_REQUIRED_COLUMNS - set(reader.fieldnames)
    if missing_cols:
        raise ValidationError(
            rule="V1",
            message="manifest is missing required columns",
            details={
                "missing": sorted(missing_cols),
                "got": list(reader.fieldnames),
            },
        )

    entries: list[ManifestEntry] = []
    for line_no, row in enumerate(reader, start=2):  # 1 = header
        try:
            entry = ManifestEntry(
                file_name=row["file_name"].strip(),
                sha256=row["sha256"].strip().lower(),
                row_count=int(row["row_count"]),
            )
        except (ValueError, KeyError) as e:
            raise ValidationError(
                rule="V1",
                message=f"manifest row {line_no} is malformed",
                details={"line_no": line_no, "row": dict(row), "error": str(e)},
            ) from e

        if entry.file_name not in KNOWN_FILE_NAMES:
            raise ValidationError(
                rule="V1",
                message=f"manifest references unknown file {entry.file_name!r}",
                details={
                    "line_no": line_no,
                    "file_name": entry.file_name,
                    "known_files": sorted(KNOWN_FILE_NAMES),
                },
            )
        entries.append(entry)

    if not entries:
        raise ValidationError(
            rule="V1",
            message="manifest has zero data rows",
        )

    # File-name uniqueness within a single manifest.
    names = [e.file_name for e in entries]
    if len(set(names)) != len(names):
        raise ValidationError(
            rule="V1",
            message="manifest contains duplicate file_name entries",
            details={"file_names": names},
        )

    return Manifest(drop_date=drop_date, entries=entries)


async def verify_manifest_presence(manifest: Manifest) -> None:
    """V2 — every ``ManifestEntry.file_name`` exists in the drop folder.

    Reads the existing list under ``vendor-inbound/ventra/YYYY-MM-DD/`` and
    asserts every listed file is present. Raises ``ValidationError(rule='V2')``
    on the first missing file with the full missing list in details.
    """
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
            message="manifest references files not present in drop folder",
            details={
                "missing": sorted(missing),
                "present": sorted(existing),
                "drop_path": drop_dir,
            },
        )


async def verify_manifest_checksums(manifest: Manifest) -> dict[str, bytes]:
    """V3 + V4 — download each file, verify SHA-256 + row count.

    Returns a ``{file_name: bytes}`` dict so the caller does not have to
    re-download for parsing (V5-V11). Bytes are kept in memory only —
    the pre-aggregated CSVs are tiny (<100 KB total).

    Raises ``ValidationError(rule='V3')`` on first SHA mismatch or
    ``ValidationError(rule='V4')`` on first row-count mismatch.
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
                message=f"sha256 mismatch on {entry.file_name}",
                details={
                    "file_name": entry.file_name,
                    "expected_sha256": entry.sha256,
                    "actual_sha256": actual_sha,
                },
            )

        # Row count = total lines minus the header. Empty trailing newline
        # is tolerated by splitlines() (does not produce an empty entry).
        actual_rows = max(0, len(data.splitlines()) - 1)
        if actual_rows != entry.row_count:
            raise ValidationError(
                rule="V4",
                message=f"row_count mismatch on {entry.file_name}",
                details={
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
    """Convenience: V1 + V2 + V3 + V4 in one call.

    ``manifest_blob_path`` is the full blob path from the Event Grid event
    subject (e.g. ``ventra/2026-05-15/_MANIFEST.csv``). Caller passes
    ``drop_date`` extracted from the path so V6 (date drift) can compare
    against parsed file rows downstream.

    Returns ``(Manifest, file_bytes_by_name)``.
    """
    manifest_bytes = await blob.download_bytes(
        container_name=VENDOR_INBOUND_CONTAINER, blob_name=manifest_blob_path
    )
    manifest = parse_manifest_bytes(manifest_bytes, drop_date)            # V1
    await verify_manifest_presence(manifest)                               # V2
    file_bytes = await verify_manifest_checksums(manifest)                 # V3, V4
    return manifest, file_bytes
