"""Census-only entry portal tests.

Two layers:

1. Pure validation tests run without Postgres (rejects bad input before any DB
   work happens — login validation, no-cookie 401).
2. DB-backed tests skip if Postgres isn't reachable. They cover login happy
   path, lockout, single-session lock, and the write-only daily-census POST.

The portal is intentionally separate from the Entra-gated dashboard, so the
tests use only `census_session` cookies — never `Authorization: Dev <role>`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text

from app.deps import SessionLocal
from app.main import app
from app.models.census_credentials import CensusCredential
from app.models.entries import DailyEntry
from app.models.masters import Site
from app.services import census_auth

pytestmark = pytest.mark.asyncio


# ----------------------------------------------------------------------------
# Pure validation — no DB needed
# ----------------------------------------------------------------------------


async def test_login_rejects_empty_email() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/census-portal/login",
            json={"email": "", "password": "x"},
        )
    assert r.status_code == 422


async def test_login_rejects_empty_password() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/census-portal/login",
            json={"email": "ops@example.com", "password": ""},
        )
    assert r.status_code == 422


async def test_daily_census_without_cookie_returns_401() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/census-portal/daily-census",
            json={
                "entry_date": datetime.now(UTC).date().isoformat(),
                "rows": [{"site_id": 1, "census": 100}],
            },
        )
    assert r.status_code == 401


# ----------------------------------------------------------------------------
# DB-backed — skipped if Postgres isn't reachable
# ----------------------------------------------------------------------------


async def _can_connect_to_postgres() -> bool:
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="module", autouse=True)
async def _skip_if_no_postgres() -> None:
    if not await _can_connect_to_postgres():
        pytest.skip("Postgres not reachable — skipping census-portal DB tests")


TEST_EMAIL = "portal-test@hhamedicine.com"
TEST_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
async def seeded_credential():
    """Drop and re-seed the single census_credentials row before each test."""
    async with SessionLocal() as session:
        await session.execute(delete(CensusCredential))
        cred = CensusCredential(
            id=1,
            email=TEST_EMAIL,
            password_hash=census_auth.hash_password(TEST_PASSWORD),
            failed_attempts=0,
        )
        session.add(cred)
        await session.commit()
    yield
    async with SessionLocal() as session:
        await session.execute(delete(CensusCredential))
        await session.commit()


async def test_login_happy_path_sets_cookie_and_returns_sites(seeded_credential) -> None:
    _ = seeded_credential
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/census-portal/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
    assert r.status_code == 200
    assert r.cookies.get("census_session"), "login should set census_session cookie"
    body = r.json()
    assert "entry_date" in body
    assert isinstance(body["sites"], list)


async def test_login_wrong_password_returns_401_and_increments_counter(
    seeded_credential,
) -> None:
    _ = seeded_credential
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/census-portal/login",
            json={"email": TEST_EMAIL, "password": "wrong"},
        )
    assert r.status_code == 401

    async with SessionLocal() as session:
        cred = (
            await session.execute(select(CensusCredential).where(CensusCredential.id == 1))
        ).scalar_one()
        assert cred.failed_attempts == 1


async def test_lockout_after_ten_failures_returns_423(seeded_credential) -> None:
    _ = seeded_credential
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _i in range(10):
            await client.post(
                "/api/v1/census-portal/login",
                json={"email": TEST_EMAIL, "password": "wrong"},
            )
        # 11th attempt — even with the right password, the account is now locked.
        r = await client.post(
            "/api/v1/census-portal/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
    assert r.status_code == 423


async def test_single_session_lock_boots_prior_browser(seeded_credential) -> None:
    """Two simultaneous logins on the same credential. The first browser's
    cookie must stop working as soon as the second login completes."""
    _ = seeded_credential
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post(
            "/api/v1/census-portal/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        cookie1 = r1.cookies.get("census_session")

        # Second login — overwrites active_session_token.
        r2 = await client.post(
            "/api/v1/census-portal/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        cookie2 = r2.cookies.get("census_session")

    assert cookie1 != cookie2

    # Re-using cookie1 against a protected endpoint must 401.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/census-portal/daily-census",
            cookies={"census_session": cookie1},
            json={
                "entry_date": datetime.now(UTC).date().isoformat(),
                "rows": [{"site_id": 1, "census": 100}],
            },
        )
    assert r.status_code == 401


async def test_daily_census_with_valid_session_writes_with_manual_portal_source(
    seeded_credential,
) -> None:
    _ = seeded_credential
    today = datetime.now(UTC).date()

    # Ensure at least one site exists so the upsert has a valid site_id.
    # Tests don't assume scripts/seed_sites.py was run against the test DB.
    async with SessionLocal() as session:
        existing_sites = (await session.execute(select(Site))).scalars().all()
        if not existing_sites:
            session.add(Site(name="Test Site", state="FL", status="ACTIVE"))
            await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login_r = await client.post(
            "/api/v1/census-portal/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert login_r.status_code == 200
        sites = login_r.json()["sites"]
        assert sites, "expected at least one site (seeded above if missing)"
        site_id = sites[0]["site_id"]
        # Cookie has Secure=True; AsyncClient strips it under http://. Re-pass.
        cookie = login_r.cookies.get("census_session")
        assert cookie is not None

        r = await client.post(
            "/api/v1/census-portal/daily-census",
            cookies={"census_session": cookie},
            json={
                "entry_date": today.isoformat(),
                "rows": [{"site_id": site_id, "census": 123, "open_shifts": 1}],
            },
        )

    assert r.status_code == 200
    body = r.json()
    assert any(row["source"] == "manual_portal" for row in body)

    # Verify the row in the DB carries portal attribution.
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(DailyEntry).where(
                    DailyEntry.site_id == site_id,
                    DailyEntry.entry_date == today,
                )
            )
        ).scalar_one()
        assert row.census == 123
        assert row.source == "manual_portal"
        assert row.entered_by_upn == "census-portal@hhamedicine.com"

    # Cleanup so we don't leave behind today's-row state for other tests.
    async with SessionLocal() as session:
        await session.execute(
            delete(DailyEntry).where(
                DailyEntry.site_id == site_id,
                DailyEntry.entry_date == today,
            )
        )
        await session.commit()


async def test_prefill_includes_entered_at_for_existing_entries(
    seeded_credential,
) -> None:
    """Login response must carry `entered_at` for any site that already has a
    DailyEntry today, and `null` for sites that don't. The portal UI uses this
    to decide whether to render the row in locked-with-Edit state."""
    _ = seeded_credential
    today = datetime.now(UTC).date()

    async with SessionLocal() as session:
        existing_sites = (await session.execute(select(Site))).scalars().all()
        if not existing_sites:
            session.add(Site(name="Test Site", state="FL", status="ACTIVE"))
            await session.commit()
            existing_sites = (await session.execute(select(Site))).scalars().all()
        seeded_site_id = existing_sites[0].id
        unseeded_site_id = existing_sites[1].id if len(existing_sites) > 1 else None

        # Pre-seed today's entry for one site so we have a known entered_at.
        await session.execute(
            delete(DailyEntry).where(DailyEntry.entry_date == today)
        )
        session.add(
            DailyEntry(
                site_id=seeded_site_id,
                entry_date=today,
                census=88,
                open_shifts=2,
                entered_by_upn="census-portal@hhamedicine.com",
                source="manual_portal",
            )
        )
        await session.commit()

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            login_r = await client.post(
                "/api/v1/census-portal/login",
                json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            )
        assert login_r.status_code == 200
        sites = {s["site_id"]: s for s in login_r.json()["sites"]}

        seeded_row = sites[seeded_site_id]
        assert seeded_row["census"] == 88
        assert seeded_row["entered_at"] is not None, (
            "site with an existing entry must surface entered_at"
        )

        if unseeded_site_id is not None:
            unseeded_row = sites[unseeded_site_id]
            assert unseeded_row["census"] is None
            assert unseeded_row["entered_at"] is None, (
                "site without an entry today must have entered_at=null"
            )
    finally:
        async with SessionLocal() as session:
            await session.execute(
                delete(DailyEntry).where(DailyEntry.entry_date == today)
            )
            await session.commit()


async def test_save_response_includes_entered_at(seeded_credential) -> None:
    """POST /daily-census must return `entered_at` on every saved row so the
    frontend can immediately flip the row into the locked-with-Edit state
    without a follow-up GET."""
    _ = seeded_credential
    today = datetime.now(UTC).date()

    async with SessionLocal() as session:
        existing_sites = (await session.execute(select(Site))).scalars().all()
        if not existing_sites:
            session.add(Site(name="Test Site", state="FL", status="ACTIVE"))
            await session.commit()
        await session.execute(
            delete(DailyEntry).where(DailyEntry.entry_date == today)
        )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        login_r = await client.post(
            "/api/v1/census-portal/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert login_r.status_code == 200
        site_id = login_r.json()["sites"][0]["site_id"]
        cookie = login_r.cookies.get("census_session")
        assert cookie is not None

        r = await client.post(
            "/api/v1/census-portal/daily-census",
            cookies={"census_session": cookie},
            json={
                "entry_date": today.isoformat(),
                "rows": [{"site_id": site_id, "census": 50, "open_shifts": 0}],
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["entered_at"] is not None
    # Datetime parses without raising — locks the wire shape.
    datetime.fromisoformat(body[0]["entered_at"].replace("Z", "+00:00"))

    async with SessionLocal() as session:
        await session.execute(
            delete(DailyEntry).where(
                DailyEntry.site_id == site_id, DailyEntry.entry_date == today
            )
        )
        await session.commit()


async def test_re_save_advances_entered_at_timestamp(seeded_credential) -> None:
    """Locks the audit-friendly story: editing an already-entered row updates
    `updated_at` (which the API surfaces as `entered_at`). The frontend's
    "entered HH:MM" timestamp will move forward after every Edit → Save.

    Combined with the audit-trigger coverage merged in T13, this means a re-save
    produces an UPDATE row in audit.audit_log with the new value — the change
    history the portal user wants for "I see who edited what when."
    """
    _ = seeded_credential
    today = datetime.now(UTC).date()

    async with SessionLocal() as session:
        existing_sites = (await session.execute(select(Site))).scalars().all()
        if not existing_sites:
            session.add(Site(name="Test Site", state="FL", status="ACTIVE"))
            await session.commit()
        await session.execute(
            delete(DailyEntry).where(DailyEntry.entry_date == today)
        )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        login_r = await client.post(
            "/api/v1/census-portal/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        site_id = login_r.json()["sites"][0]["site_id"]
        cookie = login_r.cookies.get("census_session")
        assert cookie is not None

        first = await client.post(
            "/api/v1/census-portal/daily-census",
            cookies={"census_session": cookie},
            json={
                "entry_date": today.isoformat(),
                "rows": [{"site_id": site_id, "census": 100, "open_shifts": 0}],
            },
        )
        assert first.status_code == 200
        first_ts = datetime.fromisoformat(
            first.json()[0]["entered_at"].replace("Z", "+00:00")
        )

        # Re-save with a new census — the user's "Edit → Save" path.
        second = await client.post(
            "/api/v1/census-portal/daily-census",
            cookies={"census_session": cookie},
            json={
                "entry_date": today.isoformat(),
                "rows": [{"site_id": site_id, "census": 105, "open_shifts": 0}],
            },
        )
        assert second.status_code == 200
        second_ts = datetime.fromisoformat(
            second.json()[0]["entered_at"].replace("Z", "+00:00")
        )

    assert second.json()[0]["census"] == 105
    assert second_ts >= first_ts, "re-save must advance entered_at"

    async with SessionLocal() as session:
        await session.execute(
            delete(DailyEntry).where(
                DailyEntry.site_id == site_id, DailyEntry.entry_date == today
            )
        )
        await session.commit()


async def test_logout_clears_session(seeded_credential) -> None:
    _ = seeded_credential
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login_r = await client.post(
            "/api/v1/census-portal/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        cookie = login_r.cookies.get("census_session")

        r = await client.post(
            "/api/v1/census-portal/logout",
            cookies={"census_session": cookie},
        )
        assert r.status_code == 200

    # Cookie should now be invalid.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/census-portal/daily-census",
            cookies={"census_session": cookie},
            json={
                "entry_date": datetime.now(UTC).date().isoformat(),
                "rows": [{"site_id": 1, "census": 100}],
            },
        )
    assert r.status_code == 401
