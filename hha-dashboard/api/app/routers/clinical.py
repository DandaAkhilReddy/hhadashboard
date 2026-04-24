from fastapi import APIRouter

from ..deps import UserDep
from ..schemas.clinical import ClinicalSummary, CredentialExpiring
from ..services import fake_data

router = APIRouter(prefix="/api/v1/clinical", tags=["clinical"])


@router.get("/summary", response_model=ClinicalSummary)
async def clinical_summary(user: UserDep) -> dict:
    _ = user
    return fake_data.get_clinical_summary()


@router.get("/credentials-expiring", response_model=list[CredentialExpiring])
async def credentials_expiring(user: UserDep) -> list[dict]:
    _ = user
    return fake_data.get_credentials_expiring()
