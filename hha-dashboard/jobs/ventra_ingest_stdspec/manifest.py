"""Zip-drop loader for the row-level (Standard Spec) Ventra ingest.

Phase 4Z change: Ventra delivers a single ``.zip`` per drop (no
``_MANIFEST.csv``) per their 2026-06-22 reply. This module downloads the
zip, validates + unzips it in memory, and returns the 5 CSV byte blobs
keyed by file name. The zip's own CRC32 (validated by ``ZipFile.read``)
replaces the manifest sha256/row-count checks — integrity is per-member
and automatic.

Validation rules preserved under the zip model:
  - V1  zip is well-formed, within the size guards, contains only known
        members, and every member's CRC32 is intact
  - V2  all 5 expected files are present
  - V3  per-member CRC32 (enforced by ``zipfile`` on read; a corrupt
        member raises ``BadZipFile``, mapped to ValidationError)

Drop date comes from the zip filename (``HHA_Extact_20260610.zip`` ->
2026-06-10), tolerant of the vendor's ``Extact``/``Extract`` spelling and
of an optional dated subfolder before the zip.

The module name stays ``manifest.py`` for git continuity; there is no
longer a CSV manifest in the contract.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date

from app.services import blob

from .exceptions import ValidationError

VENDOR_INBOUND_CONTAINER = "vendor-inbound"
VENTRA_STDSPEC_PREFIX = "ventra/stdspec"

# The 5 files HHA ingests (2026-06-15 decision; filenames confirmed by
# Ventra 2026-06-22). Matched by stem so Invoice.csv / invoice.CSV resolve.
KNOWN_FILE_STEMS = frozenset(
    {"invoice", "chargelines", "physician", "facility", "transactionsalt"}
)

# Zip-bomb guards. The real drop is ~35 MB uncompressed across 5 files;
# these caps are generous headroom, not a tight fit. A drop that exceeds
# them is rejected as V1 before any member is decompressed.
MAX_ZIP_ENTRIES = 50
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024  # 500 MB

_DROP_DATE_RE = re.compile(r"(\d{8})")


def file_stem(file_name: str) -> str:
    """Normalize a delivered file name to its routing stem.

    Lowercases, drops the directory + extension, and removes non-alphanumeric
    characters so ``ChargeLines.csv`` / ``charge-lines.CSV`` / ``ChargeLines``
    all map to ``chargelines``.
    """
    base = file_name.strip().rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return "".join(ch for ch in base.lower() if ch.isalnum())


def drop_date_from_zip_name(zip_name: str) -> date:
    """Parse the drop date from the zip filename.

    Reads the first 8-digit run as ``YYYYMMDD`` (e.g.
    ``HHA_Extact_20260610.zip`` -> 2026-06-10). Tolerant of the vendor's
    ``Extact``/``Extract`` spelling and of any directory prefix.

    Raises ``ValidationError(rule='V1')`` if no parseable calendar date is
    present in the name.
    """
    base = zip_name.strip().rsplit("/", 1)[-1]
    match = _DROP_DATE_RE.search(base)
    if match is None:
        raise ValidationError(
            rule="V1",
            safe_message="zip filename has no YYYYMMDD drop date",
            internal_details={"zip_name": base},
        )
    digits = match.group(1)
    try:
        return date(int(digits[0:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError as e:
        raise ValidationError(
            rule="V1",
            safe_message="zip filename date is not a valid calendar date",
            internal_details={"zip_name": base, "digits": digits},
        ) from e


@dataclass(frozen=True, slots=True)
class ZipDrop:
    """One unzipped Standard Spec drop, fully in memory.

    ``file_bytes`` maps the delivered file name (e.g. ``Invoice.csv``) to
    its raw CSV bytes. ``zip_file_name`` + ``zip_sha256`` form the V13
    dedup key — one ``ops.processed_files`` ledger row per drop, not per
    member. ``total_rows`` is the summed data-row count across the 5 files
    (header excluded) for telemetry.
    """

    drop_date: date
    zip_file_name: str
    zip_sha256: str
    file_bytes: dict[str, bytes]
    total_rows: int

    @property
    def file_names(self) -> list[str]:
        return list(self.file_bytes.keys())


def _is_noise_member(name: str) -> bool:
    """True for zip members we ignore: directories + macOS/OS cruft.

    Skips directory entries (trailing slash), the ``__MACOSX/`` resource
    fork tree, and dotfiles like ``.DS_Store`` so a zip created on a Mac
    doesn't fail the unknown-member check.
    """
    base = name.rsplit("/", 1)[-1]
    return (
        name.endswith("/")
        or name.startswith("__MACOSX/")
        or base.startswith(".")
        or base == ""
    )


def unzip_drop(zip_bytes: bytes, zip_blob_path: str) -> ZipDrop:
    """V1 + V2 + V3 — validate + unzip a Standard Spec drop in memory.

    - V1: the zip is well-formed, within the size guards, and every
          non-noise member routes to a known file stem (no unknowns, no
          duplicates).
    - V3: each member's CRC32 is checked by ``ZipFile.read`` — a corrupt
          member raises ``BadZipFile``, mapped to ValidationError(V1).
    - V2: all 5 ``KNOWN_FILE_STEMS`` are present after extraction.

    Never writes to disk. The decompressed bytes live only in the returned
    dict and are released to GC once the aggregator has consumed them.
    """
    zip_name = zip_blob_path.rsplit("/", 1)[-1]
    drop_date = drop_date_from_zip_name(zip_name)
    zip_sha256 = hashlib.sha256(zip_bytes).hexdigest()

    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        raise ValidationError(
            rule="V1",
            safe_message="delivered file is not a valid zip",
            internal_details={"zip_name": zip_name},
        ) from e

    with archive as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise ValidationError(
                rule="V1",
                safe_message="zip has too many entries",
                internal_details={"entries": len(infos), "max": MAX_ZIP_ENTRIES},
            )
        total_uncompressed = sum(info.file_size for info in infos)
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise ValidationError(
                rule="V1",
                safe_message="zip uncompressed size exceeds the limit",
                internal_details={
                    "uncompressed_bytes": total_uncompressed,
                    "max": MAX_UNCOMPRESSED_BYTES,
                },
            )

        file_bytes: dict[str, bytes] = {}
        seen_stems: set[str] = set()
        for info in infos:
            if _is_noise_member(info.filename):
                continue
            stem = file_stem(info.filename)
            if stem not in KNOWN_FILE_STEMS:
                raise ValidationError(
                    rule="V1",
                    safe_message=f"zip contains an unexpected file {info.filename!r}",
                    internal_details={
                        "file_name": info.filename,
                        "stem": stem,
                        "known_stems": sorted(KNOWN_FILE_STEMS),
                    },
                )
            if stem in seen_stems:
                raise ValidationError(
                    rule="V1",
                    safe_message=f"zip contains duplicate {stem} files",
                    internal_details={"stem": stem, "file_name": info.filename},
                )
            seen_stems.add(stem)
            base = info.filename.rsplit("/", 1)[-1]
            try:
                # .read() validates the member's CRC32 and decompresses it.
                # A corrupt member can surface as BadZipFile (CRC mismatch),
                # zlib.error / EOFError (broken deflate stream), OSError, or a
                # decode error from a mangled local header. Any failure on
                # this untrusted-vendor read is a V3 integrity failure that
                # must quarantine, never crash-and-retry — so we fail closed
                # on Exception and re-raise as a PHI-safe ValidationError.
                file_bytes[base] = zf.read(info)
            except Exception as e:  # noqa: BLE001 — fail-closed on untrusted zip member
                raise ValidationError(
                    rule="V1",
                    safe_message=f"zip member {base!r} failed its integrity check",
                    internal_details={"file_name": base},
                ) from e

    missing = KNOWN_FILE_STEMS - seen_stems
    if missing:
        raise ValidationError(
            rule="V2",
            safe_message="zip is missing required files",
            internal_details={
                "missing_stems": sorted(missing),
                "present": sorted(seen_stems),
            },
        )

    total_rows = sum(max(0, len(data.splitlines()) - 1) for data in file_bytes.values())

    return ZipDrop(
        drop_date=drop_date,
        zip_file_name=zip_name,
        zip_sha256=zip_sha256,
        file_bytes=file_bytes,
        total_rows=total_rows,
    )


async def load_zip_drop(zip_blob_path: str) -> ZipDrop:
    """Download the drop zip from blob storage and unzip it in memory.

    ``zip_blob_path`` is the path relative to vendor-inbound taken from the
    Event Grid subject — e.g. ``ventra/stdspec/HHA_Extact_20260610.zip`` or
    ``ventra/stdspec/2026-06-10/HHA_Extact_20260610.zip`` (a dated subfolder
    is tolerated). Returns a :class:`ZipDrop`; raises ``ValidationError`` on
    any V1/V2/V3 failure.
    """
    zip_bytes = await blob.download_bytes(
        container_name=VENDOR_INBOUND_CONTAINER, blob_name=zip_blob_path
    )
    return unzip_drop(zip_bytes, zip_blob_path)


__all__ = [
    "KNOWN_FILE_STEMS",
    "VENDOR_INBOUND_CONTAINER",
    "VENTRA_STDSPEC_PREFIX",
    "ZipDrop",
    "drop_date_from_zip_name",
    "file_stem",
    "load_zip_drop",
    "unzip_drop",
]
