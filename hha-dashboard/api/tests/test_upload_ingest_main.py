"""Unit tests for ``jobs/upload_ingest/main.py`` core helpers.

Covers ``_claim_work`` (the FOR UPDATE SKIP LOCKED claim) + ``_process_one``
(per-row processing with retry/error flip). All Azure SDK + DB calls are
mocked; this file is pure Python.

The top-level ``main()`` orchestrator is NOT covered here — it wires
``configure_logging`` + audit listener + SessionLocal lifecycle and is
best exercised end-to-end against a real Postgres in a future Docker
session.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from jobs.upload_ingest.main import BATCH_SIZE, MAX_RETRIES, _claim_work, _process_one


def _upload_row(**overrides) -> MagicMock:
    """Build a stand-in for an UploadLog ORM row. Attributes are mutated
    in-place by the code under test, so MagicMock(spec=...) would over-
    constrain — use a plain MagicMock and override the relevant fields."""
    row = MagicMock()
    row.id = overrides.get("id", 1)
    row.uploaded_by_upn = overrides.get("uploaded_by_upn", "crystal@hha.com")
    row.original_filename = overrides.get("original_filename", "census.pdf")
    row.blob_name = overrides.get("blob_name", "uploads/1.pdf")
    row.sha256 = overrides.get("sha256", "a" * 64)
    row.file_type = overrides.get("file_type", "census_pdf")
    row.status = overrides.get("status", "uploaded")
    row.retry_count = overrides.get("retry_count", 0)
    row.rows_written = None
    row.error_message = None
    row.processing_started_at = None
    row.processing_finished_at = None
    return row


# ---------- _claim_work ----------


class TestClaimWork:
    async def test_returns_empty_list_when_no_work(self) -> None:
        db = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        rows = await _claim_work(db)
        assert rows == []
        # commit still fires (no-op when no rows were touched, but the
        # code commits unconditionally).
        db.commit.assert_awaited()

    async def test_flips_claimed_rows_to_processing(self) -> None:
        r1 = _upload_row(id=1, status="uploaded")
        r2 = _upload_row(id=2, status="uploaded")
        db = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [r1, r2]
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        rows = await _claim_work(db)

        assert len(rows) == 2
        assert r1.status == "processing"
        assert r2.status == "processing"
        assert r1.processing_started_at is not None
        assert r2.processing_started_at is not None
        # All rows get the same `now` from a single datetime.now() call.
        assert r1.processing_started_at == r2.processing_started_at

    async def test_constants_are_locked(self) -> None:
        # The cron's contract depends on these — if they change, the
        # operator runbook must change too.
        assert BATCH_SIZE == 50
        assert MAX_RETRIES == 3


# ---------- _process_one — happy path ----------


def _patch_blob_and_routes(monkeypatch, *, blob_bytes: bytes, extractor) -> dict:
    """Stub blob_service.download_bytes + set_metadata + ROUTES dispatch."""
    calls: dict = {"set_metadata": None}

    async def fake_download(_container: str, _blob_name: str) -> bytes:
        return blob_bytes

    async def fake_set_metadata(_container: str, _blob_name: str, meta: dict) -> None:
        calls["set_metadata"] = meta

    monkeypatch.setattr(
        "jobs.upload_ingest.main.blob_service.download_bytes",
        fake_download,
    )
    monkeypatch.setattr(
        "jobs.upload_ingest.main.blob_service.set_metadata",
        fake_set_metadata,
    )
    monkeypatch.setattr(
        "jobs.upload_ingest.main.ROUTES",
        {"census_pdf": extractor, "finance_xlsx": extractor},
    )
    return calls


class TestProcessOne:
    async def test_happy_path_flips_status_writes_metadata(self, monkeypatch) -> None:
        data = b"%PDF-stub"
        sha = hashlib.sha256(data).hexdigest()
        row = _upload_row(sha256=sha)

        async def extractor(_data, _row, _db):
            return SimpleNamespace(rows_written=3, warnings=[])

        calls = _patch_blob_and_routes(monkeypatch, blob_bytes=data, extractor=extractor)

        db = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        db.execute = AsyncMock()

        await _process_one(db, row)

        assert row.status == "processed"
        assert row.rows_written == 3
        assert row.error_message is None
        assert row.processing_finished_at is not None
        # Metadata write fires with the processed flag + rows_written.
        meta = calls["set_metadata"]
        assert meta["status"] == "processed"
        assert meta["rows_written"] == "3"
        assert meta["sha256"] == row.sha256
        # No rollback on happy path
        db.rollback.assert_not_awaited()

    async def test_warnings_join_into_error_message_field(self, monkeypatch) -> None:
        data = b"%PDF-stub"
        sha = hashlib.sha256(data).hexdigest()
        row = _upload_row(sha256=sha)

        async def extractor(_data, _row, _db):
            return SimpleNamespace(
                rows_written=2,
                warnings=["row 17 had no site match", "row 22 had no site match"],
            )

        _patch_blob_and_routes(monkeypatch, blob_bytes=data, extractor=extractor)

        db = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        await _process_one(db, row)

        # Warnings join with newlines into error_message even on success.
        assert row.error_message is not None
        assert "row 17" in row.error_message
        assert "row 22" in row.error_message
        # Still flipped to processed (warnings are non-fatal).
        assert row.status == "processed"


# ---------- _process_one — error / retry paths ----------


class TestProcessOneErrorPaths:
    async def test_sha_mismatch_increments_retry_and_keeps_status_uploaded(
        self, monkeypatch
    ) -> None:
        """SHA-256 mismatch on download triggers the retry path. With
        retry_count=0 -> 1, status stays 'uploaded' for re-processing."""
        # row.sha256 != hash of blob_bytes
        data = b"%PDF-stub"
        row = _upload_row(sha256="b" * 64, retry_count=0)

        # Refetch returns the same row (mock the .scalar_one() chain)
        db = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        refetch_result = MagicMock()
        refetch_result.scalar_one.return_value = row
        db.execute = AsyncMock(return_value=refetch_result)

        async def fake_download(_c, _b):
            return data

        monkeypatch.setattr(
            "jobs.upload_ingest.main.blob_service.download_bytes", fake_download
        )

        await _process_one(db, row)

        db.rollback.assert_awaited()
        assert row.retry_count == 1
        # 1 < MAX_RETRIES(3) → re-queue as 'uploaded'
        assert row.status == "uploaded"
        assert row.error_message is not None
        assert "SHA-256 mismatch" in row.error_message

    async def test_third_failure_marks_status_error_terminal(self, monkeypatch) -> None:
        """retry_count goes 2 -> 3; status flips to terminal 'error'."""
        row = _upload_row(sha256="b" * 64, retry_count=2)

        db = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        refetch_result = MagicMock()
        refetch_result.scalar_one.return_value = row
        db.execute = AsyncMock(return_value=refetch_result)

        async def fake_download(_c, _b):
            return b"%PDF-stub"

        monkeypatch.setattr(
            "jobs.upload_ingest.main.blob_service.download_bytes", fake_download
        )

        await _process_one(db, row)

        assert row.retry_count == 3
        assert row.status == "error"

    async def test_unknown_file_type_triggers_error_branch(self, monkeypatch) -> None:
        data = b"%PDF-stub"
        sha = hashlib.sha256(data).hexdigest()
        row = _upload_row(sha256=sha, file_type="not_a_known_type", retry_count=0)

        async def fake_download(_c, _b):
            return data

        monkeypatch.setattr(
            "jobs.upload_ingest.main.blob_service.download_bytes", fake_download
        )
        monkeypatch.setattr("jobs.upload_ingest.main.ROUTES", {"census_pdf": object()})

        db = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        refetch = MagicMock()
        refetch.scalar_one.return_value = row
        db.execute = AsyncMock(return_value=refetch)

        await _process_one(db, row)

        assert "Unknown file_type" in row.error_message
        assert row.retry_count == 1

    async def test_extractor_exception_triggers_rollback(self, monkeypatch) -> None:
        """When the extractor raises, db.rollback fires before the retry
        bookkeeping commits."""
        data = b"%PDF-stub"
        sha = hashlib.sha256(data).hexdigest()
        row = _upload_row(sha256=sha)

        async def boom(_data, _row, _db):
            raise RuntimeError("extractor blew up")

        _patch_blob_and_routes(monkeypatch, blob_bytes=data, extractor=boom)

        db = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        refetch = MagicMock()
        refetch.scalar_one.return_value = row
        db.execute = AsyncMock(return_value=refetch)

        await _process_one(db, row)

        db.rollback.assert_awaited()
        assert "RuntimeError" in row.error_message
        assert "extractor blew up" in row.error_message
        assert row.retry_count == 1

    async def test_error_message_truncates_at_500_chars(self, monkeypatch) -> None:
        """The error_message column is VARCHAR(500); the slice [:500] in
        the code is the cap. Pin that contract."""
        data = b"%PDF-stub"
        sha = hashlib.sha256(data).hexdigest()
        row = _upload_row(sha256=sha)

        big = "x" * 2000

        async def boom(_data, _row, _db):
            raise ValueError(big)

        _patch_blob_and_routes(monkeypatch, blob_bytes=data, extractor=boom)

        db = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        refetch = MagicMock()
        refetch.scalar_one.return_value = row
        db.execute = AsyncMock(return_value=refetch)

        await _process_one(db, row)

        assert row.error_message is not None
        assert len(row.error_message) <= 500
