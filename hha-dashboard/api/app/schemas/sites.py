from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    state: str
    hospital_system: str | None
    status: str
    created_at: datetime
