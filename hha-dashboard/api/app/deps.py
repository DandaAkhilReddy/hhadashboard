"""FastAPI dependencies: DB session, current user (Entra MSAL in prod, dev stub now).

Dev mode (ENV=dev): accepts `Authorization: Dev <role>` header to simulate a user.
Prod: verifies Entra ID JWT via jwks metadata (wired in Session 2).
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as SyncSession

from .services.audit import current_upn
from .settings import settings

engine = create_async_engine(settings.database_url, echo=False, future=True, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


# Lazy GUC: when a session actually starts a transaction (= real work is
# about to happen), copy the request's UPN contextvar into the Postgres
# session GUC `audit.upn`. The audit trigger (migration 0007) reads this
# to attribute every INSERT/UPDATE/DELETE on audited tables.
#
# Doing this on `after_begin` instead of at session-open avoids a DB hit
# for routes that fail dependency resolution (e.g., 403 role gates, 422
# Pydantic validation) before any SQL runs — keeps validation tests fast
# and avoids asyncpg cross-loop cleanup issues in pytest-asyncio.
@event.listens_for(SyncSession, "after_begin")
def _set_audit_upn(_session: SyncSession, _transaction, connection) -> None:
    upn = current_upn.get()
    connection.execute(
        text("SELECT set_config('audit.upn', :upn, false)"),
        {"upn": upn},
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession. Audit attribution wired via the `after_begin`
    event listener above — fires the moment a real transaction starts."""
    async with SessionLocal() as session:
        yield session


DBDep = Annotated[AsyncSession, Depends(get_db)]


# ---------- Current user ----------


class CurrentUser(BaseModel):
    upn: str
    roles: set[str]
    comp_viewer: bool


VALID_DEV_ROLES = {
    "admin",
    "exec",
    "owner_ops",
    "owner_finance",
    "owner_clinical",
    "owner_hr",
}


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """Resolve the current user. Three paths, in priority order:

    1. **Real Entra JWT** — if `Authorization: Bearer <jwt>` AND Entra is
       configured (tenant_id + api_client_id), verify against the tenant
       JWKS and map group claims → roles.
    2. **Dev stub** — if `ENV=dev` and `Authorization: Dev <role>`, return
       a synthetic user with that single role.
    3. **Dev default** — if `ENV=dev` and no header, return an admin
       (convenience for browser-based local poking).

    In prod with Entra unconfigured, requests without a valid JWT 401 out.
    """
    # ---- Path 1: Real JWT (preferred when Entra is configured) ----
    if (
        authorization
        and authorization.startswith("Bearer ")
        and settings.entra_configured
    ):
        # Local import keeps the verifier optional for tests that don't need it
        from .services.entra_jwt import (
            extract_roles,
            extract_upn,
            verify_access_token,
        )

        token = authorization.removeprefix("Bearer ").strip()
        claims = await verify_access_token(token)
        upn = extract_upn(claims)
        roles = extract_roles(claims)
        return CurrentUser(
            upn=upn,
            roles=roles,
            comp_viewer="comp_viewer" in roles,
        )

    # ---- Path 2: Dev stub (only outside prod) ----
    if settings.env == "dev" and authorization and authorization.startswith("Dev "):
        role = authorization.removeprefix("Dev ").strip()
        if role not in VALID_DEV_ROLES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Invalid dev role '{role}'. Valid: {sorted(VALID_DEV_ROLES)}",
            )
        return CurrentUser(
            upn=f"dev-{role}@local",
            roles={role},
            comp_viewer=(role == "admin"),
        )

    # ---- Path 3: Dev default ----
    if settings.env == "dev":
        return CurrentUser(upn="dev-default@local", roles={"admin"}, comp_viewer=True)

    # Prod / non-dev with no valid token
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")


UserDep = Annotated[CurrentUser, Depends(get_current_user)]


# ---------- Role guards ----------


def require_role(*allowed: str):
    """Dependency factory for role gating. Usage: `user: CurrentUser = Depends(require_role('admin'))`."""

    async def checker(user: UserDep) -> CurrentUser:
        if not user.roles & set(allowed):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Requires one of roles: {', '.join(allowed)}",
            )
        return user

    return checker


async def require_comp_viewer(user: UserDep) -> CurrentUser:
    """Gate for comp-sensitive endpoints (CEO, CFO only, plus admin)."""
    if not user.comp_viewer:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Requires comp_viewer privilege (CEO/CFO)",
        )
    return user
