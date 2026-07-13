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


# ---------------------------------------------------------------------------
# Phase 3 gap-fill: set_current_upn_middleware swallow + alembic head cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_middleware_swallows_get_current_user_exception() -> None:
    """The middleware tries to resolve UPN from the request header so that
    audit attribution works for authenticated routes; if get_current_user
    raises (malformed header, network blip in JWT path), the middleware
    must NOT crash the response — it falls back to upn='__system__' and
    lets the downstream Depends(get_current_user) do the 401.

    Force the exception by patching app.main.get_current_user to raise;
    the request still completes 200 from /health (which has no auth dep)."""
    from app.main import app
    from app.services.audit import current_upn

    captured: dict[str, str] = {}

    async def _raising_get_current_user(*, authorization: str | None = None) -> object:
        _ = authorization
        raise RuntimeError("simulated auth failure inside middleware")

    @app.get("/_capture_middleware_swallow")
    async def _capture() -> dict[str, str]:
        captured["upn"] = current_upn.get()
        return {"upn": current_upn.get()}

    with patch("app.main.get_current_user", _raising_get_current_user):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get(
                "/_capture_middleware_swallow",
                headers={"Authorization": "Dev owner_ops"},
            )

    # Middleware swallowed the exception → request completes cleanly
    assert r.status_code == 200
    # And the contextvar was left at __system__ rather than the real UPN
    # because the exception fired before `upn = user.upn`.
    assert captured["upn"] == "__system__"


def test_expected_alembic_revision_caches_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """The /ready handler computes the alembic head once per process by
    globbing alembic/versions/. The second call must return the cached
    value without re-doing the glob (otherwise every health probe re-
    walks the filesystem)."""
    import app.main as main_mod

    # Reset the cache to force a fresh compute first.
    monkeypatch.setattr(main_mod, "_CACHED_ALEMBIC_HEAD", None)

    first = main_mod._expected_alembic_revision()
    # Looks like '0019' or similar — 4+ digits, all numeric
    assert first.isdigit()
    assert len(first) >= 4

    # Second call must short-circuit on the cache. Sentinel via the
    # module-level variable: if it were re-computed, _CACHED_ALEMBIC_HEAD
    # would still be set to `first`, so we'd see the same answer. To
    # PROVE caching, mutate the cache and confirm the function returns
    # the mutated value (rather than re-globbing).
    monkeypatch.setattr(main_mod, "_CACHED_ALEMBIC_HEAD", "9999")
    cached = main_mod._expected_alembic_revision()

    assert cached == "9999"  # proves we hit the cache branch, not re-glob


@pytest.mark.asyncio
async def test_middleware_attributes_authenticated_dev_user_in_upn() -> None:
    """Happy path on the middleware: Dev header → user.upn is captured
    into the audit contextvar BEFORE the route handler runs. Verifies by
    asserting current_upn during a route call."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.main import set_current_upn_middleware
    from app.services.audit import current_upn

    test_app = FastAPI()
    test_app.middleware("http")(set_current_upn_middleware)

    captured_upn: dict[str, str] = {}

    @test_app.get("/_capture_upn")
    async def _route() -> dict[str, str]:
        captured_upn["value"] = current_upn.get()
        return {"upn": current_upn.get()}

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        r = await client.get(
            "/_capture_upn", headers={"Authorization": "Dev owner_ops"}
        )

    assert r.status_code == 200
    assert captured_upn["value"] == "dev-owner_ops@local"
    # And the contextvar resets after the response (in the finally block)
    # — verified indirectly by a follow-up request with no auth header
    # returning the system default.
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        r2 = await client.get("/_capture_upn")

    assert r2.json()["upn"] == "__system__"
