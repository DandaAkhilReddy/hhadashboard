"""Dimension / mapping tables in schema ``dims``.

Currently holds the Ventra-facility mapping. Ventra keys their data by
their own ``FacilityNo`` (2284-2290 for HHA's seven Florida hospitals);
HHA's canonical model keys facilities by ``masters.sites.id`` (1-7). Every
other board (operations, clinical, people, scorecards) joins on
``masters.sites.id``, so the Ventra ingest pipelines resolve the vendor's
FacilityNo to the HHA site_id at write time and store the HHA id in the
fact tables. This table is that mapping.

The mapping is time-versioned (``effective_from`` / ``effective_through``)
so a future Ventra facility renumbering can be expressed as closing one
row and opening another, preserving the historical resolution for old
fact rows. v1 seeds the seven current FL mappings with ``effective_from``
= the contract start and a NULL ``effective_through`` (open-ended).

Per ADR-001: every column is ``data_class = B`` (workforce / directory
reference — a facility-to-vendor-id map is operational metadata, not PHI).
Per ADR-003: this table IS audited — a change to the mapping could
silently redirect which HHA site a Ventra drop lands on, which is a
security-relevant event, so the ``audit.log_change()`` trigger is attached
(migration 0014) and ``("dims", "facility_codes")`` is in
``app.services.audit.AUDITED_TABLES``.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, DataClass, TimestampMixin

B = DataClass.B.value


class FacilityCode(Base, TimestampMixin):
    """Maps a Ventra ``FacilityNo`` to an HHA ``masters.sites.id``.

    Lookup at ingest: ``SELECT site_id FROM dims.facility_codes WHERE
    ventra_facility_no = :no AND effective_through IS NULL`` (the open
    row). The Ventra pipelines load the whole active map in one query
    and resolve every row in memory.
    """

    __tablename__ = "facility_codes"
    __table_args__ = (
        # One OPEN mapping per Ventra facility. A historical (closed) row
        # may share the ventra_facility_no, so the uniqueness is enforced
        # only on the open row via a partial index below — the table-level
        # UniqueConstraint covers (ventra_facility_no, effective_from) so a
        # facility can be remapped over time without collision.
        UniqueConstraint(
            "ventra_facility_no",
            "effective_from",
            name="uq_facility_codes_ventra_no_effective",
        ),
        CheckConstraint(
            "effective_through IS NULL OR effective_through >= effective_from",
            name="effective_window_ordered",
        ),
        Index("ix_facility_codes_ventra_no", "ventra_facility_no"),
        Index("ix_facility_codes_site_id", "site_id"),
        {"schema": "dims"},
    )

    id: Mapped[int] = mapped_column(primary_key=True, info={"data_class": B})
    ventra_facility_no: Mapped[int] = mapped_column(
        Integer, nullable=False, info={"data_class": B}
    )
    site_id: Mapped[int] = mapped_column(
        ForeignKey("masters.sites.id"), nullable=False, info={"data_class": B}
    )
    effective_from: Mapped[date] = mapped_column(
        Date, nullable=False, info={"data_class": B}
    )
    effective_through: Mapped[date | None] = mapped_column(
        Date, nullable=True, info={"data_class": B}
    )


__all__ = ["FacilityCode"]
