"""Pydantic schemas for the census-only portal."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator


class LoginIn(BaseModel):
    """Email + password from the portal login form."""

    email: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=1, max_length=200)


class PortalSiteOut(BaseModel):
    """One facility row, prefilled with today's existing census (or null)."""

    site_id: int
    site_name: str
    state: str
    census: int | None
    open_shifts: int


class PortalLoginOut(BaseModel):
    """Login success — returns the prefill list so the form can render
    immediately without a second round-trip."""

    entry_date: date
    sites: list[PortalSiteOut]


class PortalCensusRow(BaseModel):
    """One row of the bulk save."""

    site_id: int
    census: int = Field(..., ge=0, le=2000)
    open_shifts: int = Field(default=0, ge=0, le=50)


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
    """One persisted row, mirrored back to the client."""

    site_id: int
    site_name: str
    state: str
    entry_date: date
    census: int
    open_shifts: int
    source: str
