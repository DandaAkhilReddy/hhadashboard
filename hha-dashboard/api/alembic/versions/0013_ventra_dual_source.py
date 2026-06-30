"""Ventra hybrid: dual-source provenance + reconciliation table

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-25

Activates the **hybrid Ventra pipeline** decided 2026-05-29 (Dinesh confirmed
Hybrid Option after Gilda's 3-option proposal). Two parallel ingest paths
land in the same 3 fact tables, tagged by ``source_system``:

  ``VENTRA_FL_PREAGG``        — Ventra's pre-aggregated extract per HHA's
                                spec (Option 2 / ADR-006 / zero PHI on wire).
                                The migration retags the existing single
                                allowed value ``VENTRA_FL_ATHENA`` to this.

  ``VENTRA_FL_STDSPEC_AGG``   — HHA's in-memory aggregation of Ventra's
                                row-level Standard Data Extract (Option 1
                                / contains PHI on wire / four-layer V15
                                denylist enforced; zero PHI ever reaches
                                this table — only the aggregates).

The natural-key UNIQUE constraint on each fact table is widened to include
``source_system`` so the two paths coexist per (date, facility, payer)
tuple. The surrogate ``id INTEGER`` primary key stays. The reconciliation
job in ``jobs/ventra_reconcile/`` joins the two rows per tuple, computes
the variance, and writes one row per tuple to ``entries.ventra_recon``.

Schema changes (in order — relaxation must precede the UPDATE):

  1. Drop the ``*_source_system_locked`` CHECK constraints on the 3 fact
     tables (they previously locked ``source_system = 'VENTRA_FL_ATHENA'``).
  2. UPDATE existing rows from ``VENTRA_FL_ATHENA`` → ``VENTRA_FL_PREAGG``.
  3. Add new ``*_source_system_dual`` CHECK constraints accepting either of
     the two new values (the old value is fully retired).
  4. Drop the natural-key UNIQUE constraints and re-add them with the
     ``source_system`` column appended.
  5. Drop the ``server_default = 'VENTRA_FL_ATHENA'`` (app code now sets
     the tag explicitly per pipeline; no migration default would be
     correct).
  6. Create ``entries.ventra_recon`` for the daily reconciliation harness
     and attach the standard ``audit.log_change()`` trigger.

Downgrade reverses every step including reverting any
``VENTRA_FL_STDSPEC_AGG`` row's tag back to ``VENTRA_FL_PREAGG`` so the
restored single-value CHECK is satisfiable. Stdspec rows are NOT
deleted in downgrade — the operator decides whether to clean them out
manually after pinning down whatever forced the rollback.

The ``state = 'FL'`` CHECK is unchanged: both paths are FL-only (ADR-005).
The ``ingest_run_id`` linkage is unchanged. Audit triggers from 0007
remain attached to the existing 3 fact tables.

Per ADR-001: zero ``data_class: C`` columns added. ``ventra_recon`` is
Tier-A aggregates only (Decimal money amounts, the natural-key tuple,
and a tier label). No PHI columns by construction; the CI test
``tests/test_schema_classification.py`` enforces.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# Constant tuples used by both upgrade() and downgrade() to stay symmetric.
# ---------------------------------------------------------------------------

# (table_name, old_check_name, new_check_name, old_unique_name, natural_key_cols)
FACT_TABLES: list[tuple[str, str, str, str, list[str]]] = [
    (
        "fact_collections_daily",
        "collections_source_system_locked",
        "collections_source_system_dual",
        "uq_collections_daily_natural",
        ["date", "facility_no", "payer_class"],
    ),
    (
        "fact_ar_snapshot",
        "ar_source_system_locked",
        "ar_source_system_dual",
        "uq_ar_snapshot_natural",
        ["snapshot_date", "facility_no", "aging_bucket"],
    ),
    (
        "fact_revenue_by_physician_mo",
        "physician_mo_source_system_locked",
        "physician_mo_source_system_dual",
        "uq_revenue_physician_mo_natural",
        ["month", "physician_npi", "facility_no"],
    ),
]

OLD_VALUE = "VENTRA_FL_ATHENA"
PREAGG_VALUE = "VENTRA_FL_PREAGG"
STDSPEC_VALUE = "VENTRA_FL_STDSPEC_AGG"
DUAL_CHECK_EXPR = (
    f"source_system IN ('{PREAGG_VALUE}', '{STDSPEC_VALUE}')"
)


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. Drop the locked-to-single-value CHECK constraints on the 3 fact
    #    tables. Must precede the UPDATE — Postgres would otherwise reject
    #    the new value as a CHECK violation.
    # -----------------------------------------------------------------------
    for table_name, old_check, _, _, _ in FACT_TABLES:
        op.drop_constraint(old_check, table_name, type_="check", schema="entries")

    # -----------------------------------------------------------------------
    # 2. Retag every existing row's source_system from the old single value
    #    to VENTRA_FL_PREAGG. This is bounded — only the pre-aggregated path
    #    has ever written rows up to this point (PR #54 was gated behind
    #    enable_sftp=false; the only data here is what's been ingested
    #    against dev).
    # -----------------------------------------------------------------------
    for table_name, _, _, _, _ in FACT_TABLES:
        op.execute(
            sa.text(
                f"UPDATE entries.{table_name} "
                f"SET source_system = :new_value "
                f"WHERE source_system = :old_value"
            ).bindparams(new_value=PREAGG_VALUE, old_value=OLD_VALUE)
        )

    # -----------------------------------------------------------------------
    # 3. Add the dual-value CHECK constraints. Both VENTRA_FL_PREAGG and
    #    VENTRA_FL_STDSPEC_AGG are now legal; the old VENTRA_FL_ATHENA tag
    #    is fully retired (no row carries it after step 2; no new row may
    #    insert it after this step).
    # -----------------------------------------------------------------------
    for table_name, _, new_check, _, _ in FACT_TABLES:
        op.create_check_constraint(
            new_check,
            table_name,
            DUAL_CHECK_EXPR,
            schema="entries",
        )

    # -----------------------------------------------------------------------
    # 4. Replace the natural-key UNIQUE constraints with widened versions
    #    that include source_system. Both pipelines can now write their own
    #    row per (date, facility, payer) tuple without conflicting; the
    #    reconciliation job joins on the natural key minus source_system.
    # -----------------------------------------------------------------------
    for table_name, _, _, old_unique, natural_cols in FACT_TABLES:
        op.drop_constraint(old_unique, table_name, type_="unique", schema="entries")
        op.create_unique_constraint(
            old_unique,
            table_name,
            [*natural_cols, "source_system"],
            schema="entries",
        )

    # -----------------------------------------------------------------------
    # 5. Drop the server_default. Neither pipeline can rely on a default —
    #    the stdspec path must explicitly set VENTRA_FL_STDSPEC_AGG, the
    #    preagg path must explicitly set VENTRA_FL_PREAGG. Forcing the
    #    explicit set in app code prevents a silent default-wins bug.
    # -----------------------------------------------------------------------
    for table_name, _, _, _, _ in FACT_TABLES:
        op.alter_column(
            table_name,
            "source_system",
            server_default=None,
            schema="entries",
        )

    # -----------------------------------------------------------------------
    # 6. Reconciliation table — one row per (drop_date, facility, payer)
    #    written by jobs/ventra_reconcile/. Stores both amounts + the
    #    computed diff + a tiered label (match / minor / drift). Audit
    #    trigger attached so any out-of-band manipulation is captured.
    # -----------------------------------------------------------------------
    op.create_table(
        "ventra_recon",
        sa.Column("drop_date", sa.Date(), nullable=False),
        sa.Column("facility_no", sa.Integer(), nullable=False),
        sa.Column("payer_class", sa.String(20), nullable=False),
        sa.Column("stdspec_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("preagg_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "diff",
            sa.Numeric(18, 2),
            sa.Computed(
                "stdspec_amount - preagg_amount",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("tier", sa.String(10), nullable=False),
        sa.Column(
            "reconciled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "drop_date",
            "facility_no",
            "payer_class",
            name="pk_ventra_recon",
        ),
        sa.CheckConstraint(
            "tier IN ('match', 'minor', 'drift')",
            name="ventra_recon_tier_valid",
        ),
        sa.CheckConstraint(
            "payer_class IN ('commercial', 'medicare', 'medicaid', 'selfpay', 'other')",
            name="ventra_recon_payer_class_valid",
        ),
        schema="entries",
    )
    op.create_index(
        "ix_ventra_recon_drop_date",
        "ventra_recon",
        ["drop_date"],
        schema="entries",
    )
    op.create_index(
        "ix_ventra_recon_tier",
        "ventra_recon",
        ["tier"],
        schema="entries",
    )

    # Attach audit trigger using the same pattern as 0011.
    op.execute(
        "DROP TRIGGER IF EXISTS audit_ventra_recon_change ON entries.ventra_recon;"
    )
    op.execute(
        "CREATE TRIGGER audit_ventra_recon_change "
        "AFTER INSERT OR UPDATE OR DELETE ON entries.ventra_recon "
        "FOR EACH ROW EXECUTE FUNCTION audit.log_change();"
    )


def downgrade() -> None:
    # -----------------------------------------------------------------------
    # Reverse step 6: drop reconciliation table + its trigger.
    # -----------------------------------------------------------------------
    op.execute(
        "DROP TRIGGER IF EXISTS audit_ventra_recon_change ON entries.ventra_recon;"
    )
    op.drop_table("ventra_recon", schema="entries")

    # -----------------------------------------------------------------------
    # Reverse step 5: restore the server_default to the (now-restored)
    # single legal value. This happens BEFORE the CHECK is re-tightened so
    # the schema is consistent at every intermediate state.
    # -----------------------------------------------------------------------
    for table_name, _, _, _, _ in FACT_TABLES:
        op.alter_column(
            table_name,
            "source_system",
            server_default=OLD_VALUE,
            schema="entries",
        )

    # -----------------------------------------------------------------------
    # Reverse step 4: narrow the UNIQUE constraints back to the natural key
    # without source_system.
    # -----------------------------------------------------------------------
    for table_name, _, _, old_unique, natural_cols in FACT_TABLES:
        op.drop_constraint(old_unique, table_name, type_="unique", schema="entries")
        op.create_unique_constraint(
            old_unique,
            table_name,
            natural_cols,
            schema="entries",
        )

    # -----------------------------------------------------------------------
    # Reverse step 3: drop the dual-value CHECK constraints.
    # -----------------------------------------------------------------------
    for table_name, _, new_check, _, _ in FACT_TABLES:
        op.drop_constraint(new_check, table_name, type_="check", schema="entries")

    # -----------------------------------------------------------------------
    # Reverse step 2: retag VENTRA_FL_PREAGG rows back to the legacy value
    # so the about-to-be-restored locked CHECK is satisfiable. Stdspec rows
    # cannot be retagged (no legacy equivalent exists) — they would violate
    # the restored CHECK. We refuse the downgrade if any are present.
    # -----------------------------------------------------------------------
    for table_name, _, _, _, _ in FACT_TABLES:
        # NOTE: a PL/pgSQL ``DO $$ ... $$`` block accepts NO bind parameters
        # (the body is opaque to the driver), so ``:stdspec_value`` would raise
        # IndeterminateDatatype ("could not determine data type of parameter
        # $1"). STDSPEC_VALUE is a fixed code constant (not user input), so we
        # inline it as a quoted SQL literal — safe, no injection surface.
        op.execute(
            sa.text(
                f"DO $$ "
                f"DECLARE stdspec_count INT; "
                f"BEGIN "
                f"  SELECT COUNT(*) INTO stdspec_count "
                f"  FROM entries.{table_name} "
                f"  WHERE source_system = '{STDSPEC_VALUE}'; "
                f"  IF stdspec_count > 0 THEN "
                f"    RAISE EXCEPTION 'Cannot downgrade: % stdspec-tagged rows present in entries.{table_name}; "
                f"manual cleanup required before downgrade', stdspec_count; "
                f"  END IF; "
                f"END $$;"
            )
        )
        op.execute(
            sa.text(
                f"UPDATE entries.{table_name} "
                f"SET source_system = :old_value "
                f"WHERE source_system = :preagg_value"
            ).bindparams(old_value=OLD_VALUE, preagg_value=PREAGG_VALUE)
        )

    # -----------------------------------------------------------------------
    # Reverse step 1: re-add the original locked CHECK constraints.
    # -----------------------------------------------------------------------
    for table_name, old_check, _, _, _ in FACT_TABLES:
        op.create_check_constraint(
            old_check,
            table_name,
            f"source_system = '{OLD_VALUE}'",
            schema="entries",
        )
