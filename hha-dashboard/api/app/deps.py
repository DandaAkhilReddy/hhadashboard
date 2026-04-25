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
    # Dev shortcut: Authorization: Dev <role>
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

    # Dev default — no header means "you are admin"
    if settings.env == "dev":
        return CurrentUser(upn="dev-default@local", roles={"admin"}, comp_viewer=True)

    # TODO (Session 2): verify Entra JWT, extract groups → roles, extract comp_viewer flag
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
