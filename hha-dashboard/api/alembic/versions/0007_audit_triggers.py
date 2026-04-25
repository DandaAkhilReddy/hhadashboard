"""audit triggers — replace ORM listener with PL/pgSQL triggers

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-25

Why
---
The Python ORM `before_flush` listener at app/services/audit.py only fires
for ORM-tracked instances (session.new/dirty/deleted). All four owner-form
endpoints (Sessions 4/6/7/8) plus the Ventra ingest cron use Core-level
`pg_insert(...).on_conflict_do_update(...)` which BYPASSES the ORM unit of
work — net result: zero audit rows written for any of those mutations.

The fix: a Postgres trigger function `audit.log_change()` that fires for
INSERT/UPDATE/DELETE on every audited table, regardless of which API path
(ORM, Core, raw SQL) issued the statement. The trigger reads the current
user's UPN from a session-scoped GUC `audit.upn`, set by FastAPI middleware
or cron startup before any audited write.

Trigger contract:
- table_schema, table_name, row_pk (NEW.id / OLD.id), action (INSERT|UPDATE|DELETE)
- diff jsonb:
    INSERT → {"new": {col: val, ...}}                       (excl. created_at, updated_at)
    UPDATE → {col: {"old": val, "new": val}}  (changed cols only, excl. timestamps)
    DELETE → {"old": {col: val, ...}}
- changed_by_upn = current_setting('audit.upn', true) ?? '__system__'
- changed_at = now()

UPDATE with no real change after stripping timestamps → no audit row.
audit.audit_log itself is NOT triggered (avoids recursion).

Removes the redundant explicit `AuditLog` row that ventra_ingest currently
writes — triggers will handle it. Backfill is not needed: the only existing
audited mutation is one Ventra row from today's smoke test, which is already
in audit.audit_log via the explicit-write workaround. Re-running the ingest
will idempotently overwrite via on_conflict_do_update.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


AUDITED_TABLES: list[tuple[str, str]] = [
    ("masters", "physicians"),
    ("masters", "comp_agreements"),
    ("masters", "contracts"),
    ("masters", "credentials"),
    ("masters", "site_coverage"),
    ("entries", "daily_entries"),
    ("entries", "monthly_finance_manual"),
    ("entries", "weekly_clinical"),
    ("entries", "weekly_hr_manual"),
]


TRIGGER_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION audit.log_change() RETURNS TRIGGER AS $$
DECLARE
    upn TEXT;
    pk_value TEXT;
    old_json JSONB;
    new_json JSONB;
    diff_json JSONB;
BEGIN
    -- Read UPN from session GUC; default to '__system__' if unset.
    -- second arg `true` to current_setting = "missing_ok" (no error if unset).
    upn := COALESCE(NULLIF(current_setting('audit.upn', true), ''), '__system__');

    -- All audited tables have single-column 'id' PK (verified at migration time).
    IF TG_OP = 'DELETE' THEN
        pk_value := OLD.id::TEXT;
    ELSE
        pk_value := NEW.id::TEXT;
    END IF;

    IF TG_OP = 'INSERT' THEN
        new_json := to_jsonb(NEW) - 'created_at' - 'updated_at';
        diff_json := jsonb_build_object('new', new_json);

    ELSIF TG_OP = 'UPDATE' THEN
        old_json := to_jsonb(OLD) - 'created_at' - 'updated_at';
        new_json := to_jsonb(NEW) - 'created_at' - 'updated_at';

        SELECT jsonb_object_agg(
            o.key,
            jsonb_build_object('old', o.value, 'new', n.value)
        )
        INTO diff_json
        FROM jsonb_each(old_json) o
        JOIN jsonb_each(new_json) n USING (key)
        WHERE o.value IS DISTINCT FROM n.value;

        -- No real change beyond timestamps → skip the audit row entirely.
        IF diff_json IS NULL THEN
            RETURN NEW;
        END IF;

    ELSIF TG_OP = 'DELETE' THEN
        old_json := to_jsonb(OLD) - 'created_at' - 'updated_at';
        diff_json := jsonb_build_object('old', old_json);
    END IF;

    INSERT INTO audit.audit_log (
        table_schema, table_name, row_pk, action, diff, changed_by_upn, changed_at
    ) VALUES (
        TG_TABLE_SCHEMA, TG_TABLE_NAME, pk_value, TG_OP, diff_json, upn, now()
    );

    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(TRIGGER_FUNCTION_SQL)

    for schema, table in AUDITED_TABLES:
        op.execute(
            f"DROP TRIGGER IF EXISTS audit_{table}_change ON {schema}.{table};"
        )
        op.execute(
            f"CREATE TRIGGER audit_{table}_change "
            f"AFTER INSERT OR UPDATE OR DELETE ON {schema}.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION audit.log_change();"
        )


def downgrade() -> None:
    for schema, table in AUDITED_TABLES:
        op.execute(
            f"DROP TRIGGER IF EXISTS audit_{table}_change ON {schema}.{table};"
        )
    op.execute("DROP FUNCTION IF EXISTS audit.log_change();")
