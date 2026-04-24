from fastapi import APIRouter

from ..deps import UserDep
from ..schemas.alerts import Alert, Meta
from ..services import fake_data

router = APIRouter(prefix="/api/v1", tags=["alerts"])


@router.get("/alerts", response_model=list[Alert])
async def current_alerts(user: UserDep) -> list[dict]:
    _ = user
    return fake_data.get_current_alerts()


@router.get("/meta", response_model=Meta)
async def meta() -> dict:
    """Data-source + freshness info (no auth required)."""
    return fake_data.get_meta()
