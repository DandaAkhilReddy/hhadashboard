from typing import Any

from fastapi import APIRouter

from ..deps import DBDep, UserDep
from ..schemas.people import OpenPositionBySite, PeopleSummary
from ..services import fake_data

router = APIRouter(prefix="/api/v1/people", tags=["people"])


@router.get("/summary", response_model=PeopleSummary)
async def people_summary(db: DBDep, user: UserDep) -> dict[str, Any]:
    _ = user
    return await fake_data.get_people_summary(db)


@router.get("/open-positions-by-site", response_model=list[OpenPositionBySite])
async def open_positions_by_site(user: UserDep) -> list[dict[str, Any]]:
    _ = user
    return fake_data.get_open_positions_by_site()
