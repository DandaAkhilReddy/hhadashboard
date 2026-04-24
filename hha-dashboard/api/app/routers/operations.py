from fastapi import APIRouter

from ..deps import DBDep, UserDep
from ..schemas.operations import OperationsSummary, SiteToday
from ..services import fake_data

router = APIRouter(prefix="/api/v1/operations", tags=["operations"])


@router.get("/summary", response_model=OperationsSummary)
async def operations_summary(db: DBDep, user: UserDep) -> dict:
    _ = user
    return await fake_data.get_operations_summary(db)


@router.get("/sites-today", response_model=list[SiteToday])
async def sites_today(db: DBDep, user: UserDep) -> list[dict]:
    _ = user
    return await fake_data.get_sites_today(db)
