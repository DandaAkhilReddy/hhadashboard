"""Email service unit tests.

Cover:
- `is_configured` property (False when missing, True with connection string,
  True with endpoint+sender, False with sender alone).
- `send_html_email` short-circuits to None when not configured (no ACS
  client touched).
- `send_html_email` builds the right ACS message shape when configured —
  uses a mocked `EmailClient` to avoid real ACS calls.
- `render_email_template` renders alert_digest.html.j2 with sample data.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.email import EmailService, render_email_template


def test_is_configured_false_when_unset() -> None:
    svc = EmailService(endpoint="", connection_string="", sender="")
    assert svc.is_configured is False


def test_is_configured_false_when_only_sender_set() -> None:
    svc = EmailService(endpoint="", connection_string="", sender="x@y")
    assert svc.is_configured is False


def test_is_configured_true_with_connection_string() -> None:
    svc = EmailService(connection_string="endpoint=https://x;accesskey=k", sender="x@y")
    assert svc.is_configured is True


def test_is_configured_true_with_endpoint() -> None:
    svc = EmailService(endpoint="https://x.communication.azure.com", sender="x@y")
    assert svc.is_configured is True


@pytest.mark.asyncio
async def test_send_email_short_circuits_when_not_configured() -> None:
    svc = EmailService(endpoint="", connection_string="", sender="")
    result = await svc.send_html_email(
        to="recipient@x", subject="hi", html_body="<p>hi</p>"
    )
    assert result is None


@pytest.mark.asyncio
async def test_send_email_uses_acs_client_when_configured() -> None:
    """Verify the message shape the SDK receives matches ACS expectations."""
    fake_poller = MagicMock()
    fake_poller.result.return_value = {"id": "abc-123", "status": "Succeeded"}
    fake_client = MagicMock()
    fake_client.begin_send.return_value = fake_poller

    svc = EmailService(
        connection_string="endpoint=https://x;accesskey=k",
        sender="DoNotReply@hha.test",
    )
    # Inject the mock — bypasses _get_client's lazy SDK import.
    svc._client = fake_client

    msg_id = await svc.send_html_email(
        to="exec@hha.test",
        subject="Daily digest",
        html_body="<p>flag</p>",
        plain_text_body="flag",
    )

    assert msg_id == "abc-123"
    fake_client.begin_send.assert_called_once()
    sent_message = fake_client.begin_send.call_args.args[0]
    assert sent_message["senderAddress"] == "DoNotReply@hha.test"
    assert sent_message["recipients"]["to"] == [{"address": "exec@hha.test"}]
    assert sent_message["content"]["subject"] == "Daily digest"
    assert sent_message["content"]["html"] == "<p>flag</p>"
    assert sent_message["content"]["plainText"] == "flag"


def test_render_alert_digest_template_with_alerts() -> None:
    html = render_email_template(
        "alert_digest.html.j2",
        target_date="2026-04-25",
        alerts=[
            {
                "id": "fl-collections-below-target",
                "severity": "red",
                "category": "finance",
                "title": "FL collections below target",
                "detail": "Shortfall $44k/day",
                "owner": "Sandy Collins",
            },
        ],
        severity_colors={"red": "#dc2626", "yellow": "#f59e0b", "blue": "#2563eb"},
    )
    assert "FL collections below target" in html
    assert "Shortfall $44k/day" in html
    assert "Sandy Collins" in html
    assert "2026-04-25" in html


def test_render_alert_digest_template_empty_alerts() -> None:
    html = render_email_template(
        "alert_digest.html.j2",
        target_date="2026-04-25",
        alerts=[],
        severity_colors={"red": "#dc2626", "yellow": "#f59e0b", "blue": "#2563eb"},
    )
    assert "every monitored metric is within threshold" in html


def test_render_cred_scan_template() -> None:
    html = render_email_template(
        "cred_scan.html.j2",
        scan_date="2026-04-26",
        items=[
            {
                "physician_name": "Dr. Franklyn",
                "credential_type": "DEA",
                "expires_on": "2026-05-15",
                "threshold_band": 30,
            },
        ],
        band_colors={30: "#dc2626", 60: "#f59e0b", 90: "#2563eb"},
    )
    assert "Dr. Franklyn" in html
    assert "DEA" in html
    assert "2026-05-15" in html
    assert "≤ 30 d" in html


@pytest.mark.asyncio
async def test_lazy_client_init_does_not_import_sdk_when_unconfigured() -> None:
    """Ensure `is_configured=False` short-circuit avoids importing the heavy
    `azure.communication.email` chain — important for cold-start in cron jobs
    that have email turned off."""
    svc = EmailService(endpoint="", connection_string="", sender="")
    with patch("app.services.email.EmailService._get_client") as mock_get:
        await svc.send_html_email(to="x@y", subject="s", html_body="<p>b</p>")
        mock_get.assert_not_called()
