"""Weekly-clinical router — role gates + Pydantic validation."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _last_sunday() -> str:
    today = date.today()
    return (today - timedelta(days=(today.weekday() + 1) % 7)).isoformat()


def _row(**overrides) -> dict:
    base = {
        "state": "FL",
        "hp_24h_pct": "94.5",
        "dc_48h_pct": "88.0",
        "avg_los_days": "4.2",
        "charts_audited_count": 50,
    }
    base.update(overrides)
    return base


def _batch(**overrides) -> dict:
    base: dict = {"week_ending": _last_sunday(), "rows": [_row()]}
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_post_rejects_non_owner_role() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/weekly-clinical",
            headers={"Authorization": "Dev owner_finance"},
            json=_batch(),
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_get_rejects_non_owner_role() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/v1/entries/weekly-clinical",
            headers={"Authorization": "Dev owner_ops"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_post_rejects_non_sunday_week_ending() -> None:
    """Pick a Monday (any non-Sunday)."""
    today = date.today()
    monday = today - timedelta(days=(today.weekday()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/weekly-clinical",
            headers={"Authorization": "Dev owner_clinical"},
            json=_batch(week_ending=monday.isoformat()),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_far_future_week() -> None:
    far_future = (date.today() + timedelta(days=30)).isoformat()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/weekly-clinical",
            headers={"Authorization": "Dev owner_clinical"},
            json=_batch(week_ending=far_future),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_hp_pct_over_100() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/weekly-clinical",
            headers={"Authorization": "Dev owner_clinical"},
            json=_batch(rows=[_row(hp_24h_pct="120")]),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_negative_los() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/weekly-clinical",
            headers={"Authorization": "Dev owner_clinical"},
            json=_batch(rows=[_row(avg_los_days="-1")]),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_los_over_cap() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/weekly-clinical",
            headers={"Authorization": "Dev owner_clinical"},
            json=_batch(rows=[_row(avg_los_days="100")]),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_duplicate_state() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/weekly-clinical",
            headers={"Authorization": "Dev owner_clinical"},
            json=_batch(rows=[_row(state="FL"), _row(state="FL")]),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_invalid_state() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/weekly-clinical",
            headers={"Authorization": "Dev owner_clinical"},
            json=_batch(rows=[_row(state="CA")]),
        )
    assert r.status_code == 422
