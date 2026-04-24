"""Masters schema: sites, contracts, physicians, comp_agreements, credentials, site_coverage.

Per ADR-001: every column has info={"data_class": ...}.
No PHI / Tier C columns here or anywhere.
"""

from datetime import date
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, DataClass, TimestampMixin

A = DataClass.A.value
B = DataClass.B.value
D = DataClass.D.value


# ---------- Enums (Python-side; DB stores as VARCHAR for simplicity) ----------


class StateCode(StrEnum):
    FL = "FL"
    TX = "TX"


class SiteStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PROSPECT = "PROSPECT"
    TERMED = "TERMED"


class EmploymentType(StrEnum):
    W2 = "W2"
    CONTRACTOR_1099 = "1099"


class CompModel(StrEnum):
    SALARY = "SALARY"
    PER_DIEM = "PER_DIEM"
    RVU = "RVU"
    HYBRID = "HYBRID"


class PhysicianStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PIP = "PIP"
    VACANT = "VACANT"
    TERMED = "TERMED"


class CredentialType(StrEnum):
    STATE_LICENSE = "STATE_LICENSE"
    DEA = "DEA"
    BOARD_CERTIFICATION = "BOARD_CERTIFICATION"
    HOSPITAL_PRIVILEGE = "HOSPITAL_PRIVILEGE"


class CoverageRole(StrEnum):
    MEDICAL_DIRECTOR = "MEDICAL_DIRECTOR"
    LIAISON = "LIAISON"
    COVERING = "COVERING"


# ---------- Tables ----------


class Site(Base, TimestampMixin):
    __tablename__ = "sites"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(primary_key=True, info={"data_class": D})
    name: Mapped[str] = mapped_column(
        String(200), unique=True, nullable=False, info={"data_class": D}
    )
    state: Mapped[str] = mapped_column(String(2), nullable=False, info={"data_class": D})
    hospital_system: Mapped[str | None] = mapped_column(String(200), info={"data_class": D})
    address: Mapped[str | None] = mapped_column(Text, info={"data_class": D})
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SiteStatus.ACTIVE.value, info={"data_class": B}
    )


class Contract(Base, TimestampMixin):
    __tablename__ = "contracts"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(primary_key=True, info={"data_class": A})
    site_id: Mapped[int] = mapped_column(
        ForeignKey("masters.sites.id", ondelete="RESTRICT"),
        nullable=False,
        info={"data_class": A},
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False, info={"data_class": A})
    end_date: Mapped[date] = mapped_column(Date, nullable=False, info={"data_class": A})
    annual_subsidy_usd: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, info={"data_class": A}
    )
    payment_schedule: Mapped[str | None] = mapped_column(String(50), info={"data_class": A})
    coverage_min_mds: Mapped[int | None] = mapped_column(info={"data_class": A})
    contract_pdf_url: Mapped[str | None] = mapped_column(String(500), info={"data_class": D})


class Physician(Base, TimestampMixin):
    __tablename__ = "physicians"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(primary_key=True, info={"data_class": B})
    name: Mapped[str] = mapped_column(String(200), nullable=False, info={"data_class": B})
    npi: Mapped[str | None] = mapped_column(String(10), unique=True, info={"data_class": B})
    dea: Mapped[str | None] = mapped_column(String(20), info={"data_class": B})
    email: Mapped[str | None] = mapped_column(String(200), info={"data_class": B})
    current_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=PhysicianStatus.ACTIVE.value,
        info={"data_class": B},
    )
    pip_start_date: Mapped[date | None] = mapped_column(Date, info={"data_class": B})
    primary_site_id: Mapped[int | None] = mapped_column(
        ForeignKey("masters.sites.id", ondelete="SET NULL"), info={"data_class": B}
    )
    paycom_employee_id: Mapped[str | None] = mapped_column(String(50), info={"data_class": B})
    # athena_provider_id stays null until Phase 2. It's a Ventra-side ID,
    # not a patient identifier — data_class B (directory).
    athena_provider_id: Mapped[str | None] = mapped_column(String(50), info={"data_class": B})
    hire_date: Mapped[date | None] = mapped_column(Date, info={"data_class": B})
    term_date: Mapped[date | None] = mapped_column(Date, info={"data_class": B})


class CompAgreement(Base, TimestampMixin):
    """Time-variant comp agreement per physician.

    Real comp is often hybrid (salary + RVU + stipend) and changes over time.
    GIST exclusion constraint in the migration prevents overlapping ranges
    per physician (requires btree_gist extension).
    """

    __tablename__ = "comp_agreements"
    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="effective_dates",
        ),
        Index("ix_comp_agreements_physician_id", "physician_id"),
        {"schema": "masters"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, info={"data_class": B})
    physician_id: Mapped[int] = mapped_column(
        ForeignKey("masters.physicians.id", ondelete="CASCADE"),
        nullable=False,
        info={"data_class": B},
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, info={"data_class": B})
    effective_to: Mapped[date | None] = mapped_column(Date, info={"data_class": B})
    employment_type: Mapped[str] = mapped_column(String(10), nullable=False, info={"data_class": B})
    base_salary_usd: Mapped[float | None] = mapped_column(Numeric(12, 2), info={"data_class": B})
    per_diem_rate_usd: Mapped[float | None] = mapped_column(Numeric(10, 2), info={"data_class": B})
    rvu_rate_usd: Mapped[float | None] = mapped_column(Numeric(8, 2), info={"data_class": B})
    rvu_threshold_annual: Mapped[float | None] = mapped_column(
        Numeric(10, 2), info={"data_class": B}
    )
    call_stipend_usd: Mapped[float | None] = mapped_column(Numeric(10, 2), info={"data_class": B})
    fmv_benchmark_usd: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, info={"data_class": B}
    )
    notes: Mapped[str | None] = mapped_column(Text, info={"data_class": B})
    created_by_upn: Mapped[str | None] = mapped_column(String(200), info={"data_class": B})


class Credential(Base, TimestampMixin):
    __tablename__ = "credentials"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(primary_key=True, info={"data_class": B})
    physician_id: Mapped[int] = mapped_column(
        ForeignKey("masters.physicians.id", ondelete="CASCADE"),
        nullable=False,
        info={"data_class": B},
    )
    type: Mapped[str] = mapped_column(String(30), nullable=False, info={"data_class": B})
    hospital_id: Mapped[int | None] = mapped_column(
        ForeignKey("masters.sites.id", ondelete="SET NULL"), info={"data_class": B}
    )
    issued_on: Mapped[date | None] = mapped_column(Date, info={"data_class": B})
    expires_on: Mapped[date] = mapped_column(Date, nullable=False, info={"data_class": B})
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ACTIVE", info={"data_class": B}
    )


class SiteCoverage(Base, TimestampMixin):
    """Who covers which site in which role, historically."""

    __tablename__ = "site_coverage"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(primary_key=True, info={"data_class": B})
    site_id: Mapped[int] = mapped_column(
        ForeignKey("masters.sites.id", ondelete="CASCADE"),
        nullable=False,
        info={"data_class": B},
    )
    physician_id: Mapped[int] = mapped_column(
        ForeignKey("masters.physicians.id", ondelete="CASCADE"),
        nullable=False,
        info={"data_class": B},
    )
    role: Mapped[str] = mapped_column(String(30), nullable=False, info={"data_class": B})
    start_date: Mapped[date] = mapped_column(Date, nullable=False, info={"data_class": B})
    end_date: Mapped[date | None] = mapped_column(Date, info={"data_class": B})
