"""FastAPI dependencies: DB session, current user (Entra MSAL in prod, dev stub now).

Dev mode (ENV=dev): accepts `Authorization: Dev <role>` header to simulate a user.
Prod: verifies Entra ID JWT via jwks metadata (wired in Session 2).
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .settings import settings

engine = create_async_engine(settings.database_url, echo=False, future=True, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
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
