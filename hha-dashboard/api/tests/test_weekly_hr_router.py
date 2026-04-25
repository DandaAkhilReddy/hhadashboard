"""Weekly-HR router — role gates + Pydantic validation."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _last_sunday() -> str:
    today = date.today()
    return (today - timedelta(days=(today.weekday() + 1) % 7)).isoformat()


def _payload(**overrides) -> dict:
    base = {
        "week_ending": _last_sunday(),
        "headcount_w2": 48,
        "headcount_1099": 23,
        "open_positions_total": 12,
        "terminations_90d_count": 6,
        "below_fmv_count": 61,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_post_rejects_non_owner_role() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/weekly-hr",
            headers={"Authorization": "Dev owner_finance"},
            json=_payload(),
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_get_rejects_non_owner_role() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/v1/entries/weekly-hr",
            headers={"Authorization": "Dev owner_clinical"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_post_rejects_non_sunday_week_ending() -> None:
    today = date.today()
    monday = today - timedelta(days=(today.weekday()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/weekly-hr",
            headers={"Authorization": "Dev owner_hr"},
            json=_payload(week_ending=monday.isoformat()),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_far_future_week() -> None:
    far_future = (date.today() + timedelta(days=30)).isoformat()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/weekly-hr",
            headers={"Authorization": "Dev owner_hr"},
            json=_payload(week_ending=far_future),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_negative_headcount() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/weekly-hr",
            headers={"Authorization": "Dev owner_hr"},
            json=_payload(headcount_w2=-1),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_excessive_headcount() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/weekly-hr",
            headers={"Authorization": "Dev owner_hr"},
            json=_payload(headcount_1099=99999),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_negative_terminations() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/weekly-hr",
            headers={"Authorization": "Dev owner_hr"},
            json=_payload(terminations_90d_count=-1),
        )
    assert r.status_code == 422
