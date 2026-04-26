"""Census-only entry portal — separate auth surface, write-only API.

This router is reachable from `/api/v1/census-portal/*` and gated by the
`census_session` cookie issued by `/login`. It is INTENTIONALLY decoupled
from the Entra-gated dashboard:

- No `Depends(require_role)` (no Entra roles involved).
- No GETs for any operational data — the portal cannot read scorecards,
  finance, etc. Whoever is logged into the portal cannot pivot it into a
  viewer surface.
- All mutations record `entered_by_upn = 'census-portal@hhamedicine.com'`
  and `source = 'manual_portal'` so audit reviewers can distinguish
  portal-origin entries from in-dashboard owner-form entries.

See plan section "Slice A — Census-only entry portal" and Standing Fact F2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..deps import DBDep
from ..models.census_credentials import CensusCredential
from ..models.entries import DailyEntry
from ..models.masters import Site
from ..schemas.census_portal import (
    LoginIn,
    PortalCensusBatchIn,
    PortalCensusOut,
    PortalLoginOut,
    PortalSiteOut,
)
from ..services import audit as audit_service
from ..services import census_auth

router = APIRouter(prefix="/api/v1/census-portal", tags=["census-portal"])

PORTAL_UPN = "census-portal@hhamedicine.com"
PORTAL_SOURCE = "manual_portal"

# Cookie attributes — adjust the path so the cookie is only sent to the
# portal endpoints. The dashboard's `hha_session` cookie has a different
# path, so the two never collide.
COOKIE_NAME = "census_session"
COOKIE_PATH = "/"  # browser won't send to dashboard fetches because the dashboard uses Authorization headers


async def census_session_required(
    db: DBDep,
    census_session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> CensusCredential:
    """Cookie-backed dependency. Validates the session token against the
    `auth.census_credentials` row. Sets the audit UPN for the request."""
    if not census_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    cred = await census_auth.validate_session(db, census_session)
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid")
    audit_service.set_current_upn(PORTAL_UPN)
    return cred


CredentialDep = Annotated[CensusCredential, Depends(census_session_required)]


@router.post("/login", response_model=PortalLoginOut)
async def login(
    db: DBDep,
    response: Response,
    payload: LoginIn,
) -> PortalLoginOut:
    """Verify credentials, issue a fresh session token, set the cookie.

    Single-session lock: the new token overwrites any prior token, so a
    second simultaneous login boots the first browser on its next request.
    """
    try:
        cred = await census_auth.verify_credentials(db, payload.email, payload.password)
    except census_auth.AccountLocked as e:
        await db.commit()  # persist the lock-state update
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"Too many failed attempts. Try again after {e.locked_until.isoformat()}.",
        ) from None
    except census_auth.InvalidCredentials:
        await db.commit()  # persist the failed_attempts increment if any
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password") from None

    token = await census_auth.issue_session(db, cred)
    await db.commit()

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        path=COOKIE_PATH,
        max_age=int(census_auth.SESSION_DURATION.total_seconds()),
    )

    sites = (await db.execute(select(Site).order_by(Site.name))).scalars().all()
    today = datetime.now(UTC).date()
    existing = (
        await db.execute(
            select(DailyEntry).where(DailyEntry.entry_date == today)
        )
    ).scalars().all()
    by_site = {e.site_id: e for e in existing}

    return PortalLoginOut(
        entry_date=today,
        sites=[
            PortalSiteOut(
                site_id=s.id,
                site_name=s.name,
                state=s.state,
                census=by_site[s.id].census if s.id in by_site else None,
                open_shifts=by_site[s.id].open_shifts if s.id in by_site else 0,
            )
            for s in sites
        ],
    )


@router.get("/sites", response_model=PortalLoginOut)
async def list_sites_with_today(
    db: DBDep,
    cred: CredentialDep,
) -> PortalLoginOut:
    """Return the same prefill payload as /login so the entry page can render
    after a refresh without re-authenticating.

    Returns ONLY facility names + today's already-entered numbers. No
    operational data (no scorecards, finance, clinical, etc.) — keeps the
    portal's read surface narrow and predictable.
    """
    _ = cred
    sites = (await db.execute(select(Site).order_by(Site.name))).scalars().all()
    today = datetime.now(UTC).date()
    existing = (
        await db.execute(select(DailyEntry).where(DailyEntry.entry_date == today))
    ).scalars().all()
    by_site = {e.site_id: e for e in existing}
    return PortalLoginOut(
        entry_date=today,
        sites=[
            PortalSiteOut(
                site_id=s.id,
                site_name=s.name,
                state=s.state,
                census=by_site[s.id].census if s.id in by_site else None,
                open_shifts=by_site[s.id].open_shifts if s.id in by_site else 0,
            )
            for s in sites
        ],
    )


@router.post("/logout")
async def logout(
    db: DBDep,
    response: Response,
    cred: CredentialDep,
) -> dict[str, str]:
    """Clear the active session token and the cookie."""
    await census_auth.clear_session(db, cred)
    await db.commit()
    response.delete_cookie(key=COOKIE_NAME, path=COOKIE_PATH)
    return {"status": "logged_out"}


@router.post(
    "/daily-census",
    response_model=list[PortalCensusOut],
    status_code=status.HTTP_200_OK,
)
async def save_daily_census(
    db: DBDep,
    cred: CredentialDep,
    batch: PortalCensusBatchIn,
) -> list[PortalCensusOut]:
    """Bulk upsert today's census for the supplied site rows.

    Same idempotent (site_id, entry_date) upsert as the dashboard's
    /entries/daily-census endpoint — but tagged with source='manual_portal'
    and entered_by_upn='census-portal@hhamedicine.com' for audit clarity.
    """
    _ = cred  # validated by dependency; keep for explicitness

    site_ids_in_batch = {r.site_id for r in batch.rows}
    existing_ids = set(
        (await db.execute(select(Site.id).where(Site.id.in_(site_ids_in_batch)))).scalars().all()
    )
    unknown = site_ids_in_batch - existing_ids
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown site_id(s): {sorted(unknown)}",
        )

    for row in batch.rows:
        stmt = (
            pg_insert(DailyEntry)
            .values(
                site_id=row.site_id,
                entry_date=batch.entry_date,
                census=row.census,
                open_shifts=row.open_shifts,
                entered_by_upn=PORTAL_UPN,
                source=PORTAL_SOURCE,
                pdf_sha256=None,
                notes=None,
            )
            .on_conflict_do_update(
                index_elements=["site_id", "entry_date"],
                set_={
                    "census": row.census,
                    "open_shifts": row.open_shifts,
                    "entered_by_upn": PORTAL_UPN,
                    "source": PORTAL_SOURCE,
                    "updated_at": datetime.now(UTC),
                },
            )
        )
        await db.execute(stmt)
    await db.commit()

    sites = {s.id: s for s in (await db.execute(select(Site))).scalars().all()}
    saved = (
        await db.execute(
            select(DailyEntry).where(
                DailyEntry.entry_date == batch.entry_date,
                DailyEntry.site_id.in_(site_ids_in_batch),
            )
        )
    ).scalars().all()

    return [
        PortalCensusOut(
            site_id=e.site_id,
            site_name=sites[e.site_id].name,
            state=sites[e.site_id].state,
            entry_date=e.entry_date,
            census=e.census,
            open_shifts=e.open_shifts,
            source=e.source,
        )
        for e in saved
    ]
