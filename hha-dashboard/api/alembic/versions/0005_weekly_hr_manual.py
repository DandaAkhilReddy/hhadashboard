"""weekly_hr_manual table

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-25

Adds entries.weekly_hr_manual — Andrea's weekly HR rollup. One row per
week_ending. HHA-wide (not state-split).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weekly_hr_manual",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("week_ending", sa.Date(), nullable=False),
        sa.Column("headcount_w2", sa.Integer(), nullable=False),
        sa.Column("headcount_1099", sa.Integer(), nullable=False),
        sa.Column(
            "open_positions_total", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "terminations_90d_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "below_fmv_count", sa.Integer(), nullable=False, server_default="0"
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
        sa.UniqueConstraint("week_ending", name="one_hr_per_week"),
        sa.CheckConstraint("headcount_w2 >= 0", name="headcount_w2_non_negative"),
        sa.CheckConstraint("headcount_1099 >= 0", name="headcount_1099_non_negative"),
        sa.CheckConstraint(
            "open_positions_total >= 0", name="open_positions_non_negative"
        ),
        sa.CheckConstraint(
            "terminations_90d_count >= 0", name="terminations_non_negative"
        ),
        sa.CheckConstraint("below_fmv_count >= 0", name="below_fmv_non_negative"),
        schema="entries",
    )
    op.create_index(
        "ix_weekly_hr_week_ending",
        "weekly_hr_manual",
        ["week_ending"],
        schema="entries",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_weekly_hr_week_ending", table_name="weekly_hr_manual", schema="entries"
    )
    op.drop_table("weekly_hr_manual", schema="entries")
