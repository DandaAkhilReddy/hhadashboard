"""Quarantine flow tests for the Ventra ingest pipeline.

Pure unit tests — no real blob storage. Monkeypatch the 3 blob module
functions consumed by quarantine.py (list_by_prefix, copy_blob,
upload_bytes); verify call counts, arguments, and the sidecar contents.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest
from jobs.ventra_ingest.exceptions import ADRViolation, ValidationError
from jobs.ventra_ingest.quarantine import (
    REJECT_REASON_FILE,
    VENDOR_INBOUND,
    VENDOR_QUARANTINE,
    _build_sidecar,
    quarantine_drop,
)

pytestmark = pytest.mark.asyncio


DROP = date(2026, 5, 15)
RUN_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
CORR_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


class _BlobSpy:
    """Captures every monkeypatched blob.* call. Lives outside the test
    function so the inner async helpers can close over a stable instance."""

    def __init__(self) -> None:
        self.listed_prefixes: list[tuple[str, str]] = []
        self.copies: list[dict[str, str]] = []
        self.uploads: list[dict[str, Any]] = []
        self.deletes: list[tuple[str, str]] = []
        self.list_returns: list[dict[str, Any]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_list(container_name: str, prefix: str, *, include_metadata: bool = True) -> list[dict[str, Any]]:  # noqa: ARG001
            self.listed_prefixes.append((container_name, prefix))
            return self.list_returns

        async def fake_copy(
            source_container: str,
            source_blob: str,
            dest_container: str,
            dest_blob: str,
        ) -> None:
            self.copies.append(
                {
                    "source_container": source_container,
                    "source_blob": source_blob,
                    "dest_container": dest_container,
                    "dest_blob": dest_blob,
                }
            )

        async def fake_upload(
            container_name: str,
            blob_name: str,
            data: bytes,
            *,
            content_type: str,
            metadata: dict[str, str] | None = None,
            overwrite: bool = False,
        ) -> str:
            self.uploads.append(
                {
                    "container_name": container_name,
                    "blob_name": blob_name,
                    "data": data,
                    "content_type": content_type,
                    "metadata": metadata,
                    "overwrite": overwrite,
                }
            )
            return f"https://stub/{container_name}/{blob_name}"

        async def fake_delete(container_name: str, blob_name: str) -> None:
            self.deletes.append((container_name, blob_name))

        monkeypatch.setattr("jobs.ventra_ingest.quarantine.blob.list_by_prefix", fake_list)
        monkeypatch.setattr("jobs.ventra_ingest.quarantine.blob.copy_blob", fake_copy)
        monkeypatch.setattr("jobs.ventra_ingest.quarantine.blob.upload_bytes", fake_upload)
        monkeypatch.setattr("jobs.ventra_ingest.quarantine.blob.delete_blob", fake_delete)


def _listed(name: str) -> dict[str, Any]:
    """Helper to build a list_by_prefix result entry."""
    return {"name": name, "size": 100, "last_modified": None, "metadata": {}}


# =========================================================================
# happy path — copies every inbound file + one sidecar
# =========================================================================


async def test_quarantine_copies_every_inbound_file(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _BlobSpy()
    spy.list_returns = [
        _listed("ventra/2026-05-15/collections.csv"),
        _listed("ventra/2026-05-15/ar_snapshot.csv"),
        _listed("ventra/2026-05-15/_MANIFEST.csv"),
    ]
    spy.install(monkeypatch)

    reason = ValidationError(
        rule="V9",
        message="ar_snapshot.csv duplicates (snapshot_date=2026-05-15, facility=901, bucket='0-30')",
        details={"file_name": "ar_snapshot.csv", "line_no": 5},
    )
    await quarantine_drop(DROP, reason, RUN_ID, CORR_ID)

    # Listed the right prefix
    assert spy.listed_prefixes == [(VENDOR_INBOUND, "ventra/2026-05-15/")]

    # 3 file copies — each source -> matching dest in vendor-quarantine
    assert len(spy.copies) == 3
    for c in spy.copies:
        assert c["source_container"] == VENDOR_INBOUND
        assert c["dest_container"] == VENDOR_QUARANTINE
        assert c["source_blob"] == c["dest_blob"]   # path mirrored
        assert c["source_blob"].startswith("ventra/2026-05-15/")

    # Exactly one sidecar upload
    assert len(spy.uploads) == 1


# =========================================================================
# sidecar contents
# =========================================================================


async def test_quarantine_sidecar_contains_required_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _BlobSpy()
    spy.list_returns = [_listed("ventra/2026-05-15/collections.csv")]
    spy.install(monkeypatch)

    reason = ValidationError(
        rule="V5",
        message="collections.csv line 3 failed V5",
        details={
            "file_name": "collections.csv",
            "line_no": 3,
            "row": {"date": "2026-05-15", "facility_no": "901"},
        },
    )
    await quarantine_drop(DROP, reason, RUN_ID, CORR_ID)

    upload = spy.uploads[0]
    assert upload["container_name"] == VENDOR_QUARANTINE
    assert upload["blob_name"] == f"ventra/2026-05-15/{REJECT_REASON_FILE}"
    assert upload["content_type"].startswith("text/plain")
    assert upload["overwrite"] is True

    body = upload["data"].decode("utf-8")
    assert f"RUN_ID:         {RUN_ID}" in body
    assert f"CORRELATION_ID: {CORR_ID}" in body
    assert "DROP_DATE:      2026-05-15" in body
    assert "RULE:    V5" in body
    assert "MESSAGE: collections.csv line 3 failed V5" in body
    assert "DETAILS:" in body
    assert "file_name: collections.csv" in body
    assert "line_no: 3" in body
    assert "Original drop folder:   vendor-inbound/ventra/2026-05-15/" in body
    assert "This quarantine folder: vendor-quarantine/ventra/2026-05-15/" in body
    assert "Operator runbook:       docs/04-operations/RUNBOOK.md#ventra-quarantine" in body
    assert "DO NOT delete files from this folder" in body

    # Blob metadata for KQL filtering
    assert upload["metadata"]["run_id"] == str(RUN_ID)
    assert upload["metadata"]["rule"] == "V5"
    assert upload["metadata"]["adr_005_incident"] == "false"


async def test_quarantine_sidecar_marks_adr_violation_for_v12(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _BlobSpy()
    spy.list_returns = [_listed("ventra/2026-05-15/collections.csv")]
    spy.install(monkeypatch)

    reason = ADRViolation(
        message="non-FL facility in Ventra drop: collections.csv line 3 facility_no=801 hha_state=TX",
        details={"facility_no": 801, "hha_state": "TX", "file_name": "collections.csv"},
    )
    await quarantine_drop(DROP, reason, RUN_ID, CORR_ID)

    body = spy.uploads[0]["data"].decode("utf-8")
    assert "RULE:    V12" in body
    assert "ADR-005 incident?       YES (V12 — non-FL facility in Ventra drop)" in body
    assert spy.uploads[0]["metadata"]["adr_005_incident"] == "true"
    assert spy.uploads[0]["metadata"]["rule"] == "V12"


async def test_quarantine_sidecar_handles_empty_details(monkeypatch: pytest.MonkeyPatch) -> None:
    """Some failures (e.g. blanket V1 'manifest empty') carry no details."""
    spy = _BlobSpy()
    spy.list_returns = [_listed("ventra/2026-05-15/_MANIFEST.csv")]
    spy.install(monkeypatch)

    reason = ValidationError(rule="V1", message="manifest is empty (no header row)")
    await quarantine_drop(DROP, reason, RUN_ID, CORR_ID)
    body = spy.uploads[0]["data"].decode("utf-8")
    assert "DETAILS:" in body
    assert "(none)" in body


# =========================================================================
# idempotency + side-effect guarantees
# =========================================================================


async def test_quarantine_idempotent_re_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling quarantine_drop twice for the same drop should not error.
    Server-side copy is idempotent (dest overwrites); upload_bytes is
    called with overwrite=True."""
    spy = _BlobSpy()
    spy.list_returns = [_listed("ventra/2026-05-15/collections.csv")]
    spy.install(monkeypatch)

    reason = ValidationError(rule="V5", message="bad column", details={})
    await quarantine_drop(DROP, reason, RUN_ID, CORR_ID)
    await quarantine_drop(DROP, reason, RUN_ID, CORR_ID)

    assert len(spy.copies) == 2     # one per call
    assert len(spy.uploads) == 2    # sidecar re-written each time
    assert all(u["overwrite"] is True for u in spy.uploads)


