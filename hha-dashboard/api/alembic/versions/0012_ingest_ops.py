"""Ops schema for ingest tracking — ingest_run + processed_files

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-11

Adds the ``ops`` schema and two tables that track every ingest-job
execution and dedupe re-deliveries of the same blob content.

  ops.ingest_run         — one row per Container Apps Job execution
                           (run_id, vendor, drop_date, status, counts,
                            error, correlation_id, timestamps)
  ops.processed_files    — dedup ledger; one row per accepted blob
                           keyed by (vendor, drop_date, file_name)
                           with a UNIQUE(vendor, sha256) for content-hash
                           dedupe of vendor re-sends.

Why a dedicated schema (per ADR-003 audit-chain principle of separating
operational/forensic state from business data):

  entries.*  — business facts. Audit triggers fire on writes.
  audit.*    — immutable audit log (write-only from triggers).
  ops.*      — operational ingest telemetry (this migration).

ops.* tables are NOT in AUDITED_TABLES — auditing-the-auditor recursion
buys nothing and grows audit.audit_log unboundedly with every ingest.

gen_random_uuid() is Postgres-13+ built-in (Postgres flex is on 16), so
no pgcrypto extension dependency.

The FK from ops.processed_files.run_id -> ops.ingest_run.run_id means
processed_files rows are tied to a real run; deleting a run cascades
no-op (ON DELETE RESTRICT by default in PG, which is what we want — we
never delete from ops.ingest_run, only insert + UPDATE status).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")

    # =====================================================================
    # ops.ingest_run — one row per Container Apps Job execution
    # =====================================================================
    op.create_table(
        "ingest_run",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("vendor", sa.Text(), nullable=False),
        sa.Column("drop_date", sa.Date(), nullable=False),
        sa.Column("manifest_path", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("files_count", sa.Integer(), nullable=True),
        sa.Column("rows_in", sa.Integer(), nullable=True),
        sa.Column("rows_out", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details", postgresql.JSONB(), nullable=True),
        sa.Column(
            "correlation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'quarantined')",
            name="ingest_run_status_valid",
        ),
        sa.CheckConstraint(
            "rows_in IS NULL OR rows_in >= 0",
            name="ingest_run_rows_in_non_negative",
        ),
        sa.CheckConstraint(
            "rows_out IS NULL OR rows_out >= 0",
            name="ingest_run_rows_out_non_negative",
        ),
        sa.CheckConstraint(
            "files_count IS NULL OR files_count >= 0",
            name="ingest_run_files_count_non_negative",
        ),
        schema="ops",
    )
    op.create_index(
        "ix_ingest_run_status_started",
        "ingest_run",
        ["status", sa.text("started_at DESC")],
        schema="ops",
    )
    op.create_index(
        "ix_ingest_run_vendor_dropdate",
        "ingest_run",
        ["vendor", "drop_date"],
        schema="ops",
    )
    op.create_index(
        "ix_ingest_run_correlation",
        "ingest_run",
        ["correlation_id"],
        schema="ops",
    )

    # =====================================================================
    # ops.processed_files — dedup ledger for vendor re-sends
    # =====================================================================
    op.create_table(
        "processed_files",
        sa.Column("vendor", sa.Text(), nullable=False),
        sa.Column("drop_date", sa.Date(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("blob_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "vendor", "drop_date", "file_name", name="pk_processed_files"
        ),
        sa.UniqueConstraint(
            "vendor", "sha256", name="uq_processed_files_vendor_sha"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ops.ingest_run.run_id"],
            name="fk_processed_files_run_id",
        ),
        sa.CheckConstraint(
            "row_count >= 0", name="processed_files_row_count_non_negative"
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="processed_files_sha256_format",
        ),
        schema="ops",
    )
    op.create_index(
        "ix_processed_files_run_id",
        "processed_files",
        ["run_id"],
        schema="ops",
    )
    op.create_index(
        "ix_processed_files_processed_at",
        "processed_files",
        ["processed_at"],
        schema="ops",
    )


def downgrade() -> None:
    op.drop_table("processed_files", schema="ops")
    op.drop_table("ingest_run", schema="ops")
    op.execute("DROP SCHEMA IF EXISTS ops")
