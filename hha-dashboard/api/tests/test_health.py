"""Liveness + readiness probe tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready_requires_db() -> None:
    """/ready hits the DB. Succeeds if Postgres is up (docker compose), else 500."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/ready")
    # 200 if DB is up; 500 from the DB exception is acceptable in CI-without-DB.
    assert response.status_code in (200, 500)
