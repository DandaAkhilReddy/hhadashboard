"""Sample fixture sanity tests — proves the checked-in
samples/ventra/sample-drop-2026-06-15/ still passes V1-V11 after any
change to the validators or per-file parsers.

If this test fails after editing a parser / validator, you have one of
three options:
  1. Fix the parser change (validator is too strict; sample is realistic)
  2. Regenerate the fixture with the new schema:
       python scripts/generate_sample_ventra_drop.py 2026-06-15 \\
           samples/ventra/sample-drop-2026-06-15 --include-monthly
  3. Update the generator to match the new schema, then regenerate

No DB, no blob — pure-Python pass through the file-level validators.
V6 (drop_date drift), V12 (FL-only via masters.sites), and V13 (dedup
via ops.processed_files) require a live DB and are NOT exercised here;
they have their own integration tests.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest

from jobs.ventra_ingest.manifest import (
    KNOWN_FILE_NAMES,
    Manifest,
    parse_manifest_bytes,
)
from jobs.ventra_ingest.parsers import parse_file
from jobs.ventra_ingest.validators import validate_ar_buckets_sum


SAMPLE_ROOT = (
    Path(__file__).resolve().parents[2] / "samples" / "ventra" / "sample-drop-2026-06-15"
)
DROP_DATE = date(2026, 6, 15)


@pytest.fixture
def sample_manifest_bytes() -> bytes:
    return (SAMPLE_ROOT / "_MANIFEST.csv").read_bytes()


@pytest.fixture
def sample_manifest(sample_manifest_bytes: bytes) -> Manifest:
    return parse_manifest_bytes(sample_manifest_bytes, DROP_DATE)


def test_sample_manifest_parses(sample_manifest: Manifest) -> None:
    """V1 — _MANIFEST.csv has the required columns and parses cleanly."""
    assert sample_manifest.drop_date == DROP_DATE
    assert {e.file_name for e in sample_manifest.entries} == {
        "collections.csv",
        "ar_snapshot.csv",
        "physician_monthly.csv",
    }


def test_sample_manifest_only_lists_known_files(sample_manifest: Manifest) -> None:
    """V1 — every listed file name is in the known-files allowlist."""
    for entry in sample_manifest.entries:
        assert entry.file_name in KNOWN_FILE_NAMES


def test_sample_manifest_shas_match_actual_files(sample_manifest: Manifest) -> None:
    """V3 — SHA-256 of each blob's bytes matches the manifest digest."""
    for entry in sample_manifest.entries:
        data = (SAMPLE_ROOT / entry.file_name).read_bytes()
        actual_sha = hashlib.sha256(data).hexdigest()
        assert actual_sha == entry.sha256, (
            f"sha256 drift on {entry.file_name}: regenerate the sample with "
            f"`python scripts/generate_sample_ventra_drop.py {DROP_DATE} "
            f"{SAMPLE_ROOT.relative_to(SAMPLE_ROOT.parents[2])} --include-monthly`"
        )


def test_sample_manifest_row_counts_match_actual_files(sample_manifest: Manifest) -> None:
    """V4 — manifest row_count matches actual line count minus header."""
    for entry in sample_manifest.entries:
        data = (SAMPLE_ROOT / entry.file_name).read_bytes()
        actual_rows = max(0, len(data.splitlines()) - 1)
        assert actual_rows == entry.row_count, (
            f"row_count drift on {entry.file_name}: "
            f"manifest says {entry.row_count}, actual is {actual_rows}"
        )


@pytest.mark.parametrize(
    "file_name",
    ["collections.csv", "ar_snapshot.csv", "physician_monthly.csv"],
)
def test_sample_file_passes_parser(file_name: str) -> None:
    """V5-V11 — every row in every data file passes Pydantic + the
    model_validators (V7, V10, V11, V9 per-row)."""
    data = (SAMPLE_ROOT / file_name).read_bytes()
    rows = parse_file(file_name, data)
    assert len(rows) > 0


def test_sample_ar_snapshot_passes_cross_row_v9() -> None:
    """V9 cross-row — (snapshot_date, facility_no, aging_bucket) tuples
    must be unique within the sample drop."""
    data = (SAMPLE_ROOT / "ar_snapshot.csv").read_bytes()
    rows = parse_file("ar_snapshot.csv", data)
    validate_ar_buckets_sum(rows)


def test_sample_collections_has_expected_row_count() -> None:
    """Sanity: 5 facilities x 5 payer_classes = 25 rows. If the
    generator's FACILITIES or PAYER_CLASSES constants change, this
    test will catch the drift before users hit it in dev smoke tests."""
    data = (SAMPLE_ROOT / "collections.csv").read_bytes()
    rows = parse_file("collections.csv", data)
    assert len(rows) == 25


def test_sample_ar_snapshot_has_expected_row_count() -> None:
    """Sanity: 5 facilities x 6 aging_buckets = 30 rows."""
    data = (SAMPLE_ROOT / "ar_snapshot.csv").read_bytes()
    rows = parse_file("ar_snapshot.csv", data)
    assert len(rows) == 30


def test_sample_physician_monthly_has_expected_row_count() -> None:
    """Sanity: 10 NPIs x 5 facilities = 50 rows."""
    data = (SAMPLE_ROOT / "physician_monthly.csv").read_bytes()
    rows = parse_file("physician_monthly.csv", data)
    assert len(rows) == 50
