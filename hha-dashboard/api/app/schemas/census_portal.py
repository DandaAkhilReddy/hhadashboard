"""Pydantic schemas for the census-only portal."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


class LoginIn(BaseModel):
    """Email + password from the portal login form."""

    email: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=1, max_length=200)


class PortalSiteOut(BaseModel):
    """One facility row, prefilled with today's existing census (or null).

    `entered_at` carries the row's last-saved timestamp (DailyEntry.updated_at)
    so the portal UI can render an already-entered row in the locked
    "✓ <value> · entered <HH:MM> · [Edit]" state instead of an empty input.
    None for rows the user hasn't touched today.
    """

    site_id: int
    site_name: str
    state: str
    census: int | None
    open_shifts: int
    entered_at: datetime | None


class PortalLoginOut(BaseModel):
    """Login success — returns the prefill list so the form can render
    immediately without a second round-trip."""

    entry_date: date
    sites: list[PortalSiteOut]


class PortalCensusRow(BaseModel):
    """One row of the bulk save.

    Phase 1 collects ONLY `(site_id, census)` from the portal. The DB column
    `open_shifts` (NOT NULL DEFAULT 0 on `entries.daily_entries`) stays in
    the table for compatibility with the dashboard owner-form; the portal
    does not write it. The router defaults it to 0 on insert, leaves it
    unchanged on update. See `docs/PHASE_1_CENSUS_PORTAL.md` for the
    Phase 1 field whitelist.
    """

    site_id: int
    census: int = Field(..., ge=0, le=2000)


class PortalCensusBatchIn(BaseModel):
    """Whole-page save: today's count for all 11 sites in one POST."""

    entry_date: date
    rows: list[PortalCensusRow] = Field(..., min_length=1, max_length=50)

    @field_validator("entry_date")
    @classmethod
    def _no_future_dates(cls, v: date) -> date:
        from datetime import UTC, datetime

        if v > datetime.now(UTC).date():
            msg = "entry_date cannot be in the future"
            raise ValueError(msg)
        return v


class PortalCensusOut(BaseModel):
    """One persisted row, mirrored back to the client.

    `entered_at` is always populated (the row was just saved), so the
    frontend can flip the row back to its locked "Edit"-state without
    a follow-up GET.
    """

    site_id: int
    site_name: str
    state: str
    entry_date: date
    census: int
    open_shifts: int
    source: str
    entered_at: datetime


class PortalSummaryOut(BaseModel):
    """Aggregate summary cards for the portal entry page.

    Phase 1: total / reported / missing / last_updated_at, scoped to the
    requested `entry_date`. Read-only; portal cannot pivot this into any
    other operational data.
    """

    entry_date: date
    total_census: int
    facilities_reported: int
    facilities_missing: int
    last_updated_at: datetime | None


class PortalSessionOut(BaseModel):
    """Lightweight session-check response.

    The `cookie required` dependency 401s on missing/invalid; this endpoint
    returns 200 + the portal email so the UI can verify a session without
    fetching the full /sites payload.
    """

    email: str
