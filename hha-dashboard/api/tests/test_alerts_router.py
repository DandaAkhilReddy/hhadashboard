"""GET /api/v1/alerts — wired to alert_engine with fake-data fallback.

Pure-validation tests run without Postgres (the dev-default user resolution
in deps.py + the engine's empty-DB → empty list path lets the fallback fire).

Skipped variance-row test runs against Postgres when reachable.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text

from app.deps import SessionLocal
from app.main import app
from app.models.entries_finance import MonthlyFinanceManual

pytestmark = pytest.mark.asyncio


async def test_alerts_endpoint_returns_a_list() -> None:
    """The endpoint always returns a non-empty list (engine result OR fake fallback)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/v1/alerts")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) > 0
    # Shape check
    first = body[0]
    for key in ("id", "severity", "category", "title", "detail", "owner"):
        assert key in first


async def _can_connect_to_postgres() -> bool:
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def test_alerts_endpoint_returns_engine_alerts_when_data_exists() -> None:
    """With seeded variance, the engine produces alerts AND the fake list is
    skipped — verify the real engine path is being exercised."""
    if not await _can_connect_to_postgres():
        pytest.skip("Postgres not reachable — skipping engine-path alert test")

    today = datetime.now(UTC).date()

    async with SessionLocal() as session:
        await session.execute(delete(MonthlyFinanceManual))
        # Seed a row that crosses the FL collections-below-target rule
        # for THIS month (so the engine sees it as the latest)
        session.add(
            MonthlyFinanceManual(
                year=today.year,
                month=today.month,
                period_first=date(today.year, today.month, 1),
                state="FL",
                collections_usd=Decimal("100"),
                ventra_fee_usd=Decimal("5"),
                ar_total_usd=Decimal("500"),
                ar_0_30_usd=Decimal("200"),
                ar_31_60_usd=Decimal("100"),
                ar_61_90_usd=Decimal("75"),
                ar_91_120_usd=Decimal("75"),
                ar_over_120_usd=Decimal("50"),
                net_collection_rate_pct=Decimal("95"),
                days_in_ar=Decimal("40"),
                source_system="VENTRA_FL_FALLBACK",
                entered_by_upn="test@example.com",
            )
        )
        await session.commit()

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/alerts")
        assert r.status_code == 200
        body = r.json()
        engine_alert_ids = [a["id"] for a in body]
        # Engine-generated id starts with the state prefix
        assert any(
            "fl-collections-below-target" in aid for aid in engine_alert_ids
        ), f"Expected engine alert in body, got: {engine_alert_ids}"
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(MonthlyFinanceManual))
            await session.commit()
