"""initial schema — masters

Revision ID: 0001
Revises:
Create Date: 2026-04-23

Creates the 6 schemas, btree_gist extension, and the masters tables.
GIST exclusion constraint on comp_agreements prevents overlapping
effective periods per physician.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Schemas — idempotent. Dev is pre-seeded via docker-compose/init-schemas.sql
    # but this makes prod / CI environments self-sufficient.
    for schema in ("masters", "entries", "facts", "audit", "alerts", "dims"):
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # ---------- sites ----------
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("state", sa.String(2), nullable=False),
        sa.Column("hospital_system", sa.String(200)),
        sa.Column("address", sa.Text()),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="ACTIVE"
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
        sa.UniqueConstraint("name", name="uq_sites_name"),
        schema="masters",
    )

    # ---------- contracts ----------
    op.create_table(
        "contracts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "site_id",
            sa.Integer(),
            sa.ForeignKey(
                "masters.sites.id",
                name="fk_contracts_site_id_sites",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("annual_subsidy_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("payment_schedule", sa.String(50)),
        sa.Column("coverage_min_mds", sa.Integer()),
        sa.Column("contract_pdf_url", sa.String(500)),
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
        schema="masters",
    )

    # ---------- physicians ----------
    op.create_table(
        "physicians",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("npi", sa.String(10)),
        sa.Column("dea", sa.String(20)),
        sa.Column("email", sa.String(200)),
        sa.Column(
            "current_status",
            sa.String(20),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("pip_start_date", sa.Date()),
        sa.Column(
            "primary_site_id",
            sa.Integer(),
            sa.ForeignKey(
                "masters.sites.id",
                name="fk_physicians_primary_site_id_sites",
                ondelete="SET NULL",
            ),
        ),
        sa.Column("paycom_employee_id", sa.String(50)),
        sa.Column("athena_provider_id", sa.String(50)),
        sa.Column("hire_date", sa.Date()),
        sa.Column("term_date", sa.Date()),
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
        sa.UniqueConstraint("npi", name="uq_physicians_npi"),
        schema="masters",
    )

    # ---------- comp_agreements ----------
    op.create_table(
        "comp_agreements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "physician_id",
            sa.Integer(),
            sa.ForeignKey(
                "masters.physicians.id",
                name="fk_comp_agreements_physician_id_physicians",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("employment_type", sa.String(10), nullable=False),
        sa.Column("base_salary_usd", sa.Numeric(12, 2)),
        sa.Column("per_diem_rate_usd", sa.Numeric(10, 2)),
        sa.Column("rvu_rate_usd", sa.Numeric(8, 2)),
        sa.Column("rvu_threshold_annual", sa.Numeric(10, 2)),
        sa.Column("call_stipend_usd", sa.Numeric(10, 2)),
        sa.Column("fmv_benchmark_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by_upn", sa.String(200)),
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
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_comp_agreements_effective_dates",
        ),
        schema="masters",
    )

    op.create_index(
        "ix_comp_agreements_physician_id",
        "comp_agreements",
        ["physician_id"],
        schema="masters",
    )

    # GIST exclusion: no overlapping effective periods per physician.
    # Uses btree_gist + daterange with half-open '[)' semantics.
    op.execute(
        """
        ALTER TABLE masters.comp_agreements
        ADD CONSTRAINT ex_comp_agreements_no_overlap
        EXCLUDE USING GIST (
            physician_id WITH =,
            daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[)') WITH &&
        )
        """
    )

    # ---------- credentials ----------
    op.create_table(
        "credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "physician_id",
            sa.Integer(),
            sa.ForeignKey(
                "masters.physicians.id",
                name="fk_credentials_physician_id_physicians",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column(
            "hospital_id",
            sa.Integer(),
            sa.ForeignKey(
                "masters.sites.id",
                name="fk_credentials_hospital_id_sites",
                ondelete="SET NULL",
            ),
        ),
        sa.Column("issued_on", sa.Date()),
        sa.Column("expires_on", sa.Date(), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="ACTIVE"
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
        schema="masters",
    )

    op.create_index(
        "ix_credentials_physician_id",
        "credentials",
        ["physician_id"],
        schema="masters",
    )
    op.create_index(
        "ix_credentials_expires_on",
        "credentials",
        ["expires_on"],
        schema="masters",
    )

    # ---------- site_coverage ----------
    op.create_table(
        "site_coverage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "site_id",
            sa.Integer(),
            sa.ForeignKey(
                "masters.sites.id",
                name="fk_site_coverage_site_id_sites",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "physician_id",
            sa.Integer(),
            sa.ForeignKey(
                "masters.physicians.id",
                name="fk_site_coverage_physician_id_physicians",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date()),
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
        schema="masters",
    )


def downgrade() -> None:
    op.drop_table("site_coverage", schema="masters")
    op.drop_index(
        "ix_credentials_expires_on", table_name="credentials", schema="masters"
    )
    op.drop_index(
        "ix_credentials_physician_id", table_name="credentials", schema="masters"
    )
    op.drop_table("credentials", schema="masters")
    op.execute(
        "ALTER TABLE masters.comp_agreements "
        "DROP CONSTRAINT IF EXISTS ex_comp_agreements_no_overlap"
    )
    op.drop_index(
        "ix_comp_agreements_physician_id",
        table_name="comp_agreements",
        schema="masters",
    )
    op.drop_table("comp_agreements", schema="masters")
    op.drop_table("physicians", schema="masters")
    op.drop_table("contracts", schema="masters")
    op.drop_table("sites", schema="masters")
    # Keep schemas + extension — other migrations will use them.
