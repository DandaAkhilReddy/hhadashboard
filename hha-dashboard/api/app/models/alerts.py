"""Alerts schema models.

`alert_subscriptions` — who gets emailed.
`alert_log` — what was already sent (idempotency record).
`credential_alert_log` — credential-expiry threshold-band tracking.

Per ADR-001:
- `email` (recipient) is Tier B (directory).
- alert title/detail/owner strings are Tier A.
- `credential_id` FK is Tier A (it's an int).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import BIGINT_PK, Base, DataClass

A = DataClass.A.value
B = DataClass.B.value


class AlertSubscription(Base):
    """One row per (role, email). A user can be subscribed under multiple roles
    (e.g., admin@hha is in `admin` AND `exec`)."""

    __tablename__ = "alert_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin','exec','owner_finance','owner_ops','owner_clinical','owner_hr')",
            name="role_valid",
        ),
        CheckConstraint(
            "frequency IN ('immediate','daily','weekly','never')",
            name="frequency_valid",
        ),
        UniqueConstraint("role", "email", name="uq_alert_subscriptions_role_email"),
        {"schema": "alerts"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, info={"data_class": A})
    role: Mapped[str] = mapped_column(String(40), nullable=False, info={"data_class": A})
    email: Mapped[str] = mapped_column(String(200), nullable=False, info={"data_class": B})
    categories: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), nullable=False, default=list, info={"data_class": A}
    )
    frequency: Mapped[str] = mapped_column(
        String(20), nullable=False, default="daily", info={"data_class": A}
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"data_class": A},
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"data_class": A},
    )


class AlertLog(Base):
    """One row per (alert_id, target_date, recipient_email). The cron uses
    this to skip re-sending already-delivered alerts on the same day."""

    __tablename__ = "alert_log"
    __table_args__ = (
        UniqueConstraint(
            "alert_id", "target_date", "recipient_email", name="uq_alert_log_dedup"
        ),
        Index("ix_alert_log_target_date", "target_date"),
        {"schema": "alerts"},
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, info={"data_class": A})
    alert_id: Mapped[str] = mapped_column(
        String(120), nullable=False, info={"data_class": A}
    )
    target_date: Mapped[date] = mapped_column(Date, nullable=False, info={"data_class": A})
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, info={"data_class": A}
    )
    category: Mapped[str] = mapped_column(
        String(20), nullable=False, info={"data_class": A}
    )
    recipient_email: Mapped[str] = mapped_column(
        String(200), nullable=False, info={"data_class": B}
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, info={"data_class": A}
    )
    acs_message_id: Mapped[str | None] = mapped_column(
        String(200), info={"data_class": A}
    )


class CredentialAlertLog(Base):
    """One row per (credential_id, threshold_band). Re-firing requires the
    credential to cross to a tighter band (90→60→30) — single row per band."""

    __tablename__ = "credential_alert_log"
    __table_args__ = (
        CheckConstraint(
            "threshold_band IN (30, 60, 90)", name="threshold_band_valid"
        ),
        UniqueConstraint(
            "credential_id", "threshold_band", name="uq_credential_alert_log_band"
        ),
        {"schema": "alerts"},
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, info={"data_class": A})
    credential_id: Mapped[int] = mapped_column(
        ForeignKey("masters.credentials.id", ondelete="CASCADE"),
        nullable=False,
        info={"data_class": A},
    )
    threshold_band: Mapped[int] = mapped_column(
        Integer, nullable=False, info={"data_class": A}
    )
    alerted_on: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, info={"data_class": A}
    )
