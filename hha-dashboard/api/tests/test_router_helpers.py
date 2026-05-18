"""Unit tests for the synchronous private helpers exported by the
FastAPI routers. These functions are exercised indirectly when the
router endpoints run, but the endpoints themselves require Postgres.
Pinning each helper at unit speed catches regressions before integration.

Helpers covered:
- ``app.routers.entries._source_for_state``  — FL/TX → SourceSystem map
- ``app.routers.entries._last_sunday``  — last-Sunday-on-or-before
- ``app.routers.finance._buckets_to_schema`` — dict → ArBuckets adapter
- ``app.routers.uploads._allowed_extension`` — whitelist + lowercasing
- ``app.routers.uploads._make_blob_name`` — blob-path template
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

import pytest

from app.routers.entries import _last_sunday, _source_for_state
from app.routers.finance import _buckets_to_schema
from app.routers.uploads import _allowed_extension, _make_blob_name
from app.schemas.finance import ArBuckets
from app.schemas.monthly_finance import SourceSystem, StateCode

# ============================================================================
# entries._source_for_state — FL/TX provenance map (ADR-005 invariant)
# ============================================================================


class TestSourceForState:
    def test_fl_maps_to_ventra_fl_fallback(self) -> None:
        # FL rows always tag as the Ventra-fallback provenance until SFTP
        # automation lands (then they flip to VENTRA_FL_ATHENA via the ingest
        # job, never via this owner-form path).
        assert _source_for_state(StateCode.FL) == SourceSystem.VENTRA_FL_FALLBACK

    def test_tx_maps_to_hha_tx_manual(self) -> None:
        # TX is manual-only per ADR-005 — never Ventra.
        assert _source_for_state(StateCode.TX) == SourceSystem.HHA_TX_MANUAL

    def test_no_state_maps_to_ventra_fl_athena_via_helper(self) -> None:
        # The auto-ingested ``VENTRA_FL_ATHENA`` provenance is reserved for
        # the cron path, never the manual form — assert the helper never
        # produces it.
        assert SourceSystem.VENTRA_FL_ATHENA not in {
            _source_for_state(StateCode.FL),
            _source_for_state(StateCode.TX),
        }


# ============================================================================
# entries._last_sunday — date arithmetic
# ============================================================================


class TestLastSunday:
    @pytest.mark.parametrize(
        ("today", "expected"),
        [
            # 2026-05-17 is a Sunday → returns itself
            (date(2026, 5, 17), date(2026, 5, 17)),
            # Mon 2026-05-18 → previous Sunday (2026-05-17)
            (date(2026, 5, 18), date(2026, 5, 17)),
            # Tue 2026-05-19 → 2026-05-17
            (date(2026, 5, 19), date(2026, 5, 17)),
            # Wed 2026-05-20 → 2026-05-17
            (date(2026, 5, 20), date(2026, 5, 17)),
            # Sat 2026-05-23 → 2026-05-17
            (date(2026, 5, 23), date(2026, 5, 17)),
            # Following Sunday returns itself
            (date(2026, 5, 24), date(2026, 5, 24)),
        ],
    )
    def test_walks_back_to_most_recent_sunday(
        self, today: date, expected: date
    ) -> None:
        out = _last_sunday(today)
        assert out == expected
        # Sanity: result is always a Sunday (weekday() == 6)
        assert out.weekday() == 6

    def test_handles_month_boundary(self) -> None:
        # 2026-06-01 is a Monday → previous Sunday is in May
        assert _last_sunday(date(2026, 6, 1)) == date(2026, 5, 31)

    def test_handles_year_boundary(self) -> None:
        # 2026-01-01 is a Thursday → previous Sunday is in December 2025
        assert _last_sunday(date(2026, 1, 1)) == date(2025, 12, 28)


# ============================================================================
# finance._buckets_to_schema — dict → ArBuckets
# ============================================================================


class TestBucketsToSchema:
    def test_full_bucket_dict_maps_to_schema(self) -> None:
        out = _buckets_to_schema(
            {
                "0-30": 30_000,
                "31-60": 10_000,
                "61-90": 5_000,
                "91-120": 3_000,
                ">120": 2_000,
            }
        )
        assert isinstance(out, ArBuckets)
        assert out.bucket_0_30 == 30_000
        assert out.bucket_31_60 == 10_000
        assert out.bucket_61_90 == 5_000
        assert out.bucket_91_120 == 3_000
        assert out.bucket_over_120 == 2_000

    def test_missing_required_key_raises(self) -> None:
        # The function reaches for buckets[">120"] with no .get() default;
        # KeyError is the documented failure mode.
        with pytest.raises(KeyError):
            _buckets_to_schema(
                {
                    "0-30": 0,
                    "31-60": 0,
                    "61-90": 0,
                    "91-120": 0,
                }
            )

    def test_accepts_zero_buckets(self) -> None:
        out = _buckets_to_schema(
            {
                "0-30": 0,
                "31-60": 0,
                "61-90": 0,
                "91-120": 0,
                ">120": 0,
            }
        )
        assert out.bucket_0_30 == 0


# ============================================================================
# uploads._allowed_extension — file-type whitelist
# ============================================================================


class TestAllowedExtension:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("census.pdf", "pdf"),
            ("finance.xlsx", "xlsx"),
            ("legacy.xls", "xls"),
            ("export.csv", "csv"),
            # Mixed case → lowercased
            ("Census.PDF", "pdf"),
            ("REPORT.XLSX", "xlsx"),
        ],
    )
    def test_recognized_extensions(self, filename: str, expected: str) -> None:
        assert _allowed_extension(filename) == expected

    @pytest.mark.parametrize(
        "filename",
        ["bad.exe", "script.js", "image.png", "archive.zip", "no_extension"],
    )
    def test_unrecognized_extensions_return_none(self, filename: str) -> None:
        assert _allowed_extension(filename) is None

    def test_double_extension_uses_final_one(self) -> None:
        # Path(...).suffix returns ".gz" from "foo.csv.gz" — gz is not in
        # the allowlist, so this rejects.
        assert _allowed_extension("foo.csv.gz") is None

    def test_double_extension_with_allowed_final_is_accepted(self) -> None:
        # A file named "foo.tar.csv" has suffix ".csv" → allowed.
        assert _allowed_extension("foo.tar.csv") == "csv"


# ============================================================================
# uploads._make_blob_name — blob-path template
# ============================================================================


class _FixedDatetime(datetime):
    """A datetime subclass whose ``now()`` returns a fixed instant so the
    blob-name's date component is deterministic in tests."""

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return cls(2026, 5, 17, 15, 30, tzinfo=tz)


