"""weekly_clinical table

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-25

Adds entries.weekly_clinical — Dr. Aneja / Dr. Reddy's weekly chart-audit
rollup. One row per (week_ending, state).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weekly_clinical",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("week_ending", sa.Date(), nullable=False),
        sa.Column("state", sa.String(2), nullable=False),
        sa.Column("hp_24h_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("dc_48h_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("avg_los_days", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "charts_audited_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("entered_by_upn", sa.String(200), nullable=False),
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
            "week_ending", "state", name="one_clinical_per_week_per_state"
        ),
        sa.CheckConstraint("state IN ('FL', 'TX')", name="state_valid"),
        sa.CheckConstraint("hp_24h_pct BETWEEN 0 AND 100", name="hp_24h_pct_in_range"),
        sa.CheckConstraint("dc_48h_pct BETWEEN 0 AND 100", name="dc_48h_pct_in_range"),
        sa.CheckConstraint("avg_los_days >= 0", name="avg_los_non_negative"),
        sa.CheckConstraint("avg_los_days <= 60", name="avg_los_sanity_cap"),
        sa.CheckConstraint(
            "charts_audited_count >= 0", name="charts_audited_non_negative"
        ),
        schema="entries",
    )
    op.create_index(
        "ix_weekly_clinical_week_ending",
        "weekly_clinical",
        ["week_ending"],
        schema="entries",
    )
    op.create_index(
        "ix_weekly_clinical_state",
        "weekly_clinical",
        ["state"],
        schema="entries",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_weekly_clinical_state",
        table_name="weekly_clinical",
        schema="entries",
    )
    op.drop_index(
        "ix_weekly_clinical_week_ending",
        table_name="weekly_clinical",
        schema="entries",
    )
    op.drop_table("weekly_clinical", schema="entries")
