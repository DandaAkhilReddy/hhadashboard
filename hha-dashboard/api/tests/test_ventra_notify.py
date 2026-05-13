"""Notify wrapper tests for the Ventra ingest pipeline.

Renders the 4 templates with realistic context and asserts the right
fields land in the rendered HTML. Mocks ``email_service.send_html_email``
to verify per-recipient fan-out.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest
from jobs.ventra_ingest.notify import (
    notify_failure,
    notify_incident,
    notify_quarantine,
    notify_success,
    parse_recipients,
)

from app.services.email import render_email_template

pytestmark = pytest.mark.asyncio


DROP = date(2026, 5, 15)
RUN_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
CORR_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


# =========================================================================
# parse_recipients
# =========================================================================


def test_parse_recipients_splits_comma_separated() -> None:
    assert parse_recipients("a@x.com,b@x.com,c@x.com") == [
        "a@x.com",
        "b@x.com",
        "c@x.com",
    ]


def test_parse_recipients_strips_whitespace() -> None:
    assert parse_recipients("a@x.com, b@x.com ,  c@x.com") == [
        "a@x.com",
        "b@x.com",
        "c@x.com",
    ]


def test_parse_recipients_drops_empty_segments() -> None:
    assert parse_recipients("a@x.com,,b@x.com,,,") == ["a@x.com", "b@x.com"]


@pytest.mark.parametrize("value", [None, "", "   ", ",, ,"])
def test_parse_recipients_returns_empty_for_blank(value: str | None) -> None:
    assert parse_recipients(value) == []


# =========================================================================
# Template rendering — pure render, no ACS calls
# =========================================================================


def test_success_template_renders_expected_fields() -> None:
    html = render_email_template(
        "ventra_success.html.j2",
        drop_date="2026-05-15",
        rows_written=55,
        rows_by_table={"fact_collections_daily": 25, "fact_ar_snapshot": 30},
        vendor_source_systems=["CB", "MGS"],
        duration_seconds="14.3",
        run_id=str(RUN_ID),
        correlation_id=str(CORR_ID),
    )
    assert "Drop processed — 2026-05-15" in html
    assert "fact_collections_daily" in html
    assert "25 rows" in html
    assert "55" in html
    assert "CB, MGS" in html
    assert str(RUN_ID) in html
    assert "pulse.hhamedicine.com/boards/finance" in html


def test_quarantine_template_renders_expected_fields() -> None:
    html = render_email_template(
        "ventra_quarantine.html.j2",
        drop_date="2026-05-15",
        rule="V5",
        message="collections.csv line 3 failed V5",
        details={"file_name": "collections.csv", "line_no": 3},
        run_id=str(RUN_ID),
        correlation_id=str(CORR_ID),
    )
    assert "Drop quarantined — 2026-05-15" in html
    assert "ACTION REQUIRED" in html
    assert "Rule V5" in html
    assert "collections.csv line 3 failed V5" in html
    assert "vendor-quarantine/ventra/2026-05-15/_REJECT_REASON.txt" in html
    assert "vendor-inbound/ventra/2026-05-15-retry-1/" in html


def test_failure_template_renders_expected_fields() -> None:
    html = render_email_template(
        "ventra_failure.html.j2",
        drop_date="2026-05-15",
        error_type="ConnectionError",
        error_message="could not connect to postgres",
        run_id=str(RUN_ID),
        correlation_id=str(CORR_ID),
    )
    assert "Ingest failed — 2026-05-15" in html
    assert "UNHANDLED FAILURE" in html
    assert "ConnectionError" in html
    assert "could not connect to postgres" in html
    assert str(CORR_ID) in html


def test_incident_template_renders_expected_fields() -> None:
    html = render_email_template(
        "ventra_incident.html.j2",
        drop_date="2026-05-15",
        message="non-FL facility in Ventra drop: collections.csv line 3 facility_no=801 hha_state=TX",
        details={"facility_no": 801, "hha_state": "TX", "file_name": "collections.csv"},
        run_id=str(RUN_ID),
        correlation_id=str(CORR_ID),
    )
    assert "INCIDENT · ADR-005 VIOLATION" in html
    assert "Non-Florida facility" in html
    assert "Rule V12 · ADR-005" in html
    assert "SECURITY_INCIDENT_PLAYBOOK.md" in html
    assert "facility_no" in html
    assert "801" in html


# =========================================================================
# notify_* fan-out — mock email_service to capture send calls
# =========================================================================


class _EmailSpy:
    def __init__(self, message_id: str | None = "msg-stub") -> None:
        self.message_id = message_id
        self.sends: list[dict[str, Any]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_send(self_, to: str, subject: str, html_body: str, plain_text_body: str | None = None) -> str | None:  # noqa: ARG001 — self_ stands in for the bound EmailService
            self.sends.append(
                {
                    "to": to,
                    "subject": subject,
                    "html_body": html_body,
                    "plain_text_body": plain_text_body,
                }
            )
            return self.message_id

        from app.services import email as email_module
        monkeypatch.setattr(
            email_module.EmailService, "send_html_email", fake_send
        )


async def test_notify_success_fans_out_to_every_recipient(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _EmailSpy(message_id="m1")
    spy.install(monkeypatch)

    msg_ids = await notify_success(
        drop_date=DROP,
        rows_written=55,
        rows_by_table={"fact_collections_daily": 25, "fact_ar_snapshot": 30},
        vendor_source_systems=["CB"],
        duration_seconds=14.5,
        run_id=RUN_ID,
        correlation_id=CORR_ID,
        recipients=["a@x.com", "b@x.com"],
    )
    assert len(spy.sends) == 2
    assert msg_ids == ["m1", "m1"]
    assert {s["to"] for s in spy.sends} == {"a@x.com", "b@x.com"}
    # All recipients receive the same subject + body
    subjects = {s["subject"] for s in spy.sends}
    assert subjects == {"Ventra drop processed — 2026-05-15"}
    assert all("Drop processed — 2026-05-15" in s["html_body"] for s in spy.sends)


async def test_notify_quarantine_subject_includes_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _EmailSpy()
    spy.install(monkeypatch)

    await notify_quarantine(
        drop_date=DROP,
        rule="V9",
        message="ar_snapshot.csv line 5 duplicates ...",
        details={"facility_no": 901, "aging_bucket": "0-30"},
        run_id=RUN_ID,
        correlation_id=CORR_ID,
        recipients=["ops@x.com"],
    )
    assert len(spy.sends) == 1
    s = spy.sends[0]
    assert s["subject"] == "[ACTION REQUIRED] Ventra drop quarantined — 2026-05-15 (rule V9)"
    assert "Rule V9" in s["html_body"]


async def test_notify_failure_subject_marks_urgent(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _EmailSpy()
    spy.install(monkeypatch)

    await notify_failure(
        drop_date=DROP,
        error_type="ConnectionError",
        error_message="postgres unreachable",
        run_id=RUN_ID,
        correlation_id=CORR_ID,
        recipients=["ops@x.com"],
    )
    s = spy.sends[0]
    assert s["subject"] == "[URGENT] Ventra ingest failed — 2026-05-15"
    assert "ConnectionError" in s["html_body"]


async def test_notify_incident_subject_marks_incident(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _EmailSpy()
    spy.install(monkeypatch)

    await notify_incident(
        drop_date=DROP,
        message="non-FL facility ... facility_no=801",
        details={"facility_no": 801, "hha_state": "TX"},
        run_id=RUN_ID,
        correlation_id=CORR_ID,
        recipients=["ops@x.com", "compliance@x.com"],
    )
    assert len(spy.sends) == 2
    s = spy.sends[0]
    assert s["subject"] == (
        "[INCIDENT] ADR-005 violation — non-FL facility in Ventra drop 2026-05-15"
    )
    assert "INCIDENT · ADR-005 VIOLATION" in s["html_body"]


async def test_notify_empty_recipients_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _EmailSpy()
    spy.install(monkeypatch)

    result = await notify_success(
        drop_date=DROP,
        rows_written=0,
        rows_by_table={},
        vendor_source_systems=[],
        duration_seconds=0.1,
        run_id=RUN_ID,
        correlation_id=CORR_ID,
        recipients=[],
    )
    assert result == []
    assert spy.sends == []


async def test_notify_drops_none_message_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """When email is not configured, send_html_email returns None.
    notify_* should filter those out of the returned list."""
    spy = _EmailSpy(message_id=None)
    spy.install(monkeypatch)

    result = await notify_quarantine(
        drop_date=DROP,
        rule="V5",
        message="x",
        details={},
        run_id=RUN_ID,
        correlation_id=CORR_ID,
        recipients=["a@x.com", "b@x.com"],
    )
    # Both sends issued (recorded by the spy) but no message IDs returned
    assert len(spy.sends) == 2
    assert result == []
