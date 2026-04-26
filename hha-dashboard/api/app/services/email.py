"""Email service — Azure Communication Services wrapper.

Two auth paths:
- **Connection string** (set `AZURE_COMMUNICATION_CONNECTION_STRING`): used for
  local dev when there's no managed identity available.
- **Managed identity** (set `AZURE_COMMUNICATION_ENDPOINT`, no connection
  string): production path. The App Service / Container Apps Job's MI must
  hold the Contributor role (or `Email Communication Service Contributor`)
  on the ACS resource.

When neither is configured, `EmailService.is_configured` returns False and
`send_html_email` becomes a logged no-op. This mirrors the
`paycom_configured`-or-noop pattern from Session 11 — both crons (alert_digest,
cred_scan) check the flag and exit cleanly when email isn't wired.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.settings import settings

logger = structlog.get_logger(__name__)

# Templates live next to this module; both crons import them from here so
# there's one canonical Jinja env (autoescape on, undefined-variable strict).
_TEMPLATES_DIR = Path(__file__).parent / "email_templates"
_jinja_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "j2", "html.j2"]),
)


def render_email_template(name: str, **context: Any) -> str:
    """Render `name` from `email_templates/`. Caller passes template variables
    as kwargs. Used by alert_digest and cred_scan crons."""
    template = _jinja_env.get_template(name)
    return template.render(**context)


class EmailService:
    """Async wrapper around `azure.communication.email.EmailClient`.

    The ACS SDK is sync; we run it inside `asyncio.to_thread` so callers can
    `await` cleanly without blocking the event loop.
    """

    def __init__(
        self,
        endpoint: str = "",
        connection_string: str = "",
        sender: str = "",
    ) -> None:
        self._endpoint = endpoint or settings.azure_communication_endpoint
        self._connection_string = (
            connection_string or settings.azure_communication_connection_string
        )
        self._sender = sender or settings.azure_communication_sender
        self._client: Any | None = None  # lazy-initialized

    @property
    def is_configured(self) -> bool:
        """True when we have enough credentials to actually send."""
        return bool(self._sender and (self._connection_string or self._endpoint))

    def _get_client(self) -> Any:
        """Build the ACS client on first use. Lazy because importing
        `azure.communication.email` pulls a heavy chain we don't want at
        module-import time (e.g., when `is_configured` is False)."""
        if self._client is not None:
            return self._client
        from azure.communication.email import EmailClient

        if self._connection_string:
            self._client = EmailClient.from_connection_string(self._connection_string)
        else:
            from azure.identity import DefaultAzureCredential

            self._client = EmailClient(self._endpoint, DefaultAzureCredential())
        return self._client

    async def send_html_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        plain_text_body: str | None = None,
    ) -> str | None:
        """Send a single HTML email. Returns the ACS message-id on success,
        None on no-op (email not configured).

        Raises whatever the ACS SDK raises on a hard failure — caller decides
        whether to retry. The cron jobs catch and log so a single bad recipient
        doesn't kill the whole digest run.
        """
        if not self.is_configured:
            logger.info(
                "email.skip_not_configured",
                to=to,
                subject=subject,
            )
            return None

        import asyncio

        client = self._get_client()
        message: dict[str, Any] = {
            "senderAddress": self._sender,
            "recipients": {"to": [{"address": to}]},
            "content": {
                "subject": subject,
                "html": html_body,
            },
        }
        if plain_text_body is not None:
            message["content"]["plainText"] = plain_text_body

        # ACS SDK is sync — push to a thread.
        poller = await asyncio.to_thread(client.begin_send, message)
        result = await asyncio.to_thread(poller.result)
        message_id: str = result.get("id", "")
        logger.info(
            "email.sent",
            to=to,
            subject=subject,
            message_id=message_id,
            status=result.get("status"),
        )
        return message_id


# Module-level singleton so callers don't reconfigure on every import.
email_service = EmailService()
