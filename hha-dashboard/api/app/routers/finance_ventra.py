"""Read endpoints for the Ventra pre-aggregated fact tables.

Three GET endpoints under ``/api/v1/finance`` — distinct from the
existing ``finance.py`` (legacy ``monthly_finance_manual`` shape).
RBAC-gated to ``owner_finance`` / ``admin`` / ``exec`` per ADR-002.

The dashboard tiles for the Finance board hit these three endpoints
after Phase 1B lands. The frontend never touches the fact tables
directly; all reads go through here so RBAC + filtering + future
audit-of-reads stays centralized.

No writes. Writes happen exclusively through ``jobs/ventra_ingest`` —
this router is intentionally read-only.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select

from ..deps import DBDep, require_role
from ..models.entries_ventra import (
    FactArSnapshot,
    FactCollectionsDaily,
    FactRevenueByPhysicianMo,
)
from ..schemas.ventra_facts import (
    ArSnapshotRowOut,
    CollectionsRowOut,
    Envelope,
    PhysicianMonthlyRowOut,
)

# Roles that can read the fact tables.
_READ_ROLES = ("owner_finance", "admin", "exec")

# Hard upper bound on a single response. Pre-aggregated daily rows are
# tiny (5 facilities * 5 payer_classes = 25 rows/day) so this only kicks
# in for multi-month range queries — fine to cap.
_MAX_ROWS = 5000

router = APIRouter(
    prefix="/api/v1/finance",
    tags=["finance-ventra"],
    dependencies=[Depends(require_role(*_READ_ROLES))],
)


@router.get(
    "/daily-collections",
    response_model=Envelope[CollectionsRowOut],
    status_code=status.HTTP_200_OK,
    summary="List fact_collections_daily rows in a date range",
)
async def list_daily_collections(
    db: DBDep,
    date_from: Annotated[date, Query(description="Inclusive lower bound on date.")],
    date_to: Annotated[date, Query(description="Inclusive upper bound on date.")],
    facility_no: Annotated[
        int | None,
        Query(description="Optional facility filter; omit for all FL sites."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=_MAX_ROWS, description="Max rows; capped at 5000."),
    ] = 1000,
) -> Envelope[CollectionsRowOut]:
    """Daily collections by (date, facility_no, payer_class) — read path
    for the Finance board's collections tile.

    Date range is inclusive on both ends. Results are ordered by
    (date DESC, facility_no, payer_class) so the most recent days
    surface first in the dashboard fetch."""
    stmt = (
        select(FactCollectionsDaily)
        .where(FactCollectionsDaily.date >= date_from)
        .where(FactCollectionsDaily.date <= date_to)
        .order_by(
            FactCollectionsDaily.date.desc(),
            FactCollectionsDaily.facility_no,
            FactCollectionsDaily.payer_class,
        )
        .limit(limit)
    )
    if facility_no is not None:
        stmt = stmt.where(FactCollectionsDaily.facility_no == facility_no)

    rows = (await db.execute(stmt)).scalars().all()
    return Envelope(
        count=len(rows),
        rows=[CollectionsRowOut.model_validate(r) for r in rows],
    )


@router.get(
    "/ar-snapshot",
    response_model=Envelope[ArSnapshotRowOut],
    status_code=status.HTTP_200_OK,
    summary="List fact_ar_snapshot rows for a single snapshot_date",
)
async def list_ar_snapshot(
    db: DBDep,
    snapshot_date: Annotated[date, Query(description="Snapshot date to load.")],
    facility_no: Annotated[
        int | None,
        Query(description="Optional facility filter; omit for all FL sites."),
    ] = None,
) -> Envelope[ArSnapshotRowOut]:
    """AR aging snapshot by (snapshot_date, facility_no, aging_bucket).

    Single-day grain — no range param. The Finance board's AR tile
    typically loads ``date.today() - 1 day`` to ride the daily-after-EOB
    timing of Ventra's snapshot job."""
    stmt = (
        select(FactArSnapshot)
        .where(FactArSnapshot.snapshot_date == snapshot_date)
        .order_by(FactArSnapshot.facility_no, FactArSnapshot.aging_bucket)
    )
    if facility_no is not None:
        stmt = stmt.where(FactArSnapshot.facility_no == facility_no)

    rows = (await db.execute(stmt)).scalars().all()
    return Envelope(
        count=len(rows),
        rows=[ArSnapshotRowOut.model_validate(r) for r in rows],
    )


@router.get(
    "/physician-monthly",
    response_model=Envelope[PhysicianMonthlyRowOut],
    status_code=status.HTTP_200_OK,
    summary="List fact_revenue_by_physician_mo rows for a month",
)
async def list_physician_monthly(
    db: DBDep,
    month: Annotated[
        date,
        Query(
            description="First-of-month date. Sub-month days are silently truncated by the DB CHECK upstream."
        ),
    ],
    facility_no: Annotated[
        int | None,
        Query(description="Optional facility filter; omit for all FL sites."),
    ] = None,
    npi: Annotated[
        str | None,
        Query(
            description="Optional 10-digit NPI filter; omit for all physicians.",
            pattern=r"^[0-9]{10}$",
        ),
    ] = None,
) -> Envelope[PhysicianMonthlyRowOut]:
    """Per-physician revenue / RVU for a single month.

    Doctor Scorecards consume this — paired with the
    ``masters.physicians`` directory on the frontend for name resolution
    (kept out of this endpoint by design; comp data lives in a different
    role-gated path)."""
    stmt = (
        select(FactRevenueByPhysicianMo)
        .where(FactRevenueByPhysicianMo.month == month)
        .order_by(
            FactRevenueByPhysicianMo.facility_no,
            FactRevenueByPhysicianMo.physician_npi,
        )
    )
    if facility_no is not None:
        stmt = stmt.where(FactRevenueByPhysicianMo.facility_no == facility_no)
    if npi is not None:
        stmt = stmt.where(FactRevenueByPhysicianMo.physician_npi == npi)

    rows = (await db.execute(stmt)).scalars().all()
    return Envelope(
        count=len(rows),
        rows=[PhysicianMonthlyRowOut.model_validate(r) for r in rows],
    )
