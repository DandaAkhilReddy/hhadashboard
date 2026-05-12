# Ventra sample drops — fixture data for the ingest pipeline

This directory holds **deterministically generated** sample drops that exercise
the full Ventra ingest path (V1-V14 validators + fact-table upserts) without
needing a real Ventra delivery.

## What's here

- `sample-drop-2026-06-15/` — one complete drop with all three data files
  + a matching `_MANIFEST.csv`. 25 collections rows, 30 AR snapshot rows,
  50 physician_monthly rows.

Every file is byte-deterministic: the generator script seeds values off
the facility number, payer class, NPI index, etc., so re-running it
produces the same SHA-256 hashes. That lets us check in `_MANIFEST.csv`
with pre-computed hashes and trust they won't drift.

## How to use

### Local smoke test (no Azure)

The ingest job code (`jobs/ventra_ingest/`) parses these files directly.
The integration tests in `api/tests/test_ventra_sample_fixture.py` load
this fixture through `load_manifest` + `parse_file` to assert it stays
valid across V1-V11 changes.

### Dev Azure smoke test (after `enable_vendor_storage = true`)

```bash
az login

# Upload to vendor-inbound; manifest goes last so Event Grid triggers
# only on the complete drop
./scripts/seed_sample_ventra_drop.sh sthhavendordev0xxxxxx
```

Then watch one of:

- Container Apps Job execution: `az containerapp job execution list \
  --name caj-ventra-ingest-dev --resource-group rg-hha-dashboard-dev`
- App Insights: `customEvents | where name startswith "ventra."`
- Postgres: `SELECT * FROM ops.ingest_run ORDER BY started_at DESC LIMIT 1`

## Regenerating

If you need a different drop_date or want to refresh after edits to the
generator:

```bash
python scripts/generate_sample_ventra_drop.py 2026-06-15 \
    samples/ventra/sample-drop-2026-06-15 --include-monthly
```

The `--include-monthly` flag forces `physician_monthly.csv` to be emitted
on any drop_date; without it, the file is only created when
`drop_date.day == 1` (Ventra's month-close convention).

## Important caveat — facility_no values

The fixtures use placeholder `facility_no` values `1..5`. Before the ingest
job's V12 validator will accept them, your dev DB must have matching active
FL sites in `masters.sites`. Seed via:

```bash
cd hha-dashboard/api
uv run python ../scripts/seed_sites.py
```

If your `masters.sites.id` values differ, regenerate the sample with
different facility values by editing the `FACILITIES` list in
`scripts/generate_sample_ventra_drop.py`.

## Vendor source_system tags

The `source_system` column carries Ventra's PM-system identifier
(`CB | MGS | VSQL | DUVA`). The fixture spreads facilities across these
deterministically: `VENDOR_SOURCE_SYSTEMS[facility_no % 4]`. The C12
writer discards this column (DB CHECK locks ours to `VENTRA_FL_ATHENA`);
C14 captures the value in the `ventra.ingest_complete` App Insights
event for forensic reconciliation.

## What this fixture is NOT

- **Not real data.** No PII / PHI by construction (the entire Ventra
  ingest schema is Tier-A per ADR-001).
- **Not a load test.** 25 + 30 + 50 = 105 total rows; production
  expected scale is ~5 facilities × 5 payer_classes × 30 days = 750
  collections rows/month.
- **Not deterministic across generator-script changes.** If you edit
  the generator's formulas, the sha256s in `_MANIFEST.csv` will drift —
  regenerate.
