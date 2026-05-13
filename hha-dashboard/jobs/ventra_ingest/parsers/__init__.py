"""Per-file parsers for the Ventra ingest pipeline.

Each parser owns V5 (schema match) and the per-file-row validators (V7,
V10, V11) for one file type. Cross-file validators (V6, V9, V12, V13)
live in the parent ``validators.py`` module.

The dispatch table maps the manifest's known file names (defined in
``manifest.KNOWN_FILE_NAMES``) to the parser function for that file. The
orchestrator in ``main.py`` calls ``parse_file(name, data)`` once per
manifest entry after V1-V4 have run.

Return type is the file-specific Pydantic row model (a subclass of
``pydantic.BaseModel``). The cross-file validators in C11 accept a
``dict[str, list[BaseModel]]`` keyed by file_name so they can branch on
content shape.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from .ar_snapshot import ARSnapshotRow, parse_ar_snapshot
from .collections import CollectionsRow, parse_collections
from .physician_monthly import PhysicianMonthlyRow, parse_physician_monthly


# Dispatch: file name (matches manifest.KNOWN_FILE_NAMES) -> parser fn.
# Every value returns ``list[<RowModel>]``; callers should keep the
# concrete row type narrow when downstream code branches on it.
_PARSER_BY_FILE_NAME: dict[str, Callable[[bytes], list[BaseModel]]] = {
    "collections.csv": parse_collections,            # type: ignore[dict-item]
    "ar_snapshot.csv": parse_ar_snapshot,            # type: ignore[dict-item]
    "physician_monthly.csv": parse_physician_monthly,  # type: ignore[dict-item]
}


def parse_file(file_name: str, data: bytes) -> list[BaseModel]:
    """Dispatch by file name. Caller has already verified the name is in
    ``manifest.KNOWN_FILE_NAMES`` (V1), so a KeyError here would be a
    programmer error, not a vendor-data issue."""
    return _PARSER_BY_FILE_NAME[file_name](data)


__all__ = [
    "ARSnapshotRow",
    "CollectionsRow",
    "PhysicianMonthlyRow",
    "parse_ar_snapshot",
    "parse_collections",
    "parse_file",
    "parse_physician_monthly",
]
