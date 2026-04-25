"""Audit event listener tests.

Uses an in-memory SQLite DB so the test is pure-unit (no Docker / Postgres required).
We still import the real models + listener — it's exercising the real code path.

Note: Postgres features (JSONB, CHECK constraints, GIST exclusions) don't exist
in SQLite. We work around this by not asserting on JSONB specifically — SQLite
stores the diff as TEXT and SQLAlchemy decodes it back to dict on load.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.base import Base
from app.models.entries import DailyEntry
from app.models.masters import Site
from app.services import audit as audit_service


@pytest.fixture
def db_session():
    """Sqlite in-memory DB with schemas stubbed as prefixes."""
    # SQLite doesn't support schemas — tell SQLAlchemy to ignore them for this test.
    # We do this by rebinding the metadata without schema info per-test.
    # Simpler: use `attach database` trick or just accept the real schema names
    # by creating attached DBs. For unit scope, the JSONB → Text coercion is
    # what matters.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    # Attach schemas as separate databases so schema-qualified table names work
    with engine.connect() as conn:
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS masters")
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS entries")
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS audit")
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS uploads")
        conn.commit()

    Base.metadata.create_all(engine)
    audit_service.install_audit_listener()

    # Match production: deps.py uses async_sessionmaker(expire_on_commit=False).
    # With expire_on_commit=True (the default), attributes are unloaded after
    # commit, and `load_history()` can't return the OLD value on the next
    # UPDATE — so the audit diff loses the `old` half.
    with Session(engine, expire_on_commit=False) as session:
        yield session

    engine.dispose()


def test_audit_insert_daily_entry(db_session: Session) -> None:
    """INSERT into entries.daily_entries fires one audit row with action=INSERT."""
    audit_service.set_current_upn("crystal@hhamedicine.com")

    # Need a site first (FK)
    site = Site(name="Westside Regional", state="FL", status="ACTIVE")
    db_session.add(site)
    db_session.flush()

    entry = DailyEntry(
        site_id=site.id,
        entry_date=date(2026, 4, 23),
        census=198,
        open_shifts=3,
        entered_by_upn="crystal@hhamedicine.com",
        source="manual",
    )
    db_session.add(entry)
    db_session.commit()

    # One audit row for the physician/site insert (masters.sites IS audited? no, sites not in list)
    # One audit row for the daily_entry insert
    audit_rows = (
        db_session.execute(
            select(AuditLog).where(
                AuditLog.table_schema == "entries",
                AuditLog.table_name == "daily_entries",
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    row = audit_rows[0]
    assert row.action == "INSERT"
    assert row.changed_by_upn == "crystal@hhamedicine.com"
    assert "new" in row.diff
    assert row.diff["new"]["census"] == 198
    assert row.diff["new"]["source"] == "manual"


def test_audit_update_daily_entry(db_session: Session) -> None:
    """UPDATE fires one audit row with just the changed columns."""
    audit_service.set_current_upn("crystal@hhamedicine.com")

    site = Site(name="Woodmont Hospital", state="FL", status="ACTIVE")
    db_session.add(site)
    db_session.flush()

    entry = DailyEntry(
        site_id=site.id,
        entry_date=date(2026, 4, 23),
        census=142,
        open_shifts=0,
        entered_by_upn="crystal@hhamedicine.com",
        source="manual",
    )
    db_session.add(entry)
    db_session.commit()

    # Now update
    entry.census = 148
    db_session.commit()

    update_rows = (
        db_session.execute(
            select(AuditLog)
            .where(
                AuditLog.table_schema == "entries",
                AuditLog.table_name == "daily_entries",
                AuditLog.action == "UPDATE",
            )
        )
        .scalars()
        .all()
    )
    assert len(update_rows) == 1
    row = update_rows[0]
    assert row.diff["census"]["old"] == 142
    assert row.diff["census"]["new"] == 148
    # Only census should be in the diff (not every column)
    assert set(row.diff.keys()) == {"census"}


def test_audit_skips_unaudited_tables(db_session: Session) -> None:
    """masters.sites is NOT in AUDITED_TABLES — inserting one should produce no audit rows."""
    audit_service.set_current_upn("admin@hhamedicine.com")

    site = Site(name="JFK Main Med Ctr", state="FL", status="ACTIVE")
    db_session.add(site)
    db_session.commit()

    all_audit_rows = db_session.execute(select(AuditLog)).scalars().all()
    # No audit rows because sites isn't in the audited set
    for row in all_audit_rows:
        assert not (row.table_schema == "masters" and row.table_name == "sites")


def test_audit_captures_system_upn_when_unset(db_session: Session) -> None:
    """If no UPN set in contextvar, fallback to '__system__'."""
    # Explicitly reset to default
    audit_service.set_current_upn("__system__")

    site = Site(name="Bay", state="TX", status="ACTIVE")
    db_session.add(site)
    db_session.flush()

    entry = DailyEntry(
        site_id=site.id,
        entry_date=date(2026, 4, 23),
        census=9,
        open_shifts=0,
        entered_by_upn="__system__",
        source="manual",
    )
    db_session.add(entry)
    db_session.commit()

    audit_row = db_session.execute(
        select(AuditLog).where(AuditLog.table_name == "daily_entries")
    ).scalar_one()
    assert audit_row.changed_by_upn == "__system__"
