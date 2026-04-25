"""Entries router — validation + role-gate tests.

These all exercise 4xx paths that reject before any DB write, so they run
without Docker. The Postgres-dependent paths (happy-path upsert, ops-board
read-prefers-DB, PDF extractor upsert) are covered in their own files.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _batch(**overrides) -> dict:
    base: dict = {
        "entry_date": date.today().isoformat(),
        "rows": [{"site_id": 1, "census": 100, "open_shifts": 0}],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_post_rejects_non_owner_role() -> None:
    """owner_finance is authenticated but not allowed to write census."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/daily-census",
            headers={"Authorization": "Dev owner_finance"},
            json=_batch(),
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_get_rejects_non_owner_role() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/v1/entries/daily-census",
            headers={"Authorization": "Dev owner_clinical"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_post_rejects_negative_census() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/daily-census",
            headers={"Authorization": "Dev owner_ops"},
            json=_batch(rows=[{"site_id": 1, "census": -1}]),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_census_over_cap() -> None:
    """CENSUS_MAX = 2000 — anything above is clearly bogus for our 11-site book."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/daily-census",
            headers={"Authorization": "Dev owner_ops"},
            json=_batch(rows=[{"site_id": 1, "census": 2001}]),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_future_date() -> None:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/daily-census",
            headers={"Authorization": "Dev owner_ops"},
            json=_batch(entry_date=tomorrow),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_empty_rows() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/daily-census",
            headers={"Authorization": "Dev owner_ops"},
            json=_batch(rows=[]),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_site_id_zero() -> None:
    """site_id has gt=0 — FK would reject anyway but we catch earlier."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/daily-census",
            headers={"Authorization": "Dev owner_ops"},
            json=_batch(rows=[{"site_id": 0, "census": 10}]),
        )
    assert r.status_code == 422
