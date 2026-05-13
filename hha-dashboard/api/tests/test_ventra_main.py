"""Orchestrator unit tests for jobs.ventra_ingest.main.

Heavy mocking — no DB, no queue, no blob, no ACS. The goal is to verify
the orchestration sequence per Phase 1A.A4-A5 of the plan:

  - Event Grid payload parsing → (drop_date, manifest_path)
  - Phase 1-4 validator sequence on the happy path
  - V13 dedup_skip short-circuit
  - V12 ADRViolation routes to the incident path (notify_incident +
    ventra.adr005_violation event)
  - V1-V11 / V13 ValidationError routes to the quarantine path
  - Unhandled Exception re-raises (no delete) for KEDA retry
  - Bad Event Grid payload: log + delete (poison message)
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.asyncio


# =========================================================================
# _parse_event_grid_payload
# =========================================================================


def _eg_event(subject: str) -> dict[str, Any]:
    return {
        "id": "evt-1",
        "subject": subject,
        "data": {"api": "PutBlob"},
        "eventType": "Microsoft.Storage.BlobCreated",
    }


def test_parse_event_grid_payload_plain_json() -> None:
    from jobs.ventra_ingest.main import _parse_event_grid_payload

    subj = "/blobServices/default/containers/vendor-inbound/blobs/ventra/2026-05-15/_MANIFEST.csv"
    drop_date, blob_path = _parse_event_grid_payload(json.dumps(_eg_event(subj)))
    assert drop_date == date(2026, 5, 15)
    assert blob_path == "ventra/2026-05-15/_MANIFEST.csv"


def test_parse_event_grid_payload_base64() -> None:
    from jobs.ventra_ingest.main import _parse_event_grid_payload

    subj = "/blobServices/default/containers/vendor-inbound/blobs/ventra/2026-05-15/_MANIFEST.csv"
    body = json.dumps(_eg_event(subj)).encode("utf-8")
    encoded = base64.b64encode(body).decode("ascii")
    drop_date, blob_path = _parse_event_grid_payload(encoded)
    assert drop_date == date(2026, 5, 15)
    assert blob_path == "ventra/2026-05-15/_MANIFEST.csv"


def test_parse_event_grid_payload_rejects_missing_subject() -> None:
    from jobs.ventra_ingest.main import _parse_event_grid_payload

    with pytest.raises(ValueError, match="missing subject"):
        _parse_event_grid_payload(json.dumps({"eventType": "X"}))


def test_parse_event_grid_payload_rejects_unexpected_subject() -> None:
    from jobs.ventra_ingest.main import _parse_event_grid_payload

    with pytest.raises(ValueError, match="unexpected subject"):
        _parse_event_grid_payload(json.dumps(_eg_event("/somewhere/else")))


def test_parse_event_grid_payload_rejects_non_ventra_prefix() -> None:
    from jobs.ventra_ingest.main import _parse_event_grid_payload

    subj = "/blobServices/default/containers/vendor-inbound/blobs/quest/2026-05-15/_MANIFEST.csv"
    with pytest.raises(ValueError, match="unexpected blob path"):
        _parse_event_grid_payload(json.dumps(_eg_event(subj)))


# =========================================================================
# process_one_message — orchestration scenarios
# =========================================================================


class _OrchestratorHarness:
    """Bundles every module monkeypatch needed to exercise process_one_message
    without touching DB / blob / network. Each attribute starts as None and
    a per-test factory sets the desired behavior before calling install()."""

    def __init__(self) -> None:
        # Sentinels — tests override before install()
        self.load_manifest_result: tuple | Exception | None = None
        self.parse_file_result: dict[str, list] = {}
        self.fl_only_side_effect: Exception | None = None
        self.dedup_decision: Any = None
        self.ingest_drop_result: Any = None
        self.ingest_drop_side_effect: Exception | None = None

        # Recorders
        self.run_start_calls: list[dict[str, Any]] = []
        self.run_complete_calls: list[dict[str, Any]] = []
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.quarantine_calls: list[dict[str, Any]] = []
        self.notify_calls: list[tuple[str, dict[str, Any]]] = []
        self.upn_set: list[str] = []
        self.session_used: bool = False
        self.allocated_run_id = uuid.UUID("11111111-1111-1111-1111-111111111111")

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from jobs.ventra_ingest import main as main_mod

        # --- session ---
        class _SessCtx:
            harness = self
            async def __aenter__(self_inner) -> Any:  # noqa: N805 — closure on outer harness
                self.session_used = True
                return MagicMock(name="session")
            async def __aexit__(self_inner, *a: Any) -> None:  # noqa: N805
                return None
        monkeypatch.setattr(main_mod, "SessionLocal", lambda: _SessCtx())

        # --- audit upn ---
        def fake_set_upn(upn: str) -> None:
            self.upn_set.append(upn)
        monkeypatch.setattr(main_mod, "set_current_upn", fake_set_upn)

        # --- IngestRun.start / complete ---
        harness = self
        class _FakeRun:
            run_id = harness.allocated_run_id
            @classmethod
            async def start(cls, db: Any, *, drop_date: date, manifest_path: str, correlation_id: uuid.UUID) -> _FakeRun:  # noqa: ARG003
                harness.run_start_calls.append({
                    "drop_date": drop_date,
                    "manifest_path": manifest_path,
                    "correlation_id": correlation_id,
                })
                return cls()
            async def complete(self_inner, db: Any, **kwargs: Any) -> None:  # noqa: ARG002, N805
                harness.run_complete_calls.append(kwargs)
        monkeypatch.setattr(main_mod, "IngestRun", _FakeRun)

        # --- load_manifest ---
        async def fake_load(drop_date: date, manifest_path: str) -> tuple:  # noqa: ARG001
            if isinstance(self.load_manifest_result, Exception):
                raise self.load_manifest_result
            return self.load_manifest_result
        monkeypatch.setattr(main_mod, "load_manifest", fake_load)

        # --- parse_file ---
        def fake_parse(file_name: str, data: bytes) -> list:  # noqa: ARG001
            return self.parse_file_result.get(file_name, [])
        monkeypatch.setattr(main_mod, "parse_file", fake_parse)

        # --- validators ---
        def fake_drop_consistency(parsed: dict, drop_date: date) -> None:  # noqa: ARG001
            return None
        monkeypatch.setattr(main_mod, "validate_drop_consistency", fake_drop_consistency)

        def fake_ar_sum(rows: Any) -> None:  # noqa: ARG001
            return None
        monkeypatch.setattr(main_mod, "validate_ar_buckets_sum", fake_ar_sum)

        async def fake_fl_only(db: Any, parsed: dict) -> None:  # noqa: ARG001
            if self.fl_only_side_effect is not None:
                raise self.fl_only_side_effect
        monkeypatch.setattr(main_mod, "validate_fl_only", fake_fl_only)

        async def fake_check_dedup(db: Any, manifest: Any) -> Any:  # noqa: ARG001
            return self.dedup_decision
        monkeypatch.setattr(main_mod, "check_dedup", fake_check_dedup)

        # --- ingest_drop ---
        async def fake_ingest_drop(db: Any, parsed: dict, manifest: Any, run_id: uuid.UUID) -> Any:  # noqa: ARG001
            if self.ingest_drop_side_effect is not None:
                raise self.ingest_drop_side_effect
            return self.ingest_drop_result
        monkeypatch.setattr(main_mod, "ingest_drop", fake_ingest_drop)

        # --- quarantine ---
        async def fake_quarantine(drop_date: date, reason: Exception, run_id: uuid.UUID, correlation_id: uuid.UUID) -> None:  # noqa: ARG001
            self.quarantine_calls.append({
                "drop_date": drop_date,
                "reason_rule": getattr(reason, "rule", None),
                "run_id": run_id,
            })
        monkeypatch.setattr(main_mod, "quarantine_drop", fake_quarantine)

        # --- emit_event / bind / clear ---
        def fake_emit(name: str, **kwargs: Any) -> None:
            self.events.append((name, kwargs))
        monkeypatch.setattr(main_mod, "emit_event", fake_emit)
        monkeypatch.setattr(main_mod, "bind_run", lambda **_: None)
        monkeypatch.setattr(main_mod, "clear_run", lambda: None)

        # --- notify_* ---
        async def _make_notify(name: str):
            async def fake(*args: Any, **kwargs: Any) -> list[str]:  # noqa: ARG001
                self.notify_calls.append((name, dict(kwargs)))
                return []
            return fake
        # Workaround: pytest monkeypatch needs sync setters; build above with
        # asyncio.run can't be reused. Use module-level definitions instead.
        async def fake_notify_success(**kwargs: Any) -> list[str]:
            self.notify_calls.append(("success", kwargs))
            return []
        async def fake_notify_quarantine(**kwargs: Any) -> list[str]:
            self.notify_calls.append(("quarantine", kwargs))
            return []
        async def fake_notify_failure(**kwargs: Any) -> list[str]:
            self.notify_calls.append(("failure", kwargs))
            return []
        async def fake_notify_incident(**kwargs: Any) -> list[str]:
            self.notify_calls.append(("incident", kwargs))
            return []
        monkeypatch.setattr(main_mod, "notify_success", fake_notify_success)
        monkeypatch.setattr(main_mod, "notify_quarantine", fake_notify_quarantine)
        monkeypatch.setattr(main_mod, "notify_failure", fake_notify_failure)
        monkeypatch.setattr(main_mod, "notify_incident", fake_notify_incident)


def _eg_message(drop_date_iso: str = "2026-05-15") -> str:
    subj = f"/blobServices/default/containers/vendor-inbound/blobs/ventra/{drop_date_iso}/_MANIFEST.csv"
    return json.dumps(_eg_event(subj))


def _fake_manifest(drop: date) -> Any:
    from jobs.ventra_ingest.manifest import Manifest, ManifestEntry
    return Manifest(
        drop_date=drop,
        entries=[
            ManifestEntry(file_name="collections.csv", sha256="a" * 64, row_count=1),
            ManifestEntry(file_name="ar_snapshot.csv", sha256="b" * 64, row_count=1),
        ],
    )


def _fake_dedup_decision(skip_entirely: bool = False, already_processed: list[str] | None = None) -> Any:
    from jobs.ventra_ingest.validators import DedupDecision
    return DedupDecision(skip_entirely=skip_entirely, already_processed=already_processed or [])


def _fake_ingest_result(rows_written: int = 2) -> Any:
    from jobs.ventra_ingest.ingest import IngestResult
    return IngestResult(
        rows_written=rows_written,
        rows_by_table={"fact_collections_daily": 1, "fact_ar_snapshot": 1},
        vendor_source_systems=["CB"],
    )


async def test_happy_path_writes_data_and_notifies_success(monkeypatch: pytest.MonkeyPatch) -> None:
    h = _OrchestratorHarness()
    drop = date(2026, 5, 15)
    h.load_manifest_result = (_fake_manifest(drop), {"collections.csv": b"x", "ar_snapshot.csv": b"y"})
    h.parse_file_result = {"collections.csv": [object()], "ar_snapshot.csv": [object()]}
    h.dedup_decision = _fake_dedup_decision(skip_entirely=False)
    h.ingest_drop_result = _fake_ingest_result()
    h.install(monkeypatch)

    from jobs.ventra_ingest.main import process_one_message
    await process_one_message(_eg_message(), recipients=["ops@x.com"])

    assert h.session_used
    assert h.upn_set == ["ventra-ingest@system"]
    assert len(h.run_start_calls) == 1
    assert h.run_start_calls[0]["drop_date"] == drop

    # Terminal status was 'succeeded'
    assert len(h.run_complete_calls) == 1
    assert h.run_complete_calls[0]["status"] == "succeeded"
    assert h.run_complete_calls[0]["rows_out"] == 2

    # Events fired: manifest_received → validation_passed → rows_written×2 → ingest_complete
    event_names = [n for n, _ in h.events]
    assert "ventra.manifest_received" in event_names
    assert "ventra.validation_passed" in event_names
    assert event_names.count("ventra.rows_written") == 2
    assert "ventra.ingest_complete" in event_names

    # Success notification went out
    assert h.notify_calls[0][0] == "success"
    assert h.quarantine_calls == []


async def test_dedup_skip_short_circuits_before_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    h = _OrchestratorHarness()
    drop = date(2026, 5, 15)
    h.load_manifest_result = (_fake_manifest(drop), {"collections.csv": b"x", "ar_snapshot.csv": b"y"})
    h.parse_file_result = {"collections.csv": [object()], "ar_snapshot.csv": [object()]}
    h.dedup_decision = _fake_dedup_decision(
        skip_entirely=True,
        already_processed=["collections.csv", "ar_snapshot.csv"],
    )
    # If ingest_drop is reached, blow up — it should NOT be called
    h.ingest_drop_side_effect = AssertionError("ingest_drop must not run on dedup_skip")
    h.install(monkeypatch)

    from jobs.ventra_ingest.main import process_one_message
    await process_one_message(_eg_message(), recipients=["ops@x.com"])

    assert h.run_complete_calls[0]["status"] == "succeeded"
    event_names = [n for n, _ in h.events]
    assert "ventra.dedup_skip" in event_names
    assert "ventra.ingest_complete" not in event_names
    # No success notification on a dedup_skip (no operator-visible action)
    assert h.notify_calls == []


async def test_adr_violation_routes_to_incident_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from jobs.ventra_ingest.exceptions import ADRViolation
    h = _OrchestratorHarness()
    drop = date(2026, 5, 15)
    h.load_manifest_result = (_fake_manifest(drop), {"collections.csv": b"x", "ar_snapshot.csv": b"y"})
    h.parse_file_result = {"collections.csv": [object()], "ar_snapshot.csv": [object()]}
    h.fl_only_side_effect = ADRViolation(
        message="non-FL facility ... facility_no=801",
        details={"facility_no": 801, "hha_state": "TX"},
    )
    h.install(monkeypatch)

    from jobs.ventra_ingest.main import process_one_message
    await process_one_message(_eg_message(), recipients=["ops@x.com"])

    # Quarantine called (V12 still copies + writes sidecar)
    assert len(h.quarantine_calls) == 1
    assert h.quarantine_calls[0]["reason_rule"] == "V12"

    assert h.run_complete_calls[0]["status"] == "quarantined"

    event_names = [n for n, _ in h.events]
    assert "ventra.file_quarantined" in event_names
    assert "ventra.adr005_violation" in event_names

    # incident notification (NOT quarantine)
    assert h.notify_calls[0][0] == "incident"


async def test_validation_error_routes_to_quarantine_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from jobs.ventra_ingest.exceptions import ValidationError
    h = _OrchestratorHarness()
    h.load_manifest_result = ValidationError(
        rule="V3", message="sha256 mismatch on collections.csv",
        details={"file_name": "collections.csv"},
    )
    h.install(monkeypatch)

    from jobs.ventra_ingest.main import process_one_message
    await process_one_message(_eg_message(), recipients=["ops@x.com"])

    assert h.quarantine_calls[0]["reason_rule"] == "V3"
    assert h.run_complete_calls[0]["status"] == "quarantined"

    event_names = [n for n, _ in h.events]
    assert "ventra.file_quarantined" in event_names
    assert "ventra.validation_failed" in event_names
    assert "ventra.adr005_violation" not in event_names

    assert h.notify_calls[0][0] == "quarantine"


async def test_unhandled_exception_reraises_and_emits_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    h = _OrchestratorHarness()
    drop = date(2026, 5, 15)
    h.load_manifest_result = (_fake_manifest(drop), {"collections.csv": b"x", "ar_snapshot.csv": b"y"})
    h.parse_file_result = {"collections.csv": [object()], "ar_snapshot.csv": [object()]}
    h.dedup_decision = _fake_dedup_decision(skip_entirely=False)
    h.ingest_drop_side_effect = ConnectionError("postgres unreachable")
    h.install(monkeypatch)

    from jobs.ventra_ingest.main import process_one_message

    with pytest.raises(ConnectionError):
        await process_one_message(_eg_message(), recipients=["ops@x.com"])

    assert h.run_complete_calls[0]["status"] == "failed"
    assert h.run_complete_calls[0]["error_message"] == "postgres unreachable"

    event_names = [n for n, _ in h.events]
    assert "ventra.ingest_failed" in event_names
    # No quarantine call — unhandled errors don't copy to quarantine
    assert h.quarantine_calls == []
    # Failure notification, not quarantine/incident
    assert h.notify_calls[0][0] == "failure"


async def test_validation_error_caught_before_adr_check_does_not_emit_adr005(monkeypatch: pytest.MonkeyPatch) -> None:
    """A V13 quarantine should NOT emit adr005_violation — the catch order
    is ADRViolation (subclass) first, then plain ValidationError."""
    from jobs.ventra_ingest.exceptions import ValidationError
    h = _OrchestratorHarness()
    drop = date(2026, 5, 15)
    h.load_manifest_result = (_fake_manifest(drop), {"collections.csv": b"x", "ar_snapshot.csv": b"y"})
    h.parse_file_result = {"collections.csv": [object()], "ar_snapshot.csv": [object()]}
    # V13 raised from check_dedup
    h.dedup_decision = None  # won't be used; we'll patch check_dedup directly

    from jobs.ventra_ingest import main as main_mod

    async def raise_v13(db: Any, manifest: Any) -> Any:  # noqa: ARG001
        raise ValidationError(rule="V13", message="redelivery with changed content", details={})

    h.install(monkeypatch)
    monkeypatch.setattr(main_mod, "check_dedup", raise_v13)

    from jobs.ventra_ingest.main import process_one_message
    await process_one_message(_eg_message(), recipients=["ops@x.com"])

    event_names = [n for n, _ in h.events]
    assert "ventra.validation_failed" in event_names
    assert "ventra.adr005_violation" not in event_names
    assert h.notify_calls[0][0] == "quarantine"
