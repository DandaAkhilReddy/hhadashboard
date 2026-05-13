"""HHA Dashboard API — FastAPI entrypoint.

Local dev: uvicorn app.main:app --reload
Prod: gunicorn with uvicorn workers (behind Azure App Service).
"""

from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .core.logging import configure_logging, get_logger
from .core.telemetry import setup_telemetry
from .deps import engine, get_current_user
from .routers import (
    alerts,
    census_portal,
    clinical,
    entries,
    finance,
    finance_ventra,
    operations,
    people,
    scorecards,
    sites,
    uploads,
)
from .services import audit as audit_service
from .settings import settings

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app_: FastAPI):
    configure_logging(settings.log_level)
    # Audit row writing is handled by Postgres triggers (migration 0007), not
    # an ORM listener. The middleware below sets the UPN contextvar; the
    # `get_db` dep copies it into the Postgres GUC `audit.upn` for each
    # session so triggers attribute correctly.

    # Defense in depth: refuse to start in non-dev environments unless Entra
    # is configured. Without this, a misconfigured ENV var (e.g. ENV=dev
    # accidentally shipping in prod) lets the auth fall-through path return
    # admin for every unauth'd request. Belt-and-suspenders alongside the
    # tightened deps.py Path 3.
    if settings.env != "dev" and not settings.entra_configured:
        msg = (
            f"Refusing to start: ENV={settings.env!r} requires Entra config "
            "(AZURE_TENANT_ID + AZURE_API_CLIENT_ID). Set them or set ENV=dev."
        )
        raise RuntimeError(msg)

    if settings.env != "dev" and not settings.web_origin:
        msg = (
            f"Refusing to start: ENV={settings.env!r} requires WEB_ORIGIN to be set "
            "so CORS allows the web App Service hostname."
        )
        raise RuntimeError(msg)

    # OpenTelemetry / App Insights — no-op when settings.telemetry_configured
    # is False. Audit ticket T6.
    setup_telemetry(app_)

    log.info("api.startup", env=settings.env, log_level=settings.log_level)
    yield
    await engine.dispose()
    log.info("api.shutdown")


app = FastAPI(
    title="HHA Dashboard API",
    version="0.2.0",
    description=(
        "HHA Medicine Operations Dashboard — FastAPI backend. "
        "See docs/adr/001-hipaa-data-classification.md for HIPAA posture."
    ),
    lifespan=lifespan,
)

# CORS — explicit allow_origins per environment. Web and api are deployed as
# separate App Services with separate hostnames (per Bicep), so this is NOT
# a same-origin setup. Prod must have settings.web_origin set; the lifespan
# guard above refuses to start without it.
_cors_origins: list[str] = (
    ["http://localhost:3000"] if settings.env == "dev" else [settings.web_origin]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)


# ---------- Exception handlers ----------
#
# Two layered handlers:
#   - HTTPException pass-through preserves FastAPI's existing JSON shape
#     (used by routers for 4xx role gates, validation, etc.).
#   - Catch-all returns a sanitized 500 with NO exception detail leaked to
#     the caller. The full traceback is logged structured (via structlog +
#     the PII redaction processor) so it's queryable in Log Analytics.
#
# Validation errors (422) keep their default FastAPI shape — they're already
# safe and helpful to the client.


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    correlation_id = (
        structlog.contextvars.get_contextvars().get("request_id")
        or request.headers.get("x-correlation-id")
        or str(uuid4())
    )
    log.info(
        "http_exception",
        status_code=exc.status_code,
        path=request.url.path,
        correlation_id=correlation_id,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.status_code,
                "message": exc.detail if isinstance(exc.detail, str) else "Error",
            },
            "correlation_id": correlation_id,
        },
        headers={"x-correlation-id": correlation_id},
    )


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    correlation_id = (
        structlog.contextvars.get_contextvars().get("request_id")
        or request.headers.get("x-correlation-id")
        or str(uuid4())
    )
    # Pydantic v2 validation errors can carry non-JSON-serializable context
    # (e.g., a ValueError instance in `ctx`). `jsonable_encoder` walks the
    # structure and stringifies anything it can't serialize directly.
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder(
            {
                "error": {
                    "code": 422,
                    "message": "Validation error",
                    "details": exc.errors(),
                },
                "correlation_id": correlation_id,
            }
        ),
        headers={"x-correlation-id": correlation_id},
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Catch-all. Logs the full exception structurally; returns a sanitized
    body so internal details (DB connection strings, file paths, etc.)
    never reach the client."""
    correlation_id = (
        structlog.contextvars.get_contextvars().get("request_id")
        or request.headers.get("x-correlation-id")
        or str(uuid4())
    )
    log.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        correlation_id=correlation_id,
        exc_type=type(exc).__name__,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {"code": "INTERNAL", "message": "Server error"},
            "correlation_id": correlation_id,
        },
        headers={"x-correlation-id": correlation_id},
    )


# ---------- Request-id middleware ----------
#
# Bind a per-request correlation id to structlog contextvars so every log
# record in the request scope is automatically tagged. The id flows
# through to:
#   - Every structlog record (via `merge_contextvars` in core/logging.py)
#   - Every error response body (`correlation_id` field, read by exception
#     handlers above)
#   - The `X-Correlation-Id` response header (echoed even on success so
#     the caller can re-use the id for follow-up support tickets / cross-
#     service tracing)
#
# Honors caller-supplied `X-Correlation-Id` header so an upstream gateway
# / smoke-test script can pin a known id end-to-end.
#
# Audit ticket T6.
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("x-correlation-id") or str(uuid4())
    # Fresh request: clear any contextvars left by a prior coroutine on
    # this worker (defensive; the ContextVar should already be empty).
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    try:
        response = await call_next(request)
    finally:
        structlog.contextvars.clear_contextvars()
    response.headers["x-correlation-id"] = request_id
    return response


# ---------- UPN contextvar middleware ----------
#
# The Postgres audit trigger reads UPN from a session GUC `audit.upn` set in
# `deps.get_db`. This middleware just keeps a Python contextvar in sync per
# request so `get_db` can read it. Fallback '__system__' for health checks /
# unauth routes.
@app.middleware("http")
async def set_current_upn_middleware(request: Request, call_next):
    upn = "__system__"
    # Best-effort resolve — don't crash the middleware if auth fails here.
    # The endpoint's own Depends(get_current_user) will 401 properly for protected routes.
    try:
        authorization = request.headers.get("authorization")
        if authorization:
            user = await get_current_user(authorization=authorization)
            upn = user.upn
    except Exception:
        pass  # leave as __system__
    token = audit_service.set_current_upn(upn)
    try:
        response = await call_next(request)
    finally:
        audit_service.current_upn.reset(token)
    return response


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness probe — process is alive."""
    return {"status": "ok"}


