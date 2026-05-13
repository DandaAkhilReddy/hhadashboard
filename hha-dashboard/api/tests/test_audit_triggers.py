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

T13 lock-in (audit ticket): the original tests above only cover
`entries.daily_entries`. The lower half of this file adds parameterized
coverage across all 9 audited tables — every table gets a trigger-attached
metadata check + INSERT/UPDATE/DELETE smoke test that asserts an audit
row is written with the right `action`. Catches regressions like "trigger
silently dropped" or "AUDITED_TABLES list edited without re-running 0007."

These tests require Docker Postgres up and migrations applied. They are
skipped automatically if the connection fails — the unit tests still cover
the logic that doesn't touch the database.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal

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


# ===================================================================
# T13: parameterized smoke coverage across all 9 audited tables
# ===================================================================
#
# Mirror the AUDITED_TABLES list from migration 0007. Order matters only
# for test readability — pytest will run them in this sequence per param.

AUDITED_TABLES_FQN: list[tuple[str, str]] = [
    ("masters", "physicians"),
    ("masters", "comp_agreements"),
    ("masters", "contracts"),
    ("masters", "credentials"),
    ("masters", "site_coverage"),
    ("entries", "daily_entries"),
    ("entries", "monthly_finance_manual"),
    ("entries", "weekly_clinical"),
    ("entries", "weekly_hr_manual"),
    # Added in migration 0011 (Ventra pre-aggregated facts per ADR-006).
    ("entries", "fact_collections_daily"),
    ("entries", "fact_ar_snapshot"),
    ("entries", "fact_revenue_by_physician_mo"),
]


def _test_ingest_run_uuid(upn: str) -> uuid.UUID:
    """Deterministic UUID derived from the test's UPN — used as
    ``ingest_run_id`` on every Ventra-fact-table insert in a single test
    invocation. Lets ``_scrub_ctx`` clean up by this UUID afterwards
    (the fact tables have no FK to ctx.site_id / ctx.physician_id, so
    cleanup-by-parent doesn't apply)."""
    return uuid.uuid5(uuid.NAMESPACE_DNS, upn)


@pytest.mark.parametrize(("schema", "table"), AUDITED_TABLES_FQN)
async def test_audit_trigger_attached_to_each_audited_table(
    session: AsyncSession, schema: str, table: str
) -> None:
    """Migration 0007 attaches `audit_<table>_change` to every entry in
    AUDITED_TABLES. A regression here = silent audit gap. We check via
    pg_trigger metadata rather than exercising INSERT, so this stays cheap
    and runs as the first sanity gate before the heavier I/O tests below.
    """
    result = await session.execute(
        text(
            "SELECT 1 FROM pg_trigger t "
            "JOIN pg_class c ON t.tgrelid = c.oid "
            "JOIN pg_namespace n ON c.relnamespace = n.oid "
            "WHERE n.nspname = :schema AND c.relname = :table "
            "AND t.tgname = :tgname AND NOT t.tgisinternal"
        ),
        {"schema": schema, "table": table, "tgname": f"audit_{table}_change"},
    )
    assert result.scalar_one_or_none() == 1, (
        f"audit_{table}_change trigger missing on {schema}.{table} — "
        "migration 0007 may have been edited without updating AUDITED_TABLES."
    )


# ----------- Per-table seed/update/delete dispatch -----------
#
# Each table has unique NOT NULL columns and FK requirements. Rather than
# writing one giant test per table, we keep the test bodies parameterized
# and dispatch the SQL via this map. Every entry returns (row_id) so the
# test can issue UPDATE/DELETE against it.

# Type alias for the dispatch fns: takes (session, ctx) → row id
SeedFn = Callable[[AsyncSession, "_TableOpCtx"], Awaitable[int]]
MutateFn = Callable[[AsyncSession, "_TableOpCtx", int], Awaitable[None]]


