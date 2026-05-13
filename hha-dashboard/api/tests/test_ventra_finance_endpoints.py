"""Finance-Ventra router tests — RBAC gates + Pydantic query validation.

The 4xx-path tests run without Postgres because the role gate fires
BEFORE the DB dependency resolves. The 200-path tests use the
skip-if-no-postgres fixture pattern (matches test_audit_triggers.py)
so the suite stays green in CI without a DB.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from jobs.ventra_ingest.ingest import IngestRun, ingest_drop
from jobs.ventra_ingest.manifest import Manifest, ManifestEntry
from jobs.ventra_ingest.parsers import (
    ARSnapshotRow,
    CollectionsRow,
    PhysicianMonthlyRow,
)
from sqlalchemy import text

from app.deps import SessionLocal
from app.main import app
from app.services.audit import set_current_upn

pytestmark = pytest.mark.asyncio


# =========================================================================
# RBAC — these run without Postgres (role gate fires first)
# =========================================================================


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/finance/daily-collections?date_from=2026-06-01&date_to=2026-06-15",
        "/api/v1/finance/ar-snapshot?snapshot_date=2026-06-15",
        "/api/v1/finance/physician-monthly?month=2026-06-01",
    ],
)
@pytest.mark.parametrize(
    "role",
    ["owner_ops", "owner_clinical", "owner_hr"],
)
async def test_rejects_non_finance_roles(path: str, role: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(path, headers={"Authorization": f"Dev {role}"})
    assert r.status_code == 403


@pytest.mark.parametrize(
    "role",
    ["owner_finance", "admin", "exec"],
)
async def test_accepts_finance_roles_for_well_formed_request(role: str) -> None:
    """Finance-permitted roles must NOT 403. If Postgres is reachable
    we'll get 200; otherwise 500 (DB dependency error). Either way the
    role gate passed — which is what this test asserts."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/v1/finance/daily-collections?date_from=2026-06-01&date_to=2026-06-15",
            headers={"Authorization": f"Dev {role}"},
        )
    assert r.status_code != 403


# =========================================================================
# Pydantic query-param validation — also pre-DB
# =========================================================================


async def test_daily_collections_requires_both_date_params() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/v1/finance/daily-collections?date_from=2026-06-01",
            headers={"Authorization": "Dev owner_finance"},
        )
    assert r.status_code == 422


async def test_daily_collections_rejects_invalid_date_format() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/v1/finance/daily-collections?date_from=not-a-date&date_to=2026-06-15",
            headers={"Authorization": "Dev owner_finance"},
        )
    assert r.status_code == 422


async def test_daily_collections_rejects_limit_over_max() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/v1/finance/daily-collections?date_from=2026-06-01&date_to=2026-06-15&limit=10000",
            headers={"Authorization": "Dev owner_finance"},
        )
    assert r.status_code == 422


async def test_physician_monthly_rejects_malformed_npi() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/v1/finance/physician-monthly?month=2026-06-01&npi=abc",
            headers={"Authorization": "Dev owner_finance"},
        )
    assert r.status_code == 422


