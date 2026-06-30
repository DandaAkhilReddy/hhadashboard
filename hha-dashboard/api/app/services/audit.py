"""Audit attribution — UPN propagation for Postgres-trigger-based audit.

Audit row writing is handled in Postgres by the `audit.log_change()` trigger
function (migration 0007), which fires on INSERT/UPDATE/DELETE for every
audited table. This module is the Python side: it tracks the current user's
UPN in a contextvar, and dependency code (FastAPI `get_db`, cron startup)
copies that into the session-scoped Postgres GUC `audit.upn` so the trigger
sees the right attribution.

Why a trigger and not an ORM listener:
    The previous `before_flush` listener fired only for ORM-tracked instances
    (session.new/dirty/deleted). Core-level statements like
    `pg_insert(...).on_conflict_do_update(...)` — used by every owner-form
    upsert and the Ventra ingest — bypass that path entirely. Triggers fire
    regardless of which API issued the SQL.
"""

from __future__ import annotations

import contextvars

# Tables covered by the trigger. Kept here so test code + future tooling has
# one canonical list. The migration that creates the triggers must stay
# in sync with this set; treat as immutable post-deploy and grow via new
# migrations.
AUDITED_TABLES: frozenset[tuple[str, str]] = frozenset(
    {
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
        # Test coverage in tests/test_audit_triggers.py::AUDITED_TABLES_FQN +
        # TABLE_OPS follows in commit C3b.
        ("entries", "fact_collections_daily"),
        ("entries", "fact_ar_snapshot"),
        ("entries", "fact_revenue_by_physician_mo"),
    }
)

# Request/job-scoped current-user UPN. Set by FastAPI middleware or job
# startup; copied into the Postgres GUC `audit.upn` by `get_db` (or the
# cron's session opener) before any audited SQL runs.
current_upn: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_upn", default="__system__"
)


def set_current_upn(upn: str) -> contextvars.Token[str]:
    """Set the UPN for the current async context. Returns a token for reset().

    FastAPI middleware pattern:
        token = set_current_upn(user.upn)
        try:
            response = await call_next(request)
        finally:
            current_upn.reset(token)
    """
    return current_upn.set(upn)
