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


# ----- _get_client() lazy-init paths (Phase 3 coverage uplift) -----


def test_get_client_uses_connection_string_when_present() -> None:
    """Connection-string path: dev/local. Must call from_connection_string
    rather than constructing with DefaultAzureCredential."""
    fake_client = MagicMock(name="EmailClient")
    fake_from_cs = MagicMock(return_value=fake_client)

    svc = EmailService(
        connection_string="endpoint=https://x;accesskey=k",
        sender="DoNotReply@hha.test",
    )

    with patch(
        "azure.communication.email.EmailClient.from_connection_string",
        fake_from_cs,
    ):
        client = svc._get_client()

    assert client is fake_client
    fake_from_cs.assert_called_once_with("endpoint=https://x;accesskey=k")


def test_get_client_falls_back_to_managed_identity_when_no_connection_string() -> None:
    """Production path: MI via DefaultAzureCredential. Triggered when
    endpoint is set and connection_string is empty."""
    fake_credential = MagicMock(name="DefaultAzureCredential-instance")
    fake_credential_factory = MagicMock(return_value=fake_credential)
    fake_client = MagicMock(name="EmailClient")
    fake_client_ctor = MagicMock(return_value=fake_client)

    svc = EmailService(
        endpoint="https://hha.communication.azure.com",
        connection_string="",
        sender="DoNotReply@hha.test",
    )

    with (
        patch("azure.identity.DefaultAzureCredential", fake_credential_factory),
        patch("azure.communication.email.EmailClient", fake_client_ctor),
    ):
        client = svc._get_client()

    assert client is fake_client
    fake_credential_factory.assert_called_once_with()
    fake_client_ctor.assert_called_once_with(
        "https://hha.communication.azure.com",
        fake_credential,
    )


def test_get_client_is_cached_on_second_call() -> None:
    """The lazy-init path runs once; subsequent calls return the cached
    client. Without caching, every send_html_email would re-init the SDK
    and re-resolve MI — wasteful and would also re-import the heavy
    azure.communication.email module."""
    fake_client = MagicMock(name="EmailClient-cached")
    fake_from_cs = MagicMock(return_value=fake_client)

    svc = EmailService(
        connection_string="endpoint=https://x;accesskey=k",
        sender="DoNotReply@hha.test",
    )

    with patch(
        "azure.communication.email.EmailClient.from_connection_string",
        fake_from_cs,
    ):
        first = svc._get_client()
        second = svc._get_client()

    assert first is second
    fake_from_cs.assert_called_once()  # never called the second time


@pytest.mark.asyncio
async def test_send_email_omits_plain_text_when_none() -> None:
    """If plain_text_body is None, the ACS message must NOT carry a
    plainText field — passing plainText=None makes ACS reject the request
    with a validation error."""
    fake_poller = MagicMock()
    fake_poller.result.return_value = {"id": "html-only", "status": "Succeeded"}
    fake_client = MagicMock()
    fake_client.begin_send.return_value = fake_poller

    svc = EmailService(
        connection_string="endpoint=https://x;accesskey=k",
        sender="DoNotReply@hha.test",
    )
    svc._client = fake_client

    msg_id = await svc.send_html_email(
        to="exec@hha.test",
        subject="No plain",
        html_body="<p>html only</p>",
        plain_text_body=None,
    )

    assert msg_id == "html-only"
    sent_message = fake_client.begin_send.call_args.args[0]
    assert "plainText" not in sent_message["content"]
    assert sent_message["content"]["html"] == "<p>html only</p>"


@pytest.mark.asyncio
async def test_send_email_returns_empty_string_when_acs_omits_id() -> None:
    """Defensive: result.get('id', '') defaults to '' if ACS ever omits the
    id field — the caller still gets a non-None message_id so they can
    distinguish a real send from the not-configured short-circuit (None)."""
    fake_poller = MagicMock()
    fake_poller.result.return_value = {"status": "Succeeded"}  # no 'id' key
    fake_client = MagicMock()
    fake_client.begin_send.return_value = fake_poller

    svc = EmailService(
        connection_string="endpoint=https://x;accesskey=k",
        sender="DoNotReply@hha.test",
    )
    svc._client = fake_client

    msg_id = await svc.send_html_email(
        to="recipient@hha.test",
        subject="weird ACS reply",
        html_body="<p>x</p>",
    )

    assert msg_id == ""
    assert msg_id is not None  # NOT the not-configured short-circuit
