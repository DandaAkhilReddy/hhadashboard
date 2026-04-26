from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, Integer, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

# Cross-dialect BigInteger primary key. SQLite only auto-increments INTEGER PK
# columns (not BIGINT), so the in-memory test DB falls back to plain Integer.
# Postgres still gets a true bigint via the normal BigInteger path.
BIGINT_PK = BigInteger().with_variant(Integer(), "sqlite")


class DataClass(StrEnum):
    """Data classification tiers per ADR-001.

    A: Operational aggregates (counts, sums, percentages, no patient link)
    B: HR / Workforce / Directory (physician name, comp, credentials)
    C: PHI / Limited Data Set — FORBIDDEN IN SCHEMA. Aggregate at edge only.
    D: Public / Reference (addresses, payer names, dim_date)
    """

    A = "A"
    B = "B"
    C = "C"  # never use on persisted columns
    D = "D"


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
        }
    )


class TimestampMixin:
    """Mixin adding created_at / updated_at to every table."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        info={"data_class": DataClass.A.value},
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        info={"data_class": DataClass.A.value},
    )
