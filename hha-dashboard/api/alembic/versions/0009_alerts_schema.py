"""alerts schema — subscriptions + alert_log + credential_alert_log

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-26

Three tables under the existing `alerts` schema (created in 0001):

- `alerts.alert_subscriptions` — who gets which alert categories at which
  frequency. Seeded by `infra/seed_alert_subscriptions.sh`, NOT user-managed
  yet (admin UI is a follow-up).
- `alerts.alert_log` — idempotency record. One row per
  (alert_id, target_date, recipient_email). The cron checks this BEFORE
  sending, so re-running the digest on the same day sends nothing new.
- `alerts.credential_alert_log` — one row per
  (credential_id, threshold_band) where band ∈ {30, 60, 90}. Prevents
  daily spam — only re-fires when the credential crosses to a tighter band.

Per ADR-001:
- email is Tier B (directory)
- alert title/detail/owner strings are Tier A (operational, no PHI)
- credential_id is Tier A (FK to a Tier B record, but the FK itself is just an int)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `alerts` schema was created in 0001_initial.py — no need to recreate.

    # ---------- alerts.alert_subscriptions ----------
    op.create_table(
        "alert_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("email", sa.String(200), nullable=False),
        sa.Column(
            "categories",
            sa.ARRAY(sa.String(40)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "frequency",
            sa.String(20),
            nullable=False,
            server_default="daily",
        ),
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
        sa.CheckConstraint(
            "role IN ('admin','exec','owner_finance','owner_ops','owner_clinical','owner_hr')",
            name="ck_alert_subscriptions_role_valid",
        ),
        sa.CheckConstraint(
            "frequency IN ('immediate','daily','weekly','never')",
            name="ck_alert_subscriptions_frequency_valid",
        ),
        sa.UniqueConstraint("role", "email", name="uq_alert_subscriptions_role_email"),
        schema="alerts",
    )

    # ---------- alerts.alert_log ----------
    op.create_table(
        "alert_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("alert_id", sa.String(120), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("recipient_email", sa.String(200), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("acs_message_id", sa.String(200)),
        sa.UniqueConstraint(
            "alert_id",
            "target_date",
            "recipient_email",
            name="uq_alert_log_dedup",
        ),
        schema="alerts",
    )
    op.create_index(
        "ix_alert_log_target_date",
        "alert_log",
        ["target_date"],
        schema="alerts",
    )

    # ---------- alerts.credential_alert_log ----------
    op.create_table(
        "credential_alert_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "credential_id",
            sa.Integer(),
            sa.ForeignKey(
                "masters.credentials.id",
                name="fk_credential_alert_log_credential_id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("threshold_band", sa.Integer(), nullable=False),
        sa.Column(
            "alerted_on",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "threshold_band IN (30, 60, 90)",
            name="ck_credential_alert_log_band_valid",
        ),
        sa.UniqueConstraint(
            "credential_id",
            "threshold_band",
            name="uq_credential_alert_log_band",
        ),
        schema="alerts",
    )


def downgrade() -> None:
    op.drop_table("credential_alert_log", schema="alerts")
    op.drop_table("alert_log", schema="alerts")
    op.drop_table("alert_subscriptions", schema="alerts")
