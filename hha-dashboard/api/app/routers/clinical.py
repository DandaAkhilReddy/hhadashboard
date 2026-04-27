from typing import Any

from fastapi import APIRouter

from ..deps import DBDep, UserDep
from ..schemas.clinical import ClinicalSummary, CredentialExpiring
from ..services import fake_data

router = APIRouter(prefix="/api/v1/clinical", tags=["clinical"])


@router.get("/summary", response_model=ClinicalSummary)
async def clinical_summary(db: DBDep, user: UserDep) -> dict[str, Any]:
    _ = user
    return await fake_data.get_clinical_summary(db)


@router.get("/credentials-expiring", response_model=list[CredentialExpiring])
async def credentials_expiring(user: UserDep) -> list[dict[str, Any]]:
    _ = user
    return fake_data.get_credentials_expiring()
