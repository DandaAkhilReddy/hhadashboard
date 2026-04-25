"""HHA Dashboard API — FastAPI entrypoint.

Local dev: uvicorn app.main:app --reload
Prod: gunicorn with uvicorn workers (behind Azure App Service).
"""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .core.logging import configure_logging, get_logger
from .deps import engine, get_current_user
from .routers import alerts, clinical, entries, finance, operations, people, scorecards, sites, uploads
from .services import audit as audit_service
from .settings import settings

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    # Audit row writing is handled by Postgres triggers (migration 0007), not
    # an ORM listener. The middleware below sets the UPN contextvar; the
    # `get_db` dep copies it into the Postgres GUC `audit.upn` for each
    # session so triggers attribute correctly.
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

# CORS — dev only. Prod uses same-origin via Azure App Service.
if settings.env == "dev":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


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
async def ready() -> dict[str, Any]:
    """Readiness probe — can serve traffic (DB reachable)."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ready", "db": "ok"}


app.include_router(sites.router)
app.include_router(operations.router)
app.include_router(finance.router)
app.include_router(clinical.router)
app.include_router(people.router)
app.include_router(scorecards.router)
app.include_router(alerts.router)
app.include_router(uploads.router)
app.include_router(entries.router)
