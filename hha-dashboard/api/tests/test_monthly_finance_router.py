"""Monthly-finance router — role gates + Pydantic validation.

These tests reject before the DB layer (4xx paths), so they don't need the
Postgres container. The happy-path upsert is covered by the e2e checklist.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _row(**overrides) -> dict:
    base = {
        "state": "FL",
        "collections_usd": "2280000",
        "ventra_fee_usd": "114000",
        "ar_total_usd": "5600000",
        "ar_0_30_usd": "1568000",
        "ar_31_60_usd": "1120000",
        "ar_61_90_usd": "784000",
        "ar_91_120_usd": "728000",
        "ar_over_120_usd": "1400000",
        "net_collection_rate_pct": "43",
        "days_in_ar": "39.9",
    }
    base.update(overrides)
    return base


def _batch(**overrides) -> dict:
    base: dict = {"year": 2026, "month": 3, "rows": [_row()]}
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_post_rejects_non_owner_role() -> None:
    """owner_ops is authenticated but not in the finance owner group."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/monthly-finance",
            headers={"Authorization": "Dev owner_ops"},
            json=_batch(),
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_get_rejects_non_owner_role() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/v1/entries/monthly-finance",
            headers={"Authorization": "Dev owner_clinical"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_post_rejects_negative_collections() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/monthly-finance",
            headers={"Authorization": "Dev owner_finance"},
            json=_batch(rows=[_row(collections_usd="-1")]),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_ncr_over_100() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/monthly-finance",
            headers={"Authorization": "Dev owner_finance"},
            json=_batch(rows=[_row(net_collection_rate_pct="150")]),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_invalid_month() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/monthly-finance",
            headers={"Authorization": "Dev owner_finance"},
            json=_batch(month=13),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_future_month() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/monthly-finance",
            headers={"Authorization": "Dev owner_finance"},
            json=_batch(year=2099, month=1),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_duplicate_state_in_batch() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/monthly-finance",
            headers={"Authorization": "Dev owner_finance"},
            json=_batch(rows=[_row(state="FL"), _row(state="FL")]),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_invalid_state() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/monthly-finance",
            headers={"Authorization": "Dev owner_finance"},
            json=_batch(rows=[_row(state="CA")]),
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_empty_rows() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/entries/monthly-finance",
            headers={"Authorization": "Dev owner_finance"},
            json=_batch(rows=[]),
        )
    assert r.status_code == 422
