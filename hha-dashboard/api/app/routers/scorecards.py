from __future__ import annotations

from fastapi import APIRouter

from ..deps import UserDep
from ..schemas.scorecards import ScorecardOut
from ..services import fake_data

router = APIRouter(prefix="/api/v1/scorecards", tags=["scorecards"])


@router.get("", response_model=list[ScorecardOut])
async def list_scorecards(user: UserDep) -> list[dict]:
    """Exec-visible scorecard list. Doctors never see themselves.

    The qualitative `mgma_band` is visible to anyone authenticated. The
    dollar-amount comp fields (`effective_comp_usd`, `fmv_source_note`)
    are only populated for callers with the `comp_viewer` role
    (CEO, CFO, admin); for everyone else those fields are null and the
    UI redacts them.
    """
    return fake_data.get_scorecards(include_comp_detail=user.comp_viewer)
