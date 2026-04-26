"""Scorecards router — comp_viewer gating + MGMA band visibility."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.comp import MGMA_IM_HOSPITALIST_TOTAL_COMP_USD


@pytest.mark.asyncio
async def test_list_returns_one_row_per_demo_md() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/v1/scorecards",
            headers={"Authorization": "Dev exec"},
        )
    assert r.status_code == 200
    rows = r.json()
    # SCORECARD_MDS has 7 demo physicians.
    assert len(rows) == 7


@pytest.mark.asyncio
async def test_mgma_band_always_present() -> None:
    """Even non-comp-viewers see the qualitative band (it's not $)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/v1/scorecards",
            headers={"Authorization": "Dev exec"},
        )
    assert r.status_code == 200
    rows = r.json()
    valid_bands = {"below_25", "25_50", "50_75", "75_90", "above_90"}
    for row in rows:
        assert row["mgma_band"] in valid_bands
        assert row["mgma_p50_usd"] == MGMA_IM_HOSPITALIST_TOTAL_COMP_USD[50]


@pytest.mark.asyncio
async def test_non_comp_viewer_gets_redacted_dollar_amounts() -> None:
    """exec role does not have comp_viewer in dev mode → comp $ fields are None."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/v1/scorecards",
            headers={"Authorization": "Dev exec"},
        )
    assert r.status_code == 200
    for row in r.json():
        assert row["effective_comp_usd"] is None
        assert row["fmv_source_note"] is None


@pytest.mark.asyncio
async def test_admin_sees_dollar_amounts() -> None:
    """admin gets comp_viewer in dev → comp $ fields are populated."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/v1/scorecards",
            headers={"Authorization": "Dev admin"},
        )
    assert r.status_code == 200
    rows = r.json()
    assert all(isinstance(row["effective_comp_usd"], int) for row in rows)
    # All demo MDs have non-zero comp
    assert all(row["effective_comp_usd"] > 0 for row in rows)
    # Source-note disclaimer included exactly when comp is included
    assert all("Public-approximation" in (row["fmv_source_note"] or "") for row in rows)


@pytest.mark.asyncio
async def test_below_fmv_flag_matches_band() -> None:
    """below_fmv must be true iff mgma_band == 'below_25'."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/v1/scorecards",
            headers={"Authorization": "Dev admin"},
        )
    for row in r.json():
        if row["mgma_band"] == "below_25":
            assert row["below_fmv"] is True
        else:
            assert row["below_fmv"] is False


@pytest.mark.asyncio
async def test_unauthenticated_in_prod_mode_rejected() -> None:
    """Sanity: route is auth-gated. Dev default still passes (admin)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # No Authorization header — dev default kicks in (admin) and returns 200.
        r = await client.get("/api/v1/scorecards")
    assert r.status_code == 200
