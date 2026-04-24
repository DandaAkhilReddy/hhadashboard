"""entries + audit + uploads schemas

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-23

Adds three tables across three schemas:
  entries.daily_entries  — manual + auto-extracted daily census per site
  audit.audit_log        — immutable diff log of sensitive-table mutations
  uploads.upload_log     — the cron job's work queue for ingesting files
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---------- entries.daily_entries ----------
    op.create_table(
        "daily_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "site_id",
            sa.Integer(),
            sa.ForeignKey(
                "masters.sites.id",
                name="fk_daily_entries_site_id_sites",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("census", sa.Integer(), nullable=False),
        sa.Column("open_shifts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("entered_by_upn", sa.String(200), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("pdf_sha256", sa.String(64)),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("census >= 0", name="ck_daily_entries_census_non_negative"),
        sa.CheckConstraint(
            "open_shifts >= 0", name="ck_daily_entries_open_shifts_non_negative"
        ),
        sa.UniqueConstraint(
            "site_id", "entry_date", name="one_entry_per_site_per_day"
        ),
        schema="entries",
    )

    op.create_index(
        "ix_daily_entries_entry_date",
        "daily_entries",
        ["entry_date"],
        schema="entries",
    )

    # ---------- audit.audit_log ----------
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("table_schema", sa.String(63), nullable=False),
        sa.Column("table_name", sa.String(63), nullable=False),
        sa.Column("row_pk", sa.String(200), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column(
            "diff",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("changed_by_upn", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="audit",
    )

    op.create_index(
        "ix_audit_log_changed_at", "audit_log", ["changed_at"], schema="audit"
    )
    op.create_index(
        "ix_audit_log_table_row",
        "audit_log",
        ["table_schema", "table_name", "row_pk"],
        schema="audit",
    )
    op.create_index(
        "ix_audit_log_changed_by_upn",
        "audit_log",
        ["changed_by_upn"],
        schema="audit",
    )

    # ---------- uploads.upload_log ----------
    op.execute("CREATE SCHEMA IF NOT EXISTS uploads")

    op.create_table(
        "upload_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("uploaded_by_upn", sa.String(200), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("file_type", sa.String(30), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("blob_name", sa.String(1000), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="uploaded"
        ),
        sa.Column("processing_started_at", sa.DateTime(timezone=True)),
        sa.Column("processing_finished_at", sa.DateTime(timezone=True)),
        sa.Column("rows_written", sa.Integer()),
        sa.Column("error_message", sa.Text()),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "status IN ('uploaded', 'processing', 'processed', 'error', 'expired')",
            name="ck_upload_log_status_valid",
        ),
        sa.CheckConstraint(
            "size_bytes >= 0", name="ck_upload_log_size_non_negative"
        ),
        sa.CheckConstraint(
            "retry_count >= 0", name="ck_upload_log_retry_count_non_negative"
        ),
        schema="uploads",
    )

    op.create_index(
        "ix_upload_log_status_uploaded_at",
        "upload_log",
        ["status", "uploaded_at"],
        schema="uploads",
    )
    op.create_index(
        "ix_upload_log_uploaded_by_upn",
        "upload_log",
        ["uploaded_by_upn"],
        schema="uploads",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_upload_log_uploaded_by_upn", table_name="upload_log", schema="uploads"
    )
    op.drop_index(
        "ix_upload_log_status_uploaded_at",
        table_name="upload_log",
        schema="uploads",
    )
    op.drop_table("upload_log", schema="uploads")

    op.drop_index(
        "ix_audit_log_changed_by_upn", table_name="audit_log", schema="audit"
    )
    op.drop_index("ix_audit_log_table_row", table_name="audit_log", schema="audit")
    op.drop_index("ix_audit_log_changed_at", table_name="audit_log", schema="audit")
    op.drop_table("audit_log", schema="audit")

    op.drop_index(
        "ix_daily_entries_entry_date",
        table_name="daily_entries",
        schema="entries",
    )
    op.drop_table("daily_entries", schema="entries")
