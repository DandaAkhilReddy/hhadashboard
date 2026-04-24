from typing import Annotated

from fastapi import APIRouter, Depends

from ..deps import CurrentUser, UserDep, require_comp_viewer
from ..schemas.scorecards import ScorecardOut
from ..services import fake_data

router = APIRouter(prefix="/api/v1/scorecards", tags=["scorecards"])

CompViewerDep = Annotated[CurrentUser, Depends(require_comp_viewer)]


@router.get("", response_model=list[ScorecardOut])
async def list_scorecards(user: UserDep) -> list[dict]:
    """Exec-visible scorecard list. Doctors never see themselves.

    comp_viewer gate is applied per-endpoint; this list endpoint is
    open to any authenticated role (names are directory info, not comp $).
    Comp detail endpoints get the stricter gate.
    """
    _ = user
    return fake_data.get_scorecards()


# Example of the stricter comp gate — used for endpoints that surface comp $ detail.
# In Session 5 (full Overall Rank + comp), mount on /{id}/comp.
@router.get("/_comp_gate_demo")
async def comp_gate_demo(user: CompViewerDep) -> dict:
    return {"you_can_see_comp": True, "upn": user.upn}
