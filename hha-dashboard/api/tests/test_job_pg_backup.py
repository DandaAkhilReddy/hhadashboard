"""pg_backup tests.

The unit tests mock subprocess (no real pg_dump invocation) and the blob
upload (no Azurite needed). The integration test requires:
  - docker postgres running (covered by docker-compose `db`)
  - pg_dump on PATH
  - Azurite or real Blob target

We skip the integration test if pg_dump isn't on PATH, so CI without
postgresql-client still passes the unit tests.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from jobs.pg_backup.backup import (
    BackupError,
    _filename,
    _hash_url,
    _run_pg_dump,
    _to_libpq_url,
    run_backup,
)


def test_to_libpq_url_strips_sqlalchemy_psycopg_suffix() -> None:
    """pg_dump's libpq doesn't understand 'postgresql+psycopg://...'.
    Without stripping, libpq falls back to a Unix socket and fails."""
    assert (
        _to_libpq_url("postgresql+psycopg://user:pw@host:5432/db")
        == "postgresql://user:pw@host:5432/db"
    )


def test_to_libpq_url_strips_asyncpg_suffix() -> None:
    assert (
        _to_libpq_url("postgresql+asyncpg://user:pw@host/db")
        == "postgresql://user:pw@host/db"
    )


def test_to_libpq_url_passes_plain_url_through() -> None:
    plain = "postgresql://user:pw@host/db"
    assert _to_libpq_url(plain) == plain


def test_filename_is_sortable_iso8601() -> None:
    name = _filename("dev", datetime(2026, 4, 26, 3, 0, 0, tzinfo=UTC))
    assert name == "pg-backup-dev-2026-04-26T03-00-00Z.dump"


def test_filename_includes_env_in_path() -> None:
    name = _filename("prod", datetime(2026, 4, 26, 3, 0, 0, tzinfo=UTC))
    assert name.startswith("pg-backup-prod-")


def test_hash_url_is_deterministic_and_truncated() -> None:
    h1 = _hash_url("postgresql+psycopg://user:pw@host/db")
    h2 = _hash_url("postgresql+psycopg://user:pw@host/db")
    assert h1 == h2
    assert len(h1) == 16  # truncated to 16 chars
    # Different URLs → different hashes
    h3 = _hash_url("postgresql+psycopg://other:pw@host/db")
    assert h1 != h3


def test_hash_url_does_not_leak_password() -> None:
    """The hash output must not contain the password substring."""
    h = _hash_url("postgresql+psycopg://user:supersecret123@host/db")
    assert "supersecret123" not in h
    assert "user" not in h


def test_run_pg_dump_raises_on_missing_binary(tmp_path: Path) -> None:
    """If pg_dump isn't on PATH, BackupError is raised with a helpful message."""
    with patch("subprocess.run", side_effect=FileNotFoundError), pytest.raises(
        BackupError, match="pg_dump not on PATH"
    ):
        _run_pg_dump("postgresql://localhost/x", tmp_path / "out.dump")


def test_run_pg_dump_raises_on_nonzero_exit(tmp_path: Path) -> None:
    fake_completed = subprocess.CompletedProcess(
        args=["pg_dump"], returncode=2, stdout="", stderr="connection refused"
    )
    with patch("subprocess.run", return_value=fake_completed), pytest.raises(
        BackupError, match="exited 2"
    ):
        _run_pg_dump("postgresql://localhost/x", tmp_path / "out.dump")


def test_run_pg_dump_raises_on_empty_output(tmp_path: Path) -> None:
    """pg_dump returned 0 but the output file is empty — that's a bug, not a success."""
    out_path = tmp_path / "out.dump"
    fake_completed = subprocess.CompletedProcess(
        args=["pg_dump"], returncode=0, stdout="", stderr=""
    )
    with patch("subprocess.run", return_value=fake_completed), pytest.raises(
        BackupError, match="empty or missing"
    ):
        _run_pg_dump("postgresql://localhost/x", out_path)


def test_run_pg_dump_raises_on_timeout(tmp_path: Path) -> None:
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="pg_dump", timeout=1800),
    ), pytest.raises(BackupError, match="timed out"):
        _run_pg_dump("postgresql://localhost/x", tmp_path / "out.dump")


@pytest.mark.asyncio
async def test_run_backup_invokes_pg_dump_then_uploads() -> None:
    """End-to-end orchestration: pg_dump, then upload, then return metadata."""

    # Mock the pg_dump invocation to write a fake dump file in the temp dir.
    def fake_dump(_database_url: str, output_path: Path) -> None:  # noqa: ARG001
        output_path.write_bytes(b"PGDMP\x00\x00fake binary dump bytes")

    fake_upload = AsyncMock(return_value="https://test.blob.core/backups/x.dump")

    with (
        patch("jobs.pg_backup.backup._run_pg_dump", side_effect=fake_dump),
        patch("jobs.pg_backup.backup.upload_bytes", fake_upload),
    ):
        result = await run_backup(
            env_name="dev",
            database_url="postgresql+psycopg://user:pw@host:5432/hha_dashboard",
        )

    assert "blob_name" in result
    assert result["blob_name"].startswith("pg-backup-dev-")
    assert result["blob_name"].endswith(".dump")
    assert result["env_name"] == "dev"
    assert int(result["dump_size_bytes"]) > 0
    assert "postgres_url_hash" in result
    assert len(result["postgres_url_hash"]) == 16

    fake_upload.assert_called_once()
    call_kwargs = fake_upload.call_args.kwargs
    assert call_kwargs["container_name"] == "backups"
    assert call_kwargs["overwrite"] is False  # never overwrite a backup
    assert call_kwargs["content_type"] == "application/octet-stream"
    # Metadata includes traceability fields.
    assert call_kwargs["metadata"]["env_name"] == "dev"
    assert "dump_started_at" in call_kwargs["metadata"]


@pytest.mark.asyncio
async def test_run_backup_propagates_pg_dump_failure() -> None:
    """If pg_dump fails, run_backup raises BackupError and never uploads."""

    def fake_dump(_database_url: str, _output_path: Path) -> None:  # noqa: ARG001
        msg = "connection refused"
        raise BackupError(msg)

    fake_upload = AsyncMock()
    with (
        patch("jobs.pg_backup.backup._run_pg_dump", side_effect=fake_dump),
        patch("jobs.pg_backup.backup.upload_bytes", fake_upload),
        pytest.raises(BackupError, match="connection refused"),
    ):
        await run_backup(env_name="dev", database_url="postgresql://x/y")

    fake_upload.assert_not_awaited()


# ---------------------------------------------------------------------------
# Integration: actual pg_dump against the dev compose Postgres
# ---------------------------------------------------------------------------


def _has_pg_dump() -> bool:
    return shutil.which("pg_dump") is not None


@pytest.mark.skipif(not _has_pg_dump(), reason="pg_dump not on PATH")
@pytest.mark.asyncio
async def test_real_pg_dump_against_local_postgres(tmp_path: Path) -> None:
    """Smoke test: invoke pg_dump for real against the local docker compose
    postgres. Skips silently in CI environments without postgresql-client."""
    from sqlalchemy import text

    from app.deps import SessionLocal

    # Skip if Postgres unreachable (mirrors other DB-backed tests).
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("Postgres not reachable")

    from app.settings import settings

    out_path = tmp_path / "real_dump.dump"
    _run_pg_dump(settings.database_url_sync, out_path)

    assert out_path.exists()
    assert out_path.stat().st_size > 0
    # The custom format starts with the magic bytes "PGDMP".
    assert out_path.read_bytes()[:5] == b"PGDMP"
