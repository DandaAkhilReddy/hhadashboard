"""Ventra facility mapping — dims.facility_codes

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-16

Maps Ventra's ``FacilityNo`` (2284-2290) to HHA's ``masters.sites.id``
(1-7). Confirmed by Ventra's 2026-06-15 reply: their Technology & Data
Analytics team generates both the Standard Data Extract and the
pre-aggregated extract keyed by these seven FL FacilityNos:

  2284 Jackson Memorial Hospital
  2285 HCA Florida JFK Main Hospital
  2286 HCA Florida JFK North Hospital
  2287 HCA Florida Palms West Hosp
  2288 HCA Florida University Hosp
  2289 HCA Florida Westside Hospital
  2290 HCA Florida Woodmont Hospital

HHA's masters.sites uses its own surrogate ids and slightly different
names (the seed in scripts/seed_sites.py). Both Ventra pipelines resolve
FacilityNo -> site_id at ingest and store the HHA site_id in the fact
tables so finance data joins to the same site as the ops/clinical/people
boards (which all key on masters.sites.id).

The seed resolves site_id by NAME correspondence (Ventra name -> HHA
masters.sites.name) rather than hardcoding ids, because the seeded ids
are insertion-order-dependent and would silently break if seed_sites.py
were reordered. If a site row is missing (DB not seeded), that mapping
row is skipped with a NOTICE — the table is created empty-or-partial and
the operator reseeds; ingest's V8 (unknown facility) then quarantines any
unmapped drop until the mapping is complete, which is the correct
fail-closed behavior.

Per ADR-001: all columns data_class B. Per ADR-003: audited (a remap could
redirect FL data) — the audit.log_change() trigger from migration 0007 is
attached and ("dims","facility_codes") is added to AUDITED_TABLES in the
same commit.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Ventra FacilityNo -> HHA masters.sites.name. Resolution to site_id happens
# in the seed query via a name lookup, never a hardcoded id.
VENTRA_FACILITY_TO_HHA_NAME: list[tuple[int, str]] = [
    (2284, "Jackson Memorial"),
    (2285, "JFK Main Med Ctr"),
    (2286, "JFK North Med Ctr"),
    (2287, "Palms West Hospital"),
    (2288, "University Hospital"),
    (2289, "Westside Regional"),
    (2290, "Woodmont Hospital"),
]

# Contract-aligned open-ended effective window. The 2026 HHA/Ventra FL
# engagement; effective_through stays NULL until a remap closes it.
SEED_EFFECTIVE_FROM = "2026-01-01"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS dims")

    op.create_table(
        "facility_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ventra_facility_no", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_through", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["masters.sites.id"],
            name="fk_facility_codes_site_id_sites",
        ),
        sa.UniqueConstraint(
            "ventra_facility_no",
            "effective_from",
            name="uq_facility_codes_ventra_no_effective",
        ),
        sa.CheckConstraint(
            "effective_through IS NULL OR effective_through >= effective_from",
            name="ck_facility_codes_effective_window_ordered",
        ),
        schema="dims",
    )
    op.create_index(
        "ix_facility_codes_ventra_no",
        "facility_codes",
        ["ventra_facility_no"],
        schema="dims",
    )
    op.create_index(
        "ix_facility_codes_site_id",
        "facility_codes",
        ["site_id"],
        schema="dims",
    )

    # Seed the 7 mappings by name correspondence. INSERT ... SELECT resolves
    # site_id from masters.sites by name; a missing site simply inserts zero
    # rows for that FacilityNo (fail-closed — ingest V8 quarantines unmapped
    # drops until the mapping is complete).
    for ventra_no, hha_name in VENTRA_FACILITY_TO_HHA_NAME:
        op.execute(
            sa.text(
                "INSERT INTO dims.facility_codes "
                "(ventra_facility_no, site_id, effective_from, effective_through) "
                "SELECT :ventra_no, s.id, :eff_from, NULL "
                "FROM masters.sites s "
                "WHERE s.name = :hha_name"
            ).bindparams(
                ventra_no=ventra_no,
                hha_name=hha_name,
                eff_from=SEED_EFFECTIVE_FROM,
            )
        )

    # Attach audit trigger (same pattern as migrations 0011 / 0013).
    op.execute(
        "DROP TRIGGER IF EXISTS audit_facility_codes_change ON dims.facility_codes;"
    )
    op.execute(
        "CREATE TRIGGER audit_facility_codes_change "
        "AFTER INSERT OR UPDATE OR DELETE ON dims.facility_codes "
        "FOR EACH ROW EXECUTE FUNCTION audit.log_change();"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS audit_facility_codes_change ON dims.facility_codes;"
    )
    op.drop_table("facility_codes", schema="dims")
    # Leave the dims schema in place — migration 0001 created it and other
    # future dims tables may depend on it.
