"""Ventra pre-aggregated fact tables — collections daily, AR snapshot, physician monthly

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-11

Adds three Tier-A fact tables for the Ventra ingestion pipeline per ADR-006.
Receives pre-aggregated CSVs from Ventra (zero PHI on the wire by design;
the row-level Standard Data Extract is rejected per the architecture lock).

Tables created (all in schema ``entries``):

  fact_collections_daily          — one row per (date, facility_no, payer_class)
  fact_ar_snapshot                 — one row per (snapshot_date, facility_no, aging_bucket)
  fact_revenue_by_physician_mo     — one row per (month, physician_npi, facility_no)

Invariants enforced at the DB layer (defense in depth — app code also validates
via V1-V14 in jobs/ventra_ingest/validators.py):

  source_system = 'VENTRA_FL_ATHENA'        (ADR-005 — Ventra is FL-only)
  state          = 'FL'                      (ADR-005 — runtime invariant)
  payer_class    ∈ {commercial, medicare, medicaid, selfpay, other}
  aging_bucket   ∈ {0-30, 31-60, 61-90, 91-120, 120+, credit}
  physician_npi  ~ '^[0-9]{10}$'             (10-digit NPI)
  month          = first-of-month            (physician monthly grain)
  outstanding    ≥ 0 unless aging_bucket = 'credit'

No PHI columns by construction — the schema is Tier-A per ADR-001. The CI
test ``tests/test_schema_classification.py`` rejects any column matching the
forbidden-names list (claim_id, patient_*, mrn, dob, etc.).

The ``ingest_run_id`` column on every row traces back to ``ops.ingest_run.run_id``
(migration 0012) for forensic queries — stored as UUID with no FK to keep the
schemas independently evolvable; FK-equivalent integrity is enforced at app
level in jobs/ventra_ingest/ingest.py.

Audit triggers from migration 0007's ``audit.log_change()`` function are
attached to all three tables — every INSERT/UPDATE/DELETE writes to
``audit.audit_log`` automatically. ``app/services/audit.py::AUDITED_TABLES``
is updated in the same commit to reflect coverage.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Tables added to audit coverage in this migration. Mirrors the additions to
# app/services/audit.py::AUDITED_TABLES — keep in sync.
VENTRA_FACT_TABLES: list[str] = [
    "fact_collections_daily",
    "fact_ar_snapshot",
    "fact_revenue_by_physician_mo",
]


def upgrade() -> None:
    # =====================================================================
    # fact_collections_daily
    # =====================================================================
    op.create_table(
        "fact_collections_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("facility_no", sa.Integer(), nullable=False),
        sa.Column("payer_class", sa.String(20), nullable=False),
        sa.Column("gross_charges", sa.Numeric(18, 2), nullable=False),
        sa.Column("payments_received", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "contractual_adjustments",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "write_offs", sa.Numeric(18, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "payer_refunds", sa.Numeric(18, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "patient_refunds", sa.Numeric(18, 2), nullable=False, server_default="0"
        ),
        sa.Column("net_revenue", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "source_system",
            sa.String(30),
            nullable=False,
            server_default="VENTRA_FL_ATHENA",
        ),
        sa.Column("state", sa.CHAR(2), nullable=False, server_default="FL"),
        sa.Column(
            "ingest_run_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "date",
            "facility_no",
            "payer_class",
            name="uq_collections_daily_natural",
        ),
        sa.CheckConstraint(
            "payer_class IN ('commercial', 'medicare', 'medicaid', 'selfpay', 'other')",
            name="collections_payer_class_valid",
        ),
        sa.CheckConstraint(
            "gross_charges >= 0", name="collections_gross_charges_non_negative"
        ),
        sa.CheckConstraint(
            "payments_received >= 0",
            name="collections_payments_received_non_negative",
        ),
        sa.CheckConstraint(
            "source_system = 'VENTRA_FL_ATHENA'",
            name="collections_source_system_locked",
        ),
        sa.CheckConstraint("state = 'FL'", name="collections_state_fl_only"),
        schema="entries",
    )
    op.create_index(
        "ix_fact_collections_daily_date",
        "fact_collections_daily",
        ["date"],
        schema="entries",
    )
    op.create_index(
        "ix_fact_collections_daily_facility",
        "fact_collections_daily",
        ["facility_no"],
        schema="entries",
    )
    op.create_index(
        "ix_fact_collections_daily_ingest_run",
        "fact_collections_daily",
        ["ingest_run_id"],
        schema="entries",
    )

    # =====================================================================
    # fact_ar_snapshot
    # =====================================================================
    op.create_table(
        "fact_ar_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("facility_no", sa.Integer(), nullable=False),
        sa.Column("aging_bucket", sa.String(10), nullable=False),
        sa.Column("outstanding_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "source_system",
            sa.String(30),
            nullable=False,
            server_default="VENTRA_FL_ATHENA",
        ),
        sa.Column("state", sa.CHAR(2), nullable=False, server_default="FL"),
        sa.Column(
            "ingest_run_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "snapshot_date",
            "facility_no",
            "aging_bucket",
            name="uq_ar_snapshot_natural",
        ),
        sa.CheckConstraint(
            "aging_bucket IN ('0-30', '31-60', '61-90', '91-120', '120+', 'credit')",
            name="ar_aging_bucket_valid",
        ),
        sa.CheckConstraint(
            "aging_bucket = 'credit' OR outstanding_amount >= 0",
            name="ar_outstanding_non_negative_except_credit",
        ),
        sa.CheckConstraint(
            "source_system = 'VENTRA_FL_ATHENA'",
            name="ar_source_system_locked",
        ),
        sa.CheckConstraint("state = 'FL'", name="ar_state_fl_only"),
        schema="entries",
    )
    op.create_index(
        "ix_fact_ar_snapshot_date",
        "fact_ar_snapshot",
        ["snapshot_date"],
        schema="entries",
    )
    op.create_index(
        "ix_fact_ar_snapshot_facility",
        "fact_ar_snapshot",
        ["facility_no"],
        schema="entries",
    )
    op.create_index(
        "ix_fact_ar_snapshot_ingest_run",
        "fact_ar_snapshot",
        ["ingest_run_id"],
        schema="entries",
    )

    # =====================================================================
    # fact_revenue_by_physician_mo
    # =====================================================================
    op.create_table(
        "fact_revenue_by_physician_mo",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("physician_npi", sa.String(10), nullable=False),
        sa.Column("facility_no", sa.Integer(), nullable=False),
        sa.Column("encounters_count", sa.Integer(), nullable=False),
        sa.Column(
            "total_rvu", sa.Numeric(9, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "total_work_rvu", sa.Numeric(9, 2), nullable=False, server_default="0"
        ),
        sa.Column("revenue_attributed", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "source_system",
            sa.String(30),
            nullable=False,
            server_default="VENTRA_FL_ATHENA",
        ),
        sa.Column("state", sa.CHAR(2), nullable=False, server_default="FL"),
        sa.Column(
            "ingest_run_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "month",
            "physician_npi",
            "facility_no",
            name="uq_revenue_physician_mo_natural",
        ),
        sa.CheckConstraint(
            "physician_npi ~ '^[0-9]{10}$'",
            name="physician_mo_npi_10_digit",
        ),
        sa.CheckConstraint(
            "month = date_trunc('month', month)::date",
            name="physician_mo_month_is_first_of_month",
        ),
        sa.CheckConstraint(
            "encounters_count >= 0",
            name="physician_mo_encounters_non_negative",
        ),
        sa.CheckConstraint(
            "total_rvu >= 0", name="physician_mo_total_rvu_non_negative"
        ),
        sa.CheckConstraint(
            "total_work_rvu >= 0",
            name="physician_mo_total_work_rvu_non_negative",
        ),
        sa.CheckConstraint(
            "source_system = 'VENTRA_FL_ATHENA'",
            name="physician_mo_source_system_locked",
        ),
        sa.CheckConstraint("state = 'FL'", name="physician_mo_state_fl_only"),
        schema="entries",
    )
    op.create_index(
        "ix_fact_physician_mo_month",
        "fact_revenue_by_physician_mo",
        ["month"],
        schema="entries",
    )
    op.create_index(
        "ix_fact_physician_mo_npi",
        "fact_revenue_by_physician_mo",
        ["physician_npi"],
        schema="entries",
    )
    op.create_index(
        "ix_fact_physician_mo_ingest_run",
        "fact_revenue_by_physician_mo",
        ["ingest_run_id"],
        schema="entries",
    )

    # =====================================================================
    # Attach audit.log_change() triggers from migration 0007.
    # Every INSERT/UPDATE/DELETE on these tables will write an audit row.
    # =====================================================================
    for table_name in VENTRA_FACT_TABLES:
        op.execute(
            f"DROP TRIGGER IF EXISTS audit_{table_name}_change "
            f"ON entries.{table_name};"
        )
        op.execute(
            f"CREATE TRIGGER audit_{table_name}_change "
            f"AFTER INSERT OR UPDATE OR DELETE ON entries.{table_name} "
            f"FOR EACH ROW EXECUTE FUNCTION audit.log_change();"
        )


def downgrade() -> None:
    for table_name in VENTRA_FACT_TABLES:
        op.execute(
            f"DROP TRIGGER IF EXISTS audit_{table_name}_change "
            f"ON entries.{table_name};"
        )
    op.drop_table("fact_revenue_by_physician_mo", schema="entries")
    op.drop_table("fact_ar_snapshot", schema="entries")
    op.drop_table("fact_collections_daily", schema="entries")
