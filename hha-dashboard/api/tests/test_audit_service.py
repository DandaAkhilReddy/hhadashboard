"""Direct unit tests for app.services.audit — the ContextVar layer
that propagates the current user's UPN into the Postgres `audit.upn`
GUC for trigger attribution.

The DB-side trigger behavior (insert/update/delete dispatch into
`audit.audit_log`) is covered by `tests/test_audit_triggers.py`. This
file pins the Python contract: AUDITED_TABLES shape + the contextvar
semantics that callers rely on.
"""

from __future__ import annotations

import asyncio

from app.services.audit import AUDITED_TABLES, current_upn, set_current_upn


class TestAuditedTablesRegistry:
    def test_contains_every_phase1_audited_table(self) -> None:
        """Lock the v1 owner-form + masters tables into the registry."""
        for schema, table in [
            ("masters", "physicians"),
            ("masters", "comp_agreements"),
            ("masters", "contracts"),
            ("masters", "credentials"),
            ("masters", "site_coverage"),
            ("entries", "daily_entries"),
            ("entries", "monthly_finance_manual"),
            ("entries", "weekly_clinical"),
            ("entries", "weekly_hr_manual"),
        ]:
            assert (schema, table) in AUDITED_TABLES

    def test_contains_ventra_fact_tables_per_adr_006(self) -> None:
        """ADR-006 added 3 fact tables in migration 0011; they must be in the
        AUDITED_TABLES set so the migration that attaches triggers stays in
        sync."""
        assert ("entries", "fact_collections_daily") in AUDITED_TABLES
        assert ("entries", "fact_ar_snapshot") in AUDITED_TABLES
        assert ("entries", "fact_revenue_by_physician_mo") in AUDITED_TABLES

    def test_is_frozenset(self) -> None:
        """Treat the registry as immutable so test-time mutations cannot
        bleed across tests; callers must add via migration + module edit."""
        assert isinstance(AUDITED_TABLES, frozenset)

    def test_every_entry_is_a_two_tuple_of_strings(self) -> None:
        for item in AUDITED_TABLES:
            assert isinstance(item, tuple)
            assert len(item) == 2
            schema, table = item
            assert isinstance(schema, str)
            assert isinstance(table, str)
            assert schema  # no empty schema
            assert table  # no empty table

    def test_no_forbidden_phi_tables_in_registry(self) -> None:
        """Per ADR-001, no PHI-class tables should ever appear here.
        Defensive check that catches accidental future additions."""
        forbidden_names = {
            "claims",
            "encounters",
            "patients",
            "members",
            "subscribers",
            "guarantors",
        }
        for _schema, table in AUDITED_TABLES:
            assert table.lower() not in forbidden_names, (
                f"PHI-class table '{table}' must not be in AUDITED_TABLES "
                "(ADR-001 forbids PHI in audited HHA tables)."
            )


class TestSetCurrentUpn:
    def test_default_is_system_sentinel(self) -> None:
        """Before any set, the contextvar yields the `__system__` sentinel."""
        # Run in a fresh context so prior tests cannot leak.
        async def get_default() -> str:
            return current_upn.get()

        assert asyncio.run(get_default()) == "__system__"

    def test_set_and_get_within_same_context(self) -> None:
        async def run() -> str:
            set_current_upn("crystal@hha.com")
            return current_upn.get()

        assert asyncio.run(run()) == "crystal@hha.com"

    def test_returns_token_usable_for_reset(self) -> None:
        """The token returned by set_current_upn must be a valid reset target;
        FastAPI middleware relies on this pattern."""

        async def run() -> tuple[str, str]:
            token = set_current_upn("akhil@hha.com")
            mid = current_upn.get()
            current_upn.reset(token)
            after = current_upn.get()
            return mid, after

        mid, after = asyncio.run(run())
        assert mid == "akhil@hha.com"
        assert after == "__system__"

    def test_contexts_are_isolated(self) -> None:
        """Two async tasks must not see each other's UPN — the contextvar
        is meant to be request-scoped, not process-scoped."""

        async def child_set(value: str) -> str:
            set_current_upn(value)
            return current_upn.get()

        async def run() -> tuple[str, str, str]:
            set_current_upn("parent@hha.com")
            # Each task runs in a fresh copied context — but only when we use
            # `asyncio.create_task` with explicit `contextvars.copy_context`
            # semantics. Mirror what the FastAPI middleware does: spawn tasks
            # so the parent's UPN is captured at task creation.
            t1_value = await asyncio.create_task(child_set("child1@hha.com"))
            t2_value = await asyncio.create_task(child_set("child2@hha.com"))
            return current_upn.get(), t1_value, t2_value

        parent, c1, c2 = asyncio.run(run())
        # The two children set their own values inside their tasks.
        assert c1 == "child1@hha.com"
        assert c2 == "child2@hha.com"
        # Parent context is unaffected: each task got its own copy.
        assert parent == "parent@hha.com"

    def test_repeated_set_overwrites_within_same_context(self) -> None:
        async def run() -> str:
            set_current_upn("first@hha.com")
            set_current_upn("second@hha.com")
            return current_upn.get()

        assert asyncio.run(run()) == "second@hha.com"

    def test_set_accepts_empty_string_without_raising(self) -> None:
        """The setter does no validation; callers are responsible for
        passing a real UPN. Defensive test pins this contract."""

        async def run() -> str:
            set_current_upn("")
            return current_upn.get()

        assert asyncio.run(run()) == ""
