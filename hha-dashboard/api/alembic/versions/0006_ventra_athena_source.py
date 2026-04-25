"""extend monthly_finance_manual.source_system to include VENTRA_FL_ATHENA

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-25

When the Ventra SFTP / Athena pipeline lands, FL rows get tagged with a new
provenance value `VENTRA_FL_ATHENA` (the auto-ingested path) so the UI can
distinguish them from `VENTRA_FL_FALLBACK` rows that Sandy still types in by
hand. TX stays `HHA_TX_MANUAL`.

This is a CHECK-constraint swap — drop the old, add the new — no data move.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Raw SQL — Alembic's naming_convention double-prefixes if we use op.drop_constraint
    op.execute(
        "ALTER TABLE entries.monthly_finance_manual "
        "DROP CONSTRAINT ck_monthly_finance_manual_source_system_valid"
    )
    op.create_check_constraint(
        "source_system_valid",
        "monthly_finance_manual",
        "source_system IN ('VENTRA_FL_ATHENA', 'VENTRA_FL_FALLBACK', 'HHA_TX_MANUAL')",
        schema="entries",
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE entries.monthly_finance_manual "
        "DROP CONSTRAINT ck_monthly_finance_manual_source_system_valid"
    )
    op.create_check_constraint(
        "source_system_valid",
        "monthly_finance_manual",
        "source_system IN ('VENTRA_FL_FALLBACK', 'HHA_TX_MANUAL')",
        schema="entries",
    )
