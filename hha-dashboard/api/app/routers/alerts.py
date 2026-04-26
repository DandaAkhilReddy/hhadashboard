"""Alerts read API.

`GET /api/v1/alerts` calls `services.alert_engine.compute_alerts_for_date`
against today's date. If the result is empty (genuine quiet day OR empty
DB), falls back to `fake_data.get_current_alerts()` so the dashboard's
`<AlertBanner>` doesn't go dark in dev / pre-seed environments.

Same response shape as before — frontend code is untouched.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from ..deps import DBDep, UserDep
from ..schemas.alerts import Alert, Meta
from ..services import alert_engine, fake_data

router = APIRouter(prefix="/api/v1", tags=["alerts"])


@router.get("/alerts", response_model=list[Alert])
async def current_alerts(db: DBDep, user: UserDep) -> list[dict]:
    _ = user
    today = datetime.now(UTC).date()
    candidates = await alert_engine.compute_alerts_for_date(db, today)
    if candidates:
        return [c.as_dict() for c in candidates]
    # Fallback: empty engine result → render fake alerts so dev / pre-seed
    # dashboards still show something. Once data lands, fakes silently disappear.
    return fake_data.get_current_alerts()


@router.get("/meta", response_model=Meta)
async def meta() -> dict:
    """Data-source + freshness info (no auth required)."""
    return fake_data.get_meta()
