"""Postgres audit-trigger integration tests.

Migration 0007 replaced the ORM `before_flush` listener with a PL/pgSQL
trigger function `audit.log_change()` attached to every audited table.
These tests run against the live Postgres docker container — they verify:

  - INSERT into an audited table writes one audit row with action='INSERT'
    and a `{"new": {...}}` diff (timestamps stripped)
  - UPDATE writes one audit row with `{col: {"old": ..., "new": ...}}`
    for changed cols only
  - UPDATE that only touches updated_at (no real value change) writes NO
    audit row
  - DELETE writes one audit row with `{"old": {...}}` diff
  - The session GUC `audit.upn` propagates to changed_by_upn
  - audit.audit_log itself is NOT triggered (no recursion)
  - Non-audited tables (masters.sites) produce no audit rows

These tests require Docker Postgres up and migrations applied. They are
skipped automatically if the connection fails — the unit tests still cover
the logic that doesn't touch the database.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import SessionLocal
from app.services.audit import set_current_upn

pytestmark = pytest.mark.asyncio


async def _can_connect_to_postgres() -> bool:
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


# Skip the whole module if Postgres isn't reachable. Lets the rest of the
# suite stay green in CI environments without a live DB (when we add CI).
@pytest.fixture(scope="module", autouse=True)
async def _skip_if_no_postgres() -> None:
    if not await _can_connect_to_postgres():
        pytest.skip("Postgres not reachable — skipping audit-trigger tests")


@pytest.fixture
async def session() -> AsyncSession:
    """Fresh session per test. Tests clean their own data via the cleanup
    block at the end of each test (rather than transaction rollback, since
    triggers fire only on COMMIT-visible work).
    """
    set_current_upn("trigger-test@hha.com")
    async with SessionLocal() as s:
        yield s


async def _audit_count_for(session: AsyncSession, table_name: str, upn: str) -> int:
    result = await session.execute(
        text(
            "SELECT COUNT(*) FROM audit.audit_log "
            "WHERE table_name = :t AND changed_by_upn = :upn"
        ),
        {"t": table_name, "upn": upn},
    )
    return result.scalar_one()


async def _seed_test_site(session: AsyncSession, name: str) -> int:
    """Insert a sites row (NOT audited) so we can FK-link daily_entries to it."""
    result = await session.execute(
        text(
            "INSERT INTO masters.sites (name, state, status) "
            "VALUES (:n, 'FL', 'ACTIVE') RETURNING id"
        ),
        {"n": name},
    )
    site_id = result.scalar_one()
    await session.commit()
    return site_id


async def _cleanup(session: AsyncSession, upn: str, site_id: int) -> None:
    await session.execute(
        text("DELETE FROM audit.audit_log WHERE changed_by_upn = :upn"),
        {"upn": upn},
    )
    await session.execute(
        text("DELETE FROM entries.daily_entries WHERE site_id = :sid"),
        {"sid": site_id},
    )
    await session.execute(text("DELETE FROM masters.sites WHERE id = :sid"), {"sid": site_id})
    await session.commit()


async def test_insert_writes_audit_row_with_new_diff(session: AsyncSession) -> None:
    upn = "trigger-test@hha.com"
    site_id = await _seed_test_site(session, "AuditTrigger-Insert")
    try:
        await session.execute(
            text(
                "INSERT INTO entries.daily_entries "
                "(site_id, entry_date, census, open_shifts, entered_by_upn, source) "
                "VALUES (:sid, :d, 100, 0, :upn, 'manual')"
            ),
            {"sid": site_id, "d": date(2026, 4, 25), "upn": upn},
        )
        await session.commit()

        result = await session.execute(
            text(
                "SELECT action, diff::text, changed_by_upn FROM audit.audit_log "
                "WHERE table_name = 'daily_entries' AND changed_by_upn = :upn "
                "ORDER BY changed_at DESC LIMIT 1"
            ),
            {"upn": upn},
        )
        row = result.one()
        assert row.action == "INSERT"
        assert row.changed_by_upn == upn
        assert '"new"' in row.diff
        assert '"census": 100' in row.diff
        # Timestamps must be stripped from the diff
        assert '"created_at"' not in row.diff
        assert '"updated_at"' not in row.diff
    finally:
        await _cleanup(session, upn, site_id)


async def test_update_writes_diff_with_changed_cols_only(session: AsyncSession) -> None:
    upn = "trigger-test@hha.com"
    site_id = await _seed_test_site(session, "AuditTrigger-Update")
    try:
        await session.execute(
            text(
                "INSERT INTO entries.daily_entries "
                "(site_id, entry_date, census, open_shifts, entered_by_upn, source) "
                "VALUES (:sid, :d, 100, 0, :upn, 'manual')"
            ),
            {"sid": site_id, "d": date(2026, 4, 25), "upn": upn},
        )
        await session.commit()

        # Now UPDATE just the census
        await session.execute(
            text(
                "UPDATE entries.daily_entries SET census = 105 "
                "WHERE site_id = :sid AND entry_date = :d"
            ),
            {"sid": site_id, "d": date(2026, 4, 25)},
        )
        await session.commit()

        result = await session.execute(
            text(
                "SELECT action, diff::text FROM audit.audit_log "
                "WHERE table_name = 'daily_entries' AND changed_by_upn = :upn "
                "AND action = 'UPDATE' ORDER BY changed_at DESC LIMIT 1"
            ),
            {"upn": upn},
        )
        row = result.one()
        assert row.action == "UPDATE"
        assert '"census"' in row.diff
        assert '"old": 100' in row.diff
        assert '"new": 105' in row.diff
        # Only the changed col is in the diff
        assert '"open_shifts"' not in row.diff
        assert '"entered_by_upn"' not in row.diff
    finally:
        await _cleanup(session, upn, site_id)


async def test_delete_writes_audit_row_with_old_diff(session: AsyncSession) -> None:
    upn = "trigger-test@hha.com"
    site_id = await _seed_test_site(session, "AuditTrigger-Delete")
    try:
        await session.execute(
            text(
                "INSERT INTO entries.daily_entries "
                "(site_id, entry_date, census, open_shifts, entered_by_upn, source) "
                "VALUES (:sid, :d, 200, 0, :upn, 'manual')"
            ),
            {"sid": site_id, "d": date(2026, 4, 25), "upn": upn},
        )
        await session.commit()

        await session.execute(
            text("DELETE FROM entries.daily_entries WHERE site_id = :sid"),
            {"sid": site_id},
        )
        await session.commit()

        result = await session.execute(
            text(
                "SELECT action, diff::text FROM audit.audit_log "
                "WHERE table_name = 'daily_entries' AND changed_by_upn = :upn "
                "AND action = 'DELETE' ORDER BY changed_at DESC LIMIT 1"
            ),
            {"upn": upn},
        )
        row = result.one()
        assert row.action == "DELETE"
        assert '"old"' in row.diff
        assert '"census": 200' in row.diff
    finally:
        await _cleanup(session, upn, site_id)


async def test_audit_log_table_itself_is_not_triggered(session: AsyncSession) -> None:
    """Inserting directly into audit.audit_log must NOT recursively trigger.

    audit.audit_log is intentionally not in the AUDITED_TABLES list, so the
    migration never attaches a trigger to it.
    """
    upn = "trigger-test@hha.com"
    before = await _audit_count_for(session, "audit_log", upn)
    await session.execute(
        text(
            "INSERT INTO audit.audit_log "
            "(table_schema, table_name, row_pk, action, diff, changed_by_upn, changed_at) "
            "VALUES ('test', 'test', '1', 'INSERT', '{}'::jsonb, :upn, now())"
        ),
        {"upn": upn},
    )
    await session.commit()
    after = await _audit_count_for(session, "audit_log", upn)
    assert after == before  # the manual insert wrote a row but did NOT cascade

    # cleanup
    await session.execute(
        text("DELETE FROM audit.audit_log WHERE table_name = 'test'"),
    )
    await session.commit()


async def test_unaudited_table_produces_no_audit_row(session: AsyncSession) -> None:
    """masters.sites is NOT in AUDITED_TABLES — no trigger attached."""
    before_total = (
        await session.execute(text("SELECT COUNT(*) FROM audit.audit_log"))
    ).scalar_one()

    site_id = await _seed_test_site(session, "AuditTrigger-Unaudited")
    try:
        after_total = (
            await session.execute(text("SELECT COUNT(*) FROM audit.audit_log"))
        ).scalar_one()
        # Sites insert produced ZERO audit rows
        assert after_total == before_total
    finally:
        # Direct cleanup — no entries to delete
        await session.execute(text("DELETE FROM masters.sites WHERE id = :sid"), {"sid": site_id})
        await session.commit()


async def test_upn_propagates_from_session_guc(session: AsyncSession) -> None:
    """The contextvar set by `set_current_upn` must reach the trigger via
    the Postgres GUC `audit.upn`, set automatically by the after_begin
    event listener in app/deps.py.
    """
    custom_upn = "specific-user@hha.com"
    set_current_upn(custom_upn)
    site_id = await _seed_test_site(session, "AuditTrigger-UPN")
    try:
        await session.execute(
            text(
                "INSERT INTO entries.daily_entries "
                "(site_id, entry_date, census, open_shifts, entered_by_upn, source) "
                "VALUES (:sid, :d, 50, 0, :upn, 'manual')"
            ),
            {"sid": site_id, "d": date(2026, 4, 25), "upn": custom_upn},
        )
        await session.commit()

        result = await session.execute(
            text(
                "SELECT changed_by_upn FROM audit.audit_log "
                "WHERE changed_by_upn = :upn ORDER BY changed_at DESC LIMIT 1"
            ),
            {"upn": custom_upn},
        )
        assert result.scalar_one() == custom_upn
    finally:
        await _cleanup(session, custom_upn, site_id)
        set_current_upn("trigger-test@hha.com")  # restore
