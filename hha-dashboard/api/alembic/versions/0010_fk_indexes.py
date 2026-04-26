"""missing FK indexes on masters.{contracts,credentials,site_coverage}

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-26

Why
---
0001_initial.py created tables with foreign key constraints but no indexes
on the FK columns. Postgres does NOT auto-index FK columns. Three hot read
paths table-scan as a result:

- `masters.site_coverage` — joined on `site_id` (operations site detail
  page) and on `physician_id` (scorecard build). Both FKs unindexed.
- `masters.contracts` — joined on `site_id` (operations / finance reads).
- `masters.credentials` — joined on `hospital_id` (cred_scan cron joins
  per credential). Existing index covers `expires_on` only.

At HHA scale (11 sites, ~50 physicians) table scans are micros. As soon as
Paycom sync writes 200+ employees per night and history accumulates, scans
get expensive — adding the indexes now is defensive, cheap, and removes a
class of "why is this slow at month 6" surprises.

Uses CREATE INDEX IF NOT EXISTS so the migration is safe to re-run if a
prior partial-apply already added some.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_site_coverage_site_id",
        "site_coverage",
        ["site_id"],
        schema="masters",
        if_not_exists=True,
    )
    op.create_index(
        "ix_site_coverage_physician_id",
        "site_coverage",
        ["physician_id"],
        schema="masters",
        if_not_exists=True,
    )
    op.create_index(
        "ix_contracts_site_id",
        "contracts",
        ["site_id"],
        schema="masters",
        if_not_exists=True,
    )
    op.create_index(
        "ix_credentials_hospital_id",
        "credentials",
        ["hospital_id"],
        schema="masters",
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_credentials_hospital_id",
        table_name="credentials",
        schema="masters",
        if_exists=True,
    )
    op.drop_index(
        "ix_contracts_site_id",
        table_name="contracts",
        schema="masters",
        if_exists=True,
    )
    op.drop_index(
        "ix_site_coverage_physician_id",
        table_name="site_coverage",
        schema="masters",
        if_exists=True,
    )
    op.drop_index(
        "ix_site_coverage_site_id",
        table_name="site_coverage",
        schema="masters",
        if_exists=True,
    )
