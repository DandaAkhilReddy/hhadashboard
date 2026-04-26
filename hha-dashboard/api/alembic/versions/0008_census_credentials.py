"""auth schema + census_credentials table

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-26

Why
---
The census-entry workflow runs through a SEPARATE portal (`/census/*`),
NOT through the Entra-gated dashboard. Crystal — or whoever covers ops on
a given day — types the 11 daily site counts on a stripped-down, write-only
surface that has no read access to the dashboard. See the Standing Facts
section of `.claude/plans/so-now-we-are-nested-grove.md` (F2).

The portal has exactly ONE shared credential, by design (the user said so:
"ONLY ONE CREDENTIALS ONE LOGIN"). Multi-tenant the portal becomes is a
follow-up. So the table is enforced single-row via `CHECK (id = 1)`.

Single-session lock is implemented via the `active_session_token` column:
on every successful login, the token is rewritten, so any prior browser's
cookie no longer matches and gets bounced on its next request. Two
simultaneous logins → second login boots the first. No session table
needed.

The schema is a fresh `auth` schema, kept separate from `masters` etc. so
RBAC at the database level can grant/revoke access to credential rows
without touching operational tables.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")

    op.create_table(
        "census_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column("active_session_token", sa.String(64)),
        sa.Column("active_session_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "failed_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
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
        sa.CheckConstraint("id = 1", name="ck_census_credentials_single_row"),
        sa.CheckConstraint(
            "failed_attempts >= 0", name="ck_census_credentials_attempts_non_negative"
        ),
        sa.UniqueConstraint("email", name="uq_census_credentials_email"),
        schema="auth",
    )


def downgrade() -> None:
    op.drop_table("census_credentials", schema="auth")
    op.execute("DROP SCHEMA IF EXISTS auth CASCADE")