@app.get("/ready", tags=["meta"])
async def ready() -> Any:
    """Readiness probe — checks more than DB connectivity.

    Returns 200 only when:
      1. DB connection works (SELECT 1).
      2. Alembic version matches the latest expected revision (catches partial
         deploys where the schema is mid-migration).
      3. The audit trigger function exists in the `audit` schema (catches
         scenarios where the trigger was dropped — a HIPAA-relevant silent
         failure mode).
      4. There's at least one site row (the dashboard would render blank
         without seeded data; in fresh deploys the operator runs scripts/
         seed_sites.py before flipping the App Service to live traffic).

    Returns 503 with a per-check breakdown otherwise. Cheap query cost
    (~3 SELECTs) — runs on every App Service health probe, no big deal.
    """
    expected_revision = _expected_alembic_revision()
    checks: dict[str, Any] = {}

    async with engine.connect() as conn:
        try:
            await conn.execute(text("SELECT 1"))
            checks["db"] = "ok"
        except Exception as e:
            checks["db"] = f"error: {type(e).__name__}"
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "checks": checks},
            )

        # Alembic head — must match the latest version baked into the image.
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        version = result.scalar_one_or_none()
        if version == expected_revision:
            checks["schema"] = "ok"
        else:
            checks["schema"] = f"mismatch (got={version!r} expected={expected_revision!r})"

        # Audit trigger function presence.
        result = await conn.execute(
            text(
                "SELECT 1 FROM pg_proc p "
                "JOIN pg_namespace n ON p.pronamespace = n.oid "
                "WHERE n.nspname = 'audit' AND p.proname = 'log_change'"
            )
        )
        checks["audit_trigger"] = "ok" if result.scalar_one_or_none() else "missing"

        # Sites seeded?
        result = await conn.execute(text("SELECT COUNT(*) FROM masters.sites"))
        sites_count = result.scalar_one()
        checks["sites"] = "ok" if sites_count > 0 else "empty"

    all_ok = all(v == "ok" for v in checks.values())
    if all_ok:
        return {"status": "ready", "checks": checks}
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "checks": checks},
    )


def _expected_alembic_revision() -> str:
    """Return the latest revision id baked into this image — the maximum
    revision among files in alembic/versions/. Computed once at startup
    and cached. The /ready probe compares the deployed DB's
    alembic_version.version_num to this; mismatch → 503."""
    global _CACHED_ALEMBIC_HEAD
    if _CACHED_ALEMBIC_HEAD is not None:
        return _CACHED_ALEMBIC_HEAD
    import re
    from pathlib import Path

    versions_dir = Path(__file__).parent.parent / "alembic" / "versions"
    head = "0000"  # safety default
    for path in versions_dir.glob("*.py"):
        m = re.match(r"^(\d+)_", path.name)
        if m and m.group(1) > head:
            head = m.group(1)
    _CACHED_ALEMBIC_HEAD = head
    return head


_CACHED_ALEMBIC_HEAD: str | None = None


app.include_router(sites.router)
app.include_router(operations.router)
app.include_router(finance.router)
app.include_router(finance_ventra.router)
app.include_router(clinical.router)
app.include_router(people.router)
app.include_router(scorecards.router)
app.include_router(alerts.router)
app.include_router(uploads.router)
app.include_router(entries.router)
app.include_router(census_portal.router)
