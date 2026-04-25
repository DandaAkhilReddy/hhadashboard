"""monthly_finance_manual table

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-25

Adds entries.monthly_finance_manual — Sandy Collins's monthly entry table.
One row per (year, month, state). FL is fallback until Ventra SFTP lands;
TX stays manual indefinitely per the FL-only Ventra scope decision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monthly_finance_manual",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("period_first", sa.Date(), nullable=False),
        sa.Column("state", sa.String(2), nullable=False),
        sa.Column("collections_usd", sa.Numeric(14, 2), nullable=False),
        sa.Column("ventra_fee_usd", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("ar_total_usd", sa.Numeric(14, 2), nullable=False),
        sa.Column("ar_0_30_usd", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("ar_31_60_usd", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("ar_61_90_usd", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("ar_91_120_usd", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("ar_over_120_usd", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("net_collection_rate_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("days_in_ar", sa.Numeric(6, 2), nullable=False),
        sa.Column("source_system", sa.String(30), nullable=False),
        sa.Column("entered_by_upn", sa.String(200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
            "year", "month", "state", name="one_finance_per_month_per_state"
        ),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="month_valid"),
        sa.CheckConstraint("year BETWEEN 2020 AND 2100", name="year_valid"),
        sa.CheckConstraint("state IN ('FL', 'TX')", name="state_valid"),
        sa.CheckConstraint(
            "source_system IN ('VENTRA_FL_FALLBACK', 'HHA_TX_MANUAL')",
            name="source_system_valid",
        ),
        sa.CheckConstraint("collections_usd >= 0", name="collections_non_negative"),
        sa.CheckConstraint("ar_total_usd >= 0", name="ar_total_non_negative"),
        sa.CheckConstraint(
            "net_collection_rate_pct BETWEEN 0 AND 100", name="ncr_in_range"
        ),
        sa.CheckConstraint("days_in_ar >= 0", name="days_in_ar_non_negative"),
        schema="entries",
    )
    op.create_index(
        "ix_monthly_finance_year_month",
        "monthly_finance_manual",
        ["year", "month"],
        schema="entries",
    )
    op.create_index(
        "ix_monthly_finance_state",
        "monthly_finance_manual",
        ["state"],
        schema="entries",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_monthly_finance_state",
        table_name="monthly_finance_manual",
        schema="entries",
    )
    op.drop_index(
        "ix_monthly_finance_year_month",
        table_name="monthly_finance_manual",
        schema="entries",
    )
    op.drop_table("monthly_finance_manual", schema="entries")
