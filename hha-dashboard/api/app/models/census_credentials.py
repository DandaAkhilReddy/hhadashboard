"""Auth schema — census-portal credentials.

Per ADR-001:
- email and password_hash are Tier B (workforce / directory).
- Session token + lockout fields are Tier A (operational state).

The portal owns exactly ONE row (id=1), enforced by CHECK constraint.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, DataClass, TimestampMixin

A = DataClass.A.value
B = DataClass.B.value


class CensusCredential(Base, TimestampMixin):
    """Single-row table holding the shared census-portal credential.

    `active_session_token` enforces single-session: on each login it's overwritten,
    invalidating any prior browser's cookie. `failed_attempts` + `locked_until`
    implement the lockout policy from rules/security.md (10 fails → 15-min lock).
    """

    __tablename__ = "census_credentials"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_row"),
        CheckConstraint("failed_attempts >= 0", name="attempts_non_negative"),
        UniqueConstraint("email", name="uq_census_credentials_email"),
        {"schema": "auth"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, info={"data_class": A})
    email: Mapped[str] = mapped_column(String(200), nullable=False, info={"data_class": B})
    password_hash: Mapped[str] = mapped_column(
        String(200), nullable=False, info={"data_class": B}
    )
    active_session_token: Mapped[str | None] = mapped_column(
        String(64), info={"data_class": A}
    )
    active_session_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), info={"data_class": A}
    )
    failed_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, info={"data_class": A}
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), info={"data_class": A}
    )