class TestMakeBlobName:
    def test_format_matches_documented_template(self) -> None:
        with patch("app.routers.uploads.datetime", _FixedDatetime):
            name = _make_blob_name(
                upn="crystal@hhamedicine.com",
                file_type="census_pdf",
                original_filename="Census.pdf",
                sha256_hex="a" * 64,
            )
        # Template: {type}/{YYYY-MM-DD}/{upn_safe}_{uuid8}_{sha8}.{ext}
        parts = name.split("/")
        assert parts[0] == "census_pdf"
        assert parts[1] == "2026-05-17"
        filename = parts[2]
        # UPN '@' and '.' get sanitized
        assert "crystal_at_hhamedicine_com" in filename
        # ext came from _allowed_extension('Census.pdf') = 'pdf'
        assert filename.endswith(".pdf")
        # short sha (first 8 chars of the hex) appears in the filename
        assert "aaaaaaaa" in filename

    def test_unknown_extension_falls_back_to_bin(self) -> None:
        with patch("app.routers.uploads.datetime", _FixedDatetime):
            name = _make_blob_name(
                upn="x@y.com",
                file_type="unknown",
                original_filename="weird.zzz",
                sha256_hex="b" * 64,
            )
        assert name.endswith(".bin")

    def test_uuid_segments_differ_across_calls(self) -> None:
        """Two invocations with identical inputs still produce different
        blob names — the uuid4() guarantees uniqueness so concurrent
        uploads of the same file from the same user don't collide on
        the blob path."""
        with patch("app.routers.uploads.datetime", _FixedDatetime):
            a = _make_blob_name("x@y.com", "census_pdf", "f.pdf", "c" * 64)
            b = _make_blob_name("x@y.com", "census_pdf", "f.pdf", "c" * 64)
        assert a != b

    def test_sha_short_uses_first_8_hex_chars(self) -> None:
        with patch("app.routers.uploads.datetime", _FixedDatetime):
            name = _make_blob_name(
                upn="x@y.com",
                file_type="census_pdf",
                original_filename="f.pdf",
                sha256_hex="0123456789abcdef" + "0" * 48,
            )
        # The 8-char sha prefix is "01234567" (first 8 hex chars)
        assert "01234567" in name

    def test_blob_prefix_is_file_type_for_lifecycle_targeting(self) -> None:
        """The first path segment IS the file_type — Azure lifecycle
        policies target by prefix, so this is a contract."""
        with patch("app.routers.uploads.datetime", _FixedDatetime):
            for ftype in ("census_pdf", "finance_xlsx", "clinical_xlsx", "hr_xlsx"):
                name = _make_blob_name(
                    upn="x@y.com",
                    file_type=ftype,
                    original_filename="f.pdf",
                    sha256_hex="d" * 64,
                )
                assert name.startswith(f"{ftype}/")
