from fastapi import APIRouter

from ..deps import UserDep
from ..schemas.operations import OperationsSummary, SiteToday
from ..services import fake_data

router = APIRouter(prefix="/api/v1/operations", tags=["operations"])


@router.get("/summary", response_model=OperationsSummary)
async def operations_summary(user: UserDep) -> dict:
    _ = user
    return fake_data.get_operations_summary()


@router.get("/sites-today", response_model=list[SiteToday])
async def sites_today(user: UserDep) -> list[dict]:
    _ = user
    return fake_data.get_sites_today()