async def test_quarantine_does_not_delete_inbound(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inbound files must persist for operator triage / replay; 90-day
    lifecycle policy reaps them eventually."""
    spy = _BlobSpy()
    spy.list_returns = [_listed("ventra/2026-05-15/collections.csv")]
    spy.install(monkeypatch)

    reason = ValidationError(rule="V5", message="bad", details={})
    await quarantine_drop(DROP, reason, RUN_ID, CORR_ID)
    assert spy.deletes == []


async def test_quarantine_no_files_listed_still_writes_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    """Edge case: vendor-inbound listing returns empty (e.g. file already
    auto-deleted between drop and quarantine). The sidecar still goes
    down so the operator can see the rejection record."""
    spy = _BlobSpy()
    spy.list_returns = []
    spy.install(monkeypatch)

    reason = ValidationError(rule="V5", message="late race", details={})
    await quarantine_drop(DROP, reason, RUN_ID, CORR_ID)

    assert spy.copies == []
    assert len(spy.uploads) == 1
    assert "_REJECT_REASON.txt" in spy.uploads[0]["blob_name"]


# =========================================================================
# _build_sidecar (direct unit, no monkeypatch)
# =========================================================================


def test_build_sidecar_returns_utf8_bytes() -> None:
    reason = ValidationError(rule="V13", message="dedup conflict", details={"drop_date": "2026-05-15"})
    out = _build_sidecar(DROP, reason, RUN_ID, CORR_ID)
    assert isinstance(out, bytes)
    text = out.decode("utf-8")
    assert "RULE:    V13" in text
    assert text.endswith("\n")  # trailing newline for shell-friendly display


def test_build_sidecar_includes_iso_timestamp() -> None:
    """Sanity — the timestamp should be present and parseable."""
    reason = ValidationError(rule="V5", message="x", details={})
    text = _build_sidecar(DROP, reason, RUN_ID, CORR_ID).decode("utf-8")
    # Find the TIMESTAMP line; format is "TIMESTAMP:      <iso>"
    ts_line = next(line for line in text.splitlines() if line.startswith("TIMESTAMP:"))
    iso = ts_line.split(maxsplit=1)[1].strip()
    # Parseable as ISO 8601 (datetime.fromisoformat round-trip)
    from datetime import datetime
    parsed = datetime.fromisoformat(iso)
    assert parsed is not None
