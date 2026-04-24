from fastapi import APIRouter
from sqlalchemy import select

from ..deps import DBDep, UserDep
from ..models.masters import Site
from ..schemas.sites import SiteOut

router = APIRouter(prefix="/api/v1/sites", tags=["sites"])


@router.get("", response_model=list[SiteOut])
async def list_sites(db: DBDep, user: UserDep) -> list[Site]:
    """List all sites. Any authenticated role can read."""
    _ = user  # authenticated-only gate; role filtering not needed for directory reads
    result = await db.execute(select(Site).order_by(Site.state, Site.name))
    return list(result.scalars().all())
