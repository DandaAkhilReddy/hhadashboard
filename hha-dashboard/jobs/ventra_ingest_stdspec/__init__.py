"""Ventra Standard-Spec (row-level) ingest pipeline.

Phase 4 hybrid — receives row-level Invoice + Guarantor CSVs from Ventra,
strips PHI at the parser layer (V15), aggregates in-memory to the same
(date, facility_no, payer_class) / (snapshot_date, facility_no, aging_bucket)
/ (month, physician_npi, facility_no) grain as the pre-aggregated path,
and writes to the same fact tables tagged with source_system =
'VENTRA_FL_STDSPEC_AGG'.

Lives in a separate package from ``jobs/ventra_ingest/`` (the pre-aggregated
path) because the security boundary differs — every module here must
defer to ``phi.py`` for column denial and ``logging.py`` for output
scrubbing. The two pipelines share the database schema, the
``app/services/*`` utilities, and the audit chain, but their parser +
validator + ingestion layers are distinct.

See ``docs/02-architecture/adr/007-ventra-hybrid-dual-source.md`` (H20)
for the decision record.
"""