async def test_physician_monthly_accepts_well_formed_npi() -> None:
    """NPI pattern is permissive (just 10 digits); role gate passes."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/v1/finance/physician-monthly?month=2026-06-01&npi=1234567890",
            headers={"Authorization": "Dev owner_finance"},
        )
    assert r.status_code != 403
    assert r.status_code != 422


# =========================================================================
# Happy path — live Postgres only
# =========================================================================


async def _can_connect() -> bool:
    try:
        async with SessionLocal() as s:
            await s.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture
async def seeded_drop():
    """Insert one row into each fact table for a fresh test run_id.
    Cleanup deletes by run_id. Skips the test if Postgres is unreachable."""
    if not await _can_connect():
        pytest.skip("Postgres not reachable")

    upn = "test-finance-ventra-router@hha.com"
    set_current_upn(upn)
    drop = date(2026, 6, 20)
    month = date(2026, 6, 1)

    async with SessionLocal() as db:
        run = await IngestRun.start(
            db, drop_date=drop, manifest_path="ventra/2026-06-20/_MANIFEST.csv"
        )
        facility = 91000 + (run.run_id.int & 0xFF)
        manifest = Manifest(
            drop_date=drop,
            entries=[
                ManifestEntry(file_name="collections.csv", sha256="a" * 64, row_count=1),
                ManifestEntry(file_name="ar_snapshot.csv", sha256="b" * 64, row_count=1),
                ManifestEntry(file_name="physician_monthly.csv", sha256="c" * 64, row_count=1),
            ],
        )
        parsed: dict[str, list] = {
            "collections.csv": [
                CollectionsRow(
                    date=drop, facility_no=facility, payer_class="commercial",
                    gross_charges=Decimal("10000"), payments_received=Decimal("8000"),
                    contractual_adjustments=Decimal("500"), write_offs=Decimal("200"),
                    payer_refunds=Decimal("0"), patient_refunds=Decimal("0"),
                    net_revenue=Decimal("7300"), source_system="CB",
                )
            ],
            "ar_snapshot.csv": [
                ARSnapshotRow(
                    snapshot_date=drop, facility_no=facility,
                    aging_bucket="0-30",  # type: ignore[arg-type]
                    outstanding_amount=Decimal("50000"), source_system="CB",
                )
            ],
            "physician_monthly.csv": [
                PhysicianMonthlyRow(
                    month=month, physician_npi="9876543210", facility_no=facility,
                    encounters_count=42, total_rvu=Decimal("88.0"),
                    total_work_rvu=Decimal("70.5"), revenue_attributed=Decimal("66000"),
                    source_system="CB",
                )
            ],
        }
        await ingest_drop(db, parsed, manifest, run.run_id)
        try:
            yield {"facility_no": facility, "drop_date": drop, "month": month, "run_id": run.run_id, "upn": upn}
        finally:
            # Cleanup
            for tbl in (
                "entries.fact_collections_daily",
                "entries.fact_ar_snapshot",
                "entries.fact_revenue_by_physician_mo",
            ):
                await db.execute(text(f"DELETE FROM {tbl} WHERE ingest_run_id = :rid"), {"rid": run.run_id})
            await db.execute(text("DELETE FROM ops.processed_files WHERE run_id = :rid"), {"rid": run.run_id})
            await db.execute(text("DELETE FROM ops.ingest_run WHERE run_id = :rid"), {"rid": run.run_id})
            await db.execute(text("DELETE FROM audit.audit_log WHERE changed_by_upn = :upn"), {"upn": upn})
            await db.commit()


async def test_daily_collections_returns_seeded_row(seeded_drop: dict) -> None:
    facility = seeded_drop["facility_no"]
    drop = seeded_drop["drop_date"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            f"/api/v1/finance/daily-collections?date_from={drop}&date_to={drop}&facility_no={facility}",
            headers={"Authorization": "Dev owner_finance"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    row = body["rows"][0]
    assert row["facility_no"] == facility
    assert row["payer_class"] == "commercial"
    assert row["net_revenue"] == "7300.00"
    assert uuid.UUID(row["ingest_run_id"]) == seeded_drop["run_id"]


async def test_ar_snapshot_returns_seeded_row(seeded_drop: dict) -> None:
    facility = seeded_drop["facility_no"]
    drop = seeded_drop["drop_date"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            f"/api/v1/finance/ar-snapshot?snapshot_date={drop}&facility_no={facility}",
            headers={"Authorization": "Dev owner_finance"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["rows"][0]["aging_bucket"] == "0-30"
    assert body["rows"][0]["outstanding_amount"] == "50000.00"


async def test_physician_monthly_returns_seeded_row(seeded_drop: dict) -> None:
    facility = seeded_drop["facility_no"]
    month = seeded_drop["month"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            f"/api/v1/finance/physician-monthly?month={month}&facility_no={facility}",
            headers={"Authorization": "Dev owner_finance"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["rows"][0]["physician_npi"] == "9876543210"
    assert body["rows"][0]["encounters_count"] == 42


async def test_daily_collections_filters_out_other_facilities(seeded_drop: dict) -> None:
    """Filter mismatch returns empty (not 404)."""
    drop = seeded_drop["drop_date"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            f"/api/v1/finance/daily-collections?date_from={drop}&date_to={drop}&facility_no=999999",
            headers={"Authorization": "Dev owner_finance"},
        )
    assert r.status_code == 200
    assert r.json() == {"count": 0, "rows": []}
