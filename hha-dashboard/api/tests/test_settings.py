"""Unit tests for app.settings property contracts.

Pin the *_configured booleans that gate every downstream service. A
regression in these is silent: ACS / Paycom / Entra would just stay
in no-op mode and the next deploy would discover the broken config
in production instead of CI.
"""

from __future__ import annotations

from app.settings import Settings

# ----- email_configured (line 99-109) -----


def test_email_configured_false_when_everything_unset() -> None:
    s = Settings(
        azure_communication_sender="",
        azure_communication_connection_string="",
        azure_communication_endpoint="",
    )
    assert s.email_configured is False


def test_email_configured_false_when_only_sender_set() -> None:
    """Sender alone is not enough — also need either MI endpoint or conn str."""
    s = Settings(
        azure_communication_sender="DoNotReply@hha.test",
        azure_communication_connection_string="",
        azure_communication_endpoint="",
    )
    assert s.email_configured is False


def test_email_configured_false_when_only_endpoint_set() -> None:
    """Endpoint alone is not enough — sender required for ACS API."""
    s = Settings(
        azure_communication_sender="",
        azure_communication_connection_string="",
        azure_communication_endpoint="https://hha.communication.azure.com",
    )
    assert s.email_configured is False


def test_email_configured_true_with_sender_and_connection_string() -> None:
    """Dev path: sender + connection string."""
    s = Settings(
        azure_communication_sender="DoNotReply@hha.test",
        azure_communication_connection_string="endpoint=https://x;accesskey=k",
        azure_communication_endpoint="",
    )
    assert s.email_configured is True


def test_email_configured_true_with_sender_and_endpoint() -> None:
    """Prod path: sender + MI-able endpoint (no conn str needed)."""
    s = Settings(
        azure_communication_sender="DoNotReply@hha.test",
        azure_communication_connection_string="",
        azure_communication_endpoint="https://hha.communication.azure.com",
    )
    assert s.email_configured is True


# ----- paycom_configured (line 120-128) -----


def test_paycom_configured_false_when_all_unset() -> None:
    s = Settings(
        paycom_api_base_url="",
        paycom_client_id="",
        paycom_client_secret="",
    )
    assert s.paycom_configured is False


def test_paycom_configured_false_when_missing_secret() -> None:
    """All three creds required — partial config returns False so the cron
    stays in no-op mode rather than failing mid-API-call."""
    s = Settings(
        paycom_api_base_url="https://paycom.example.com",
        paycom_client_id="client",
        paycom_client_secret="",
    )
    assert s.paycom_configured is False


def test_paycom_configured_false_when_missing_client_id() -> None:
    s = Settings(
        paycom_api_base_url="https://paycom.example.com",
        paycom_client_id="",
        paycom_client_secret="secret",
    )
    assert s.paycom_configured is False


def test_paycom_configured_false_when_missing_base_url() -> None:
    s = Settings(
        paycom_api_base_url="",
        paycom_client_id="client",
        paycom_client_secret="secret",
    )
    assert s.paycom_configured is False


def test_paycom_configured_true_when_all_three_set() -> None:
    """The cron job uses this to decide whether to actually call the API
    or short-circuit to its 'access not yet granted' log line."""
    s = Settings(
        paycom_api_base_url="https://paycom.example.com",
        paycom_client_id="client",
        paycom_client_secret="secret",
    )
    assert s.paycom_configured is True