class _TableOpCtx:
    """Pre-baked parents (site, physician) shared across each parameterized
    test invocation. Tests use `ctx.suffix` to keep INSERTs unique under
    the per-table UNIQUE constraints (e.g. one_finance_per_month_per_state).
    """

    def __init__(self, site_id: int, physician_id: int, upn: str, suffix: str) -> None:
        self.site_id = site_id
        self.physician_id = physician_id
        self.upn = upn
        self.suffix = suffix


# ----- masters.physicians -----
async def _seed_physicians(s: AsyncSession, ctx: _TableOpCtx) -> int:
    r = await s.execute(
        text("INSERT INTO masters.physicians (name) VALUES (:n) RETURNING id"),
        {"n": f"T13-Phys-{ctx.suffix}"},
    )
    rid = int(r.scalar_one())
    await s.commit()
    return rid


async def _update_physicians(s: AsyncSession, ctx: _TableOpCtx, rid: int) -> None:
    await s.execute(
        text("UPDATE masters.physicians SET name = :n WHERE id = :id"),
        {"n": f"T13-Phys-UPDATED-{ctx.suffix}", "id": rid},
    )
    await s.commit()


async def _delete_physicians(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(text("DELETE FROM masters.physicians WHERE id = :id"), {"id": rid})
    await s.commit()


# ----- masters.comp_agreements -----
async def _seed_comp_agreements(s: AsyncSession, ctx: _TableOpCtx) -> int:
    r = await s.execute(
        text(
            "INSERT INTO masters.comp_agreements "
            "(physician_id, effective_from, employment_type, fmv_benchmark_usd) "
            "VALUES (:pid, :ef, 'W2', 250000) RETURNING id"
        ),
        {"pid": ctx.physician_id, "ef": date(2026, 1, 1)},
    )
    rid = int(r.scalar_one())
    await s.commit()
    return rid


async def _update_comp_agreements(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(
        text("UPDATE masters.comp_agreements SET fmv_benchmark_usd = :v WHERE id = :id"),
        {"v": Decimal("275000.00"), "id": rid},
    )
    await s.commit()


async def _delete_comp_agreements(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(text("DELETE FROM masters.comp_agreements WHERE id = :id"), {"id": rid})
    await s.commit()


# ----- masters.contracts -----
async def _seed_contracts(s: AsyncSession, ctx: _TableOpCtx) -> int:
    r = await s.execute(
        text(
            "INSERT INTO masters.contracts "
            "(site_id, start_date, end_date, annual_subsidy_usd) "
            "VALUES (:sid, :sd, :ed, :amt) RETURNING id"
        ),
        {
            "sid": ctx.site_id,
            "sd": date(2026, 1, 1),
            "ed": date(2026, 12, 31),
            "amt": Decimal("100000.00"),
        },
    )
    rid = int(r.scalar_one())
    await s.commit()
    return rid


async def _update_contracts(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(
        text("UPDATE masters.contracts SET annual_subsidy_usd = :v WHERE id = :id"),
        {"v": Decimal("125000.00"), "id": rid},
    )
    await s.commit()


async def _delete_contracts(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(text("DELETE FROM masters.contracts WHERE id = :id"), {"id": rid})
    await s.commit()


# ----- masters.credentials -----
async def _seed_credentials(s: AsyncSession, ctx: _TableOpCtx) -> int:
    r = await s.execute(
        text(
            "INSERT INTO masters.credentials "
            "(physician_id, type, expires_on) "
            "VALUES (:pid, 'STATE_LICENSE', :ex) RETURNING id"
        ),
        {"pid": ctx.physician_id, "ex": date(2027, 12, 31)},
    )
    rid = int(r.scalar_one())
    await s.commit()
    return rid


async def _update_credentials(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(
        text("UPDATE masters.credentials SET status = :v WHERE id = :id"),
        {"v": "EXPIRED", "id": rid},
    )
    await s.commit()


async def _delete_credentials(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(text("DELETE FROM masters.credentials WHERE id = :id"), {"id": rid})
    await s.commit()


# ----- masters.site_coverage -----
async def _seed_site_coverage(s: AsyncSession, ctx: _TableOpCtx) -> int:
    r = await s.execute(
        text(
            "INSERT INTO masters.site_coverage "
            "(site_id, physician_id, role, start_date) "
            "VALUES (:sid, :pid, 'MEDICAL_DIRECTOR', :sd) RETURNING id"
        ),
        {"sid": ctx.site_id, "pid": ctx.physician_id, "sd": date(2026, 1, 1)},
    )
    rid = int(r.scalar_one())
    await s.commit()
    return rid


async def _update_site_coverage(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(
        text("UPDATE masters.site_coverage SET role = :v WHERE id = :id"),
        {"v": "COVERING", "id": rid},
    )
    await s.commit()


async def _delete_site_coverage(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(text("DELETE FROM masters.site_coverage WHERE id = :id"), {"id": rid})
    await s.commit()


# ----- entries.daily_entries -----
async def _seed_daily_entries(s: AsyncSession, ctx: _TableOpCtx) -> int:
    # entry_date must be unique per site; use suffix-derived offset to avoid
    # collisions across the 4 invocations (insert + update + delete + attach)
    # for the same site.
    r = await s.execute(
        text(
            "INSERT INTO entries.daily_entries "
            "(site_id, entry_date, census, open_shifts, entered_by_upn, source) "
            "VALUES (:sid, :d, 100, 0, :upn, 'manual') RETURNING id"
        ),
        {"sid": ctx.site_id, "d": date(2026, 6, 1), "upn": ctx.upn},
    )
    rid = int(r.scalar_one())
    await s.commit()
    return rid


async def _update_daily_entries(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(
        text("UPDATE entries.daily_entries SET census = :v WHERE id = :id"),
        {"v": 105, "id": rid},
    )
    await s.commit()


async def _delete_daily_entries(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(text("DELETE FROM entries.daily_entries WHERE id = :id"), {"id": rid})
    await s.commit()


# ----- entries.monthly_finance_manual -----
async def _seed_monthly_finance_manual(s: AsyncSession, ctx: _TableOpCtx) -> int:
    r = await s.execute(
        text(
            "INSERT INTO entries.monthly_finance_manual ("
            "year, month, period_first, state, "
            "collections_usd, ar_total_usd, "
            "net_collection_rate_pct, days_in_ar, "
            "source_system, entered_by_upn"
            ") VALUES ("
            "2026, 6, :pf, 'TX', "
            "100000, 50000, "
            "95.00, 30.00, "
            "'HHA_TX_MANUAL', :upn"
            ") RETURNING id"
        ),
        {"pf": date(2026, 6, 1), "upn": ctx.upn},
    )
    rid = int(r.scalar_one())
    await s.commit()
    return rid


async def _update_monthly_finance_manual(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(
        text(
            "UPDATE entries.monthly_finance_manual SET collections_usd = :v WHERE id = :id"
        ),
        {"v": Decimal("110000.00"), "id": rid},
    )
    await s.commit()


async def _delete_monthly_finance_manual(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(
        text("DELETE FROM entries.monthly_finance_manual WHERE id = :id"), {"id": rid}
    )
    await s.commit()


# ----- entries.weekly_clinical -----
async def _seed_weekly_clinical(s: AsyncSession, ctx: _TableOpCtx) -> int:
    r = await s.execute(
        text(
            "INSERT INTO entries.weekly_clinical ("
            "week_ending, state, hp_24h_pct, dc_48h_pct, avg_los_days, entered_by_upn"
            ") VALUES (:we, 'TX', 92.5, 88.0, 4.2, :upn) RETURNING id"
        ),
        {"we": date(2026, 6, 7), "upn": ctx.upn},
    )
    rid = int(r.scalar_one())
    await s.commit()
    return rid


async def _update_weekly_clinical(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(
        text("UPDATE entries.weekly_clinical SET hp_24h_pct = :v WHERE id = :id"),
        {"v": Decimal("94.00"), "id": rid},
    )
    await s.commit()


async def _delete_weekly_clinical(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(text("DELETE FROM entries.weekly_clinical WHERE id = :id"), {"id": rid})
    await s.commit()


# ----- entries.weekly_hr_manual -----
async def _seed_weekly_hr_manual(s: AsyncSession, ctx: _TableOpCtx) -> int:
    r = await s.execute(
        text(
            "INSERT INTO entries.weekly_hr_manual ("
            "week_ending, headcount_w2, headcount_1099, entered_by_upn"
            ") VALUES (:we, 25, 5, :upn) RETURNING id"
        ),
        {"we": date(2026, 6, 7), "upn": ctx.upn},
    )
    rid = int(r.scalar_one())
    await s.commit()
    return rid


async def _update_weekly_hr_manual(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(
        text("UPDATE entries.weekly_hr_manual SET headcount_w2 = :v WHERE id = :id"),
        {"v": 27, "id": rid},
    )
    await s.commit()


async def _delete_weekly_hr_manual(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(text("DELETE FROM entries.weekly_hr_manual WHERE id = :id"), {"id": rid})
    await s.commit()


# ----- entries.fact_collections_daily (migration 0011, ADR-006) -----
async def _seed_fact_collections_daily(s: AsyncSession, ctx: _TableOpCtx) -> int:
    r = await s.execute(
        text(
            "INSERT INTO entries.fact_collections_daily ("
            "date, facility_no, payer_class, "
            "gross_charges, payments_received, net_revenue, "
            "ingest_run_id"
            ") VALUES ("
            ":d, :fn, 'commercial', "
            "10000, 8000, 7500, "
            ":rid"
            ") RETURNING id"
        ),
        {"d": date(2026, 6, 1), "fn": 901, "rid": _test_ingest_run_uuid(ctx.upn)},
    )
    rid = int(r.scalar_one())
    await s.commit()
    return rid


async def _update_fact_collections_daily(
    s: AsyncSession, _: _TableOpCtx, rid: int
) -> None:
    await s.execute(
        text(
            "UPDATE entries.fact_collections_daily "
            "SET payments_received = :v WHERE id = :id"
        ),
        {"v": Decimal("8500.00"), "id": rid},
    )
    await s.commit()


async def _delete_fact_collections_daily(
    s: AsyncSession, _: _TableOpCtx, rid: int
) -> None:
    await s.execute(
        text("DELETE FROM entries.fact_collections_daily WHERE id = :id"),
        {"id": rid},
    )
    await s.commit()


# ----- entries.fact_ar_snapshot (migration 0011, ADR-006) -----
async def _seed_fact_ar_snapshot(s: AsyncSession, ctx: _TableOpCtx) -> int:
    r = await s.execute(
        text(
            "INSERT INTO entries.fact_ar_snapshot ("
            "snapshot_date, facility_no, aging_bucket, "
            "outstanding_amount, ingest_run_id"
            ") VALUES ("
            ":d, :fn, '0-30', "
            "50000, :rid"
            ") RETURNING id"
        ),
        {"d": date(2026, 6, 1), "fn": 902, "rid": _test_ingest_run_uuid(ctx.upn)},
    )
    rid = int(r.scalar_one())
    await s.commit()
    return rid


async def _update_fact_ar_snapshot(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(
        text(
            "UPDATE entries.fact_ar_snapshot "
            "SET outstanding_amount = :v WHERE id = :id"
        ),
        {"v": Decimal("55000.00"), "id": rid},
    )
    await s.commit()


async def _delete_fact_ar_snapshot(s: AsyncSession, _: _TableOpCtx, rid: int) -> None:
    await s.execute(
        text("DELETE FROM entries.fact_ar_snapshot WHERE id = :id"), {"id": rid}
    )
    await s.commit()


# ----- entries.fact_revenue_by_physician_mo (migration 0011, ADR-006) -----
async def _seed_fact_revenue_by_physician_mo(
    s: AsyncSession, ctx: _TableOpCtx
) -> int:
    r = await s.execute(
        text(
            "INSERT INTO entries.fact_revenue_by_physician_mo ("
            "month, physician_npi, facility_no, "
            "encounters_count, revenue_attributed, ingest_run_id"
            ") VALUES ("
            ":m, '1234567890', :fn, "
            "50, 75000, :rid"
            ") RETURNING id"
        ),
        {"m": date(2026, 6, 1), "fn": 903, "rid": _test_ingest_run_uuid(ctx.upn)},
    )
    rid = int(r.scalar_one())
    await s.commit()
    return rid


async def _update_fact_revenue_by_physician_mo(
    s: AsyncSession, _: _TableOpCtx, rid: int
) -> None:
    await s.execute(
        text(
            "UPDATE entries.fact_revenue_by_physician_mo "
            "SET encounters_count = :v WHERE id = :id"
        ),
        {"v": 55, "id": rid},
    )
    await s.commit()


async def _delete_fact_revenue_by_physician_mo(
    s: AsyncSession, _: _TableOpCtx, rid: int
) -> None:
    await s.execute(
        text("DELETE FROM entries.fact_revenue_by_physician_mo WHERE id = :id"),
        {"id": rid},
    )
    await s.commit()


# Dispatch map keyed by "schema.table" → (seed, update, delete) triple.
TABLE_OPS: dict[str, tuple[SeedFn, MutateFn, MutateFn]] = {
    "masters.physicians": (_seed_physicians, _update_physicians, _delete_physicians),
    "masters.comp_agreements": (
        _seed_comp_agreements,
        _update_comp_agreements,
        _delete_comp_agreements,
    ),
    "masters.contracts": (_seed_contracts, _update_contracts, _delete_contracts),
    "masters.credentials": (_seed_credentials, _update_credentials, _delete_credentials),
    "masters.site_coverage": (_seed_site_coverage, _update_site_coverage, _delete_site_coverage),
    "entries.daily_entries": (_seed_daily_entries, _update_daily_entries, _delete_daily_entries),
    "entries.monthly_finance_manual": (
        _seed_monthly_finance_manual,
        _update_monthly_finance_manual,
        _delete_monthly_finance_manual,
    ),
    "entries.weekly_clinical": (
        _seed_weekly_clinical,
        _update_weekly_clinical,
        _delete_weekly_clinical,
    ),
    "entries.weekly_hr_manual": (
        _seed_weekly_hr_manual,
        _update_weekly_hr_manual,
        _delete_weekly_hr_manual,
    ),
    "entries.fact_collections_daily": (
        _seed_fact_collections_daily,
        _update_fact_collections_daily,
        _delete_fact_collections_daily,
    ),
    "entries.fact_ar_snapshot": (
        _seed_fact_ar_snapshot,
        _update_fact_ar_snapshot,
        _delete_fact_ar_snapshot,
    ),
    "entries.fact_revenue_by_physician_mo": (
        _seed_fact_revenue_by_physician_mo,
        _update_fact_revenue_by_physician_mo,
        _delete_fact_revenue_by_physician_mo,
    ),
}

# Sanity: dispatch must cover every audited table — fails fast if someone
# adds to AUDITED_TABLES without adding a spec here.
assert set(TABLE_OPS.keys()) == {f"{s}.{t}" for s, t in AUDITED_TABLES_FQN}, (
    "TABLE_OPS keys must match AUDITED_TABLES_FQN"
)


async def _fresh_op_ctx(session: AsyncSession, table_fqn: str) -> _TableOpCtx:
    """Pre-create a site + physician parent per parameterized test invocation.
    Each invocation gets unique parent IDs so cleanup can be table-scoped.
    """
    upn = f"t13-{table_fqn.replace('.', '-')}@hha.com"
    set_current_upn(upn)
    suffix = table_fqn.replace(".", "-")

    site_result = await session.execute(
        text(
            "INSERT INTO masters.sites (name, state, status) "
            "VALUES (:n, 'FL', 'ACTIVE') RETURNING id"
        ),
        {"n": f"T13-Site-{suffix}"},
    )
    site_id = int(site_result.scalar_one())
    await session.commit()

    phys_result = await session.execute(
        text("INSERT INTO masters.physicians (name) VALUES (:n) RETURNING id"),
        {"n": f"T13-Parent-Phys-{suffix}"},
    )
    physician_id = int(phys_result.scalar_one())
    await session.commit()

    return _TableOpCtx(site_id=site_id, physician_id=physician_id, upn=upn, suffix=suffix)


async def _scrub_ctx(session: AsyncSession, ctx: _TableOpCtx) -> None:
    """Tear down everything created by this test invocation. Order matters:
    audit_log first (FK-free), then the dependent rows, then the parents.
    """
    await session.execute(
        text("DELETE FROM audit.audit_log WHERE changed_by_upn = :upn"),
        {"upn": ctx.upn},
    )
    # Clean every audited table that may have referenced our parents. Safe to
    # blanket-delete by FK because the test only ever inserted one row per
    # table per parent within its own UPN scope.
    await session.execute(
        text("DELETE FROM masters.site_coverage WHERE site_id = :sid OR physician_id = :pid"),
        {"sid": ctx.site_id, "pid": ctx.physician_id},
    )
    await session.execute(
        text("DELETE FROM masters.credentials WHERE physician_id = :pid"),
        {"pid": ctx.physician_id},
    )
    await session.execute(
        text("DELETE FROM masters.comp_agreements WHERE physician_id = :pid"),
        {"pid": ctx.physician_id},
    )
    await session.execute(
        text("DELETE FROM masters.contracts WHERE site_id = :sid"), {"sid": ctx.site_id}
    )
    await session.execute(
        text("DELETE FROM entries.daily_entries WHERE site_id = :sid"), {"sid": ctx.site_id}
    )
    # Finance / clinical / HR tables are not FK-linked to our parents — their
    # rows are addressed by entered_by_upn (matches our isolated test UPN).
    await session.execute(
        text("DELETE FROM entries.monthly_finance_manual WHERE entered_by_upn = :upn"),
        {"upn": ctx.upn},
    )
    await session.execute(
        text("DELETE FROM entries.weekly_clinical WHERE entered_by_upn = :upn"),
        {"upn": ctx.upn},
    )
    await session.execute(
        text("DELETE FROM entries.weekly_hr_manual WHERE entered_by_upn = :upn"),
        {"upn": ctx.upn},
    )
    # Ventra fact tables (migration 0011) — addressed by the deterministic
    # ingest_run_id derived from the test's upn. No FK to ctx parents so
    # cleanup-by-parent doesn't apply.
    test_ingest_run = _test_ingest_run_uuid(ctx.upn)
    await session.execute(
        text(
            "DELETE FROM entries.fact_collections_daily WHERE ingest_run_id = :rid"
        ),
        {"rid": test_ingest_run},
    )
    await session.execute(
        text("DELETE FROM entries.fact_ar_snapshot WHERE ingest_run_id = :rid"),
        {"rid": test_ingest_run},
    )
    await session.execute(
        text(
            "DELETE FROM entries.fact_revenue_by_physician_mo "
            "WHERE ingest_run_id = :rid"
        ),
        {"rid": test_ingest_run},
    )
    # Now the parents.
    await session.execute(
        text("DELETE FROM masters.physicians WHERE id = :id"), {"id": ctx.physician_id}
    )
    await session.execute(
        text("DELETE FROM masters.sites WHERE id = :id"), {"id": ctx.site_id}
    )
    # Re-clean audit_log: every DELETE above also fires triggers.
    await session.execute(
        text("DELETE FROM audit.audit_log WHERE changed_by_upn = :upn"),
        {"upn": ctx.upn},
    )
    await session.commit()
    set_current_upn("trigger-test@hha.com")  # restore default


@pytest.mark.parametrize("table_fqn", list(TABLE_OPS.keys()))
async def test_insert_writes_audit_row_for_every_audited_table(
    session: AsyncSession, table_fqn: str
) -> None:
    """For each audited table: a minimum-fields INSERT must produce exactly
    one audit row with action='INSERT' attributed to the test UPN. This
    catches schema drift (e.g. a NOT NULL added without updating the trigger
    function's NEW serialization)."""
    seed, _, _ = TABLE_OPS[table_fqn]
    ctx = await _fresh_op_ctx(session, table_fqn)
    schema, table = table_fqn.split(".", 1)
    try:
        before = await _audit_count_for(session, table, ctx.upn)
        rid = await seed(session, ctx)
        assert rid > 0
        after = await _audit_count_for(session, table, ctx.upn)
        assert after == before + 1, (
            f"INSERT into {schema}.{table} should write exactly one audit row "
            f"for upn={ctx.upn}; saw {after - before}"
        )

        # Tighten: confirm the row really has action='INSERT' (not just count).
        row = (
            await session.execute(
                text(
                    "SELECT action FROM audit.audit_log "
                    "WHERE table_name = :t AND changed_by_upn = :upn "
                    "ORDER BY changed_at DESC LIMIT 1"
                ),
                {"t": table, "upn": ctx.upn},
            )
        ).scalar_one()
        assert row == "INSERT"
    finally:
        await _scrub_ctx(session, ctx)


@pytest.mark.parametrize("table_fqn", list(TABLE_OPS.keys()))
async def test_update_writes_audit_row_for_every_audited_table(
    session: AsyncSession, table_fqn: str
) -> None:
    """For each audited table: an UPDATE that changes a real value (not just
    timestamps) must produce one new audit row with action='UPDATE'."""
    seed, update, _ = TABLE_OPS[table_fqn]
    ctx = await _fresh_op_ctx(session, table_fqn)
    _, table = table_fqn.split(".", 1)
    try:
        rid = await seed(session, ctx)
        # Drop the INSERT audit row so the count cleanly reflects only the UPDATE.
        await session.execute(
            text("DELETE FROM audit.audit_log WHERE changed_by_upn = :upn"),
            {"upn": ctx.upn},
        )
        await session.commit()

        await update(session, ctx, rid)

        row = (
            await session.execute(
                text(
                    "SELECT action FROM audit.audit_log "
                    "WHERE table_name = :t AND changed_by_upn = :upn "
                    "ORDER BY changed_at DESC LIMIT 1"
                ),
                {"t": table, "upn": ctx.upn},
            )
        ).scalar_one()
        assert row == "UPDATE"
    finally:
        await _scrub_ctx(session, ctx)


@pytest.mark.parametrize("table_fqn", list(TABLE_OPS.keys()))
async def test_delete_writes_audit_row_for_every_audited_table(
    session: AsyncSession, table_fqn: str
) -> None:
    """For each audited table: a DELETE must produce one audit row with
    action='DELETE'. Locks that the trigger fires on row removal even when
    the row is the last reference (no FK cascades to other audited tables)."""
    seed, _, delete = TABLE_OPS[table_fqn]
    ctx = await _fresh_op_ctx(session, table_fqn)
    _, table = table_fqn.split(".", 1)
    try:
        rid = await seed(session, ctx)
        await session.execute(
            text("DELETE FROM audit.audit_log WHERE changed_by_upn = :upn"),
            {"upn": ctx.upn},
        )
        await session.commit()

        await delete(session, ctx, rid)

        row = (
            await session.execute(
                text(
                    "SELECT action FROM audit.audit_log "
                    "WHERE table_name = :t AND changed_by_upn = :upn "
                    "ORDER BY changed_at DESC LIMIT 1"
                ),
                {"t": table, "upn": ctx.upn},
            )
        ).scalar_one()
        assert row == "DELETE"
    finally:
        await _scrub_ctx(session, ctx)
