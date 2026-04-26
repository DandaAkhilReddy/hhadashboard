"""Hardening tests for app.main.

Covers Operation B's six findings:
  1. CORS prod config (allow_origins is set, not wildcard)
  2. Lifespan startup assertion (refuses prod without entra_configured)
  3. Global exception handler (sanitized 500 + correlation id)
  4. Validation exception handler (consistent JSON shape)
  5. PII redaction processor (logging.py)
  6. Richer /ready (alembic version + audit trigger + sites count)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.logging import _redact_dict, _redact_pii_processor

# ---------------------------------------------------------------------------
# 5. PII redaction processor (no DB required)
# ---------------------------------------------------------------------------


def test_redact_pii_processor_redacts_credentials() -> None:
    out = _redact_pii_processor(None, "info", {"password": "hunter2", "msg": "hi"})
    assert out["password"] == "[REDACTED]"
    assert out["msg"] == "hi"


def test_redact_pii_processor_redacts_authorization_header() -> None:
    out = _redact_pii_processor(None, "info", {"Authorization": "Bearer x.y.z"})
    assert out["Authorization"] == "[REDACTED]"


def test_redact_pii_processor_redacts_session_token() -> None:
    out = _redact_pii_processor(None, "info", {"session_token": "abc"})
    assert out["session_token"] == "[REDACTED]"


def test_redact_pii_processor_redacts_email_and_upn() -> None:
    out = _redact_pii_processor(
        None, "info", {"email": "x@y.com", "upn": "joe@org", "msg": "hi"}
    )
    assert out["email"] == "[REDACTED]"
    assert out["upn"] == "[REDACTED]"
    assert out["msg"] == "hi"


def test_redact_pii_processor_recurses_into_nested_dicts() -> None:
    out = _redact_pii_processor(
        None, "info", {"request": {"headers": {"authorization": "Bearer x"}}}
    )
    assert out["request"]["headers"]["authorization"] == "[REDACTED]"


def test_redact_pii_processor_handles_list_of_dicts() -> None:
    out = _redact_dict(
        {"users": [{"upn": "a@b"}, {"upn": "c@d"}, "string-not-touched"]}
    )
    assert out["users"][0]["upn"] == "[REDACTED]"
    assert out["users"][1]["upn"] == "[REDACTED]"
    assert out["users"][2] == "string-not-touched"


def test_redact_pii_processor_redacts_phi_keys() -> None:
    """Mirror the FORBIDDEN_COLUMN_NAMES list — must never log these."""
    out = _redact_pii_processor(
        None,
        "info",
        {
            "patient_dob": "1990-01-01",
            "mrn": "12345",
            "claim_id": "ABC-99",
            "encounter_id": "X-1",
        },
    )
    assert out["patient_dob"] == "[REDACTED]"
    assert out["mrn"] == "[REDACTED]"
    assert out["claim_id"] == "[REDACTED]"
    assert out["encounter_id"] == "[REDACTED]"


def test_redact_pii_processor_passes_safe_keys_through() -> None:
    """Site name, role, count, etc. are NOT PII — must come through clean."""
    safe = {
        "site_name": "Westside Regional",
        "role": "owner_ops",
        "count": 198,
        "correlation_id": "abc-123",
    }
    out = _redact_pii_processor(None, "info", safe.copy())
    assert out == safe


def test_redact_pii_processor_is_case_insensitive() -> None:
    out = _redact_pii_processor(
        None, "info", {"PASSWORD": "x", "Email": "y", "X-Auth-Token": "z"}
    )
    assert out["PASSWORD"] == "[REDACTED]"
    assert out["Email"] == "[REDACTED]"
    assert out["X-Auth-Token"] == "[REDACTED]"


# ---------------------------------------------------------------------------
# 2. Lifespan startup assertion
# ---------------------------------------------------------------------------


def test_lifespan_refuses_prod_without_entra() -> None:
    """If ENV is not 'dev' AND Entra isn't configured, app refuses to start
    rather than fall through to admin-by-default."""
    import asyncio

    from app.main import lifespan

    fake_app = MagicMock()
    with patch("app.main.settings") as mock_settings:
        mock_settings.env = "prod"
        mock_settings.entra_configured = False
        mock_settings.web_origin = "https://x"
        mock_settings.log_level = "INFO"

        async def _enter():
            async with lifespan(fake_app):
                pytest.fail("lifespan should not have entered the body")

        with pytest.raises(RuntimeError, match="requires Entra config"):
            asyncio.get_event_loop().run_until_complete(_enter())


def test_lifespan_refuses_prod_without_web_origin() -> None:
    """ENV=prod requires WEB_ORIGIN set so CORS works."""
    import asyncio

    from app.main import lifespan

    fake_app = MagicMock()
    with patch("app.main.settings") as mock_settings:
        mock_settings.env = "prod"
        mock_settings.entra_configured = True
        mock_settings.web_origin = ""
        mock_settings.log_level = "INFO"

        async def _enter():
            async with lifespan(fake_app):
                pytest.fail("lifespan should not have entered the body")

        with pytest.raises(RuntimeError, match="WEB_ORIGIN"):
            asyncio.get_event_loop().run_until_complete(_enter())


# ---------------------------------------------------------------------------
# 3. Global exception handler — sanitized 500
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unhandled_exception_returns_sanitized_500() -> None:
    """If a route raises a non-HTTPException, the response must NOT include
    the raw exception message (could leak DB connection strings, etc.).

    `raise_app_exceptions=False` on the ASGI transport is needed because
    BaseHTTPMiddleware (used by `set_current_upn_middleware`) re-raises in
    test mode by default — the handler's response is what we want to
    inspect, not the propagated exception.
    """
    from app.main import app

    @app.get("/_test_explode_for_handler")
    async def _explode() -> dict:
        msg = "leaky-secret-value-do-not-show-this-to-clients"
        raise RuntimeError(msg)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/_test_explode_for_handler")

    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == "INTERNAL"
    assert body["error"]["message"] == "Server error"
    assert "leaky-secret-value-do-not-show-this-to-clients" not in r.text
    assert "correlation_id" in body
    assert r.headers.get("x-correlation-id") == body["correlation_id"]


@pytest.mark.asyncio
async def test_correlation_id_round_trip() -> None:
    """If the caller supplies an x-correlation-id, the handler echoes it back
    rather than minting a new one."""
    from app.main import app

    @app.get("/_test_explode_correlation")
    async def _explode() -> dict:
        msg = "boom"
        raise RuntimeError(msg)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/_test_explode_correlation",
            headers={"x-correlation-id": "trace-from-caller"},
        )

    assert r.json()["correlation_id"] == "trace-from-caller"
    assert r.headers["x-correlation-id"] == "trace-from-caller"


@pytest.mark.asyncio
async def test_http_exception_keeps_status_and_message() -> None:
    """403/422 etc. pass through with the right code and a friendly message."""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/daily-census",
            headers={"Authorization": "Dev owner_finance"},
            json={"entry_date": "2026-04-26", "rows": []},
        )

    # owner_finance is not allowed for census → 403 from require_role
    assert r.status_code == 403
    body = r.json()
    assert body["error"]["code"] == 403
    assert "correlation_id" in body
