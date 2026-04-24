"""Audit schema — immutable log of every mutation to sensitive tables.

Written by an `after_flush` SQLAlchemy event listener in services/audit.py.
Covers: masters.physicians, masters.comp_agreements, masters.contracts,
masters.credentials, entries.daily_entries, and every other entries table.

Regulators / internal auditors eventually ask "who changed Dr. X's below-FMV
flag on what date?" — the answer has to live here.

Per ADR-001: diffs never contain PHI. If a diff-producing column is ever
Tier C (forbidden anyway), the test_schema_classification CI guard blocks the PR.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base, DataClass

B = DataClass.B.value


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = {"schema": "audit"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, info={"data_class": B})
    table_schema: Mapped[str] = mapped_column(String(63), nullable=False, info={"data_class": B})
    table_name: Mapped[str] = mapped_column(String(63), nullable=False, info={"data_class": B})
    row_pk: Mapped[str] = mapped_column(String(200), nullable=False, info={"data_class": B})
    action: Mapped[str] = mapped_column(
        String(10), nullable=False, info={"data_class": B}
    )  # INSERT | UPDATE | DELETE
    diff: Mapped[dict] = mapped_column(JSONB, nullable=False, info={"data_class": B})
    changed_by_upn: Mapped[str] = mapped_column(
        String(200), nullable=False, info={"data_class": B}
    )
    reason: Mapped[str | None] = mapped_column(Text, info={"data_class": B})
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        info={"data_class": B},
    )
