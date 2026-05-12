# Ventra ingestion architecture

> **For engineers.** Phase 2 — how Florida RCM data from Ventra reaches the dashboard. The delivery shape is **pre-aggregated CSVs** per [ADR-006](../02-architecture/adr/006-ventra-pre-aggregated-feed.md); the row-level Standard Data Extract path is retained as a fallback in case Ventra refuses pre-aggregated.
>
> Visual: [DIAGRAMS.md § 6](../02-architecture/DIAGRAMS.md#6-ventra-ingestion-data-flow) and [§ 7 HIPAA firewall](../02-architecture/DIAGRAMS.md#7-hipaa-firewall-flow).
>
> Last updated 2026-05-11.

## Decision status

[ADR-006](../02-architecture/adr/006-ventra-pre-aggregated-feed.md) is **Proposed** — Akhil sent the pre-aggregated proposal to Ventra on 2026-05-11 (see [FOLLOWUP_EMAIL.md](../06-vendors/ventra/FOLLOWUP_EMAIL.md)). Until Ventra confirms in writing:

- Build proceeds on Option A (pre-aggregated). It's the contract HHA is offering.
- Bicep `enable_sftp` flag stays **off** in prod. No SSH key gets installed. No Ventra user account is provisioned.
- Option B (row-level Standard Data Extract) stays documented as the contingency, not built.

## TL;DR

Ventra writes three pre-aggregated CSVs daily (`collections.csv`, `ar_snapshot.csv`, optionally `physician_monthly.csv` at month close) into a `/YYYY-MM-DD/` folder on HHA's SFTP-enabled Azure Storage Account, then writes `_MANIFEST.csv` last. The manifest write fires an Event Grid event → Storage Queue → KEDA-triggered Container Apps Job. The job validates the manifest (V1-V4), validates each file's schema and content (V5-V11), enforces cross-file invariants including FL-only (V12-V13), then UPSERTs into `entries.fact_collections_daily`, `entries.fact_ar_snapshot`, and `entries.fact_revenue_by_physician_mo`. All rows carry `source_system = 'VENTRA_FL_ATHENA'` enforced by DB CHECK. **No PHI ever touches HHA systems** because none ever leaves Ventra.

## Why this design

| Requirement | How this design meets it |
|---|---|
| HIPAA — no PHI in DB | Strip at parser, aggregate in memory, persist aggregates only |
| Cheap — solo-engineer budget | Container Apps Jobs scale-to-zero between runs; no idle compute |
| Idempotent | UPSERT on `(date, site, payer_class)` natural key + file checksum dedup |
| Resilient | Manifest pattern prevents half-complete picks; quarantine for bad files |
| Auditable | Every ingest writes to `ingest.run_log` and `audit.audit_log` |
| HHA-controlled receiving side | SFTP-enabled Storage Account in HHA's tenant; Ventra pushes to us, not the other way |

## The two delivery shapes

Ventra's spec (2026-05-08) defaults to **Option B (claim-level CSV)**. HHA proposed **Option A (pre-aggregated CSV)** in the follow-up email of 2026-05-11. The architectural decision in [ADR-006](../02-architecture/adr/006-ventra-pre-aggregated-feed.md) locks Option A as the target shape; Option B is retained as a contingency to be activated only if Ventra refuses in writing.

### Option A — pre-aggregated CSV (the decision, per ADR-006)

Ventra delivers three files daily that match HHA's fact-table grain exactly:

- `collections.csv` (or `collections_YYYY-MM-DD.csv`) — grouped by `(date, facility_no, payer_class)`
- `ar_snapshot.csv` — grouped by `(snapshot_date, facility_no, aging_bucket)`
- `physician_monthly.csv` — grouped by `(month, physician_npi, facility_no)` — written monthly only

**HHA's job:** auto-validate (V1-V14, see catalog below), upsert into three fact tables, alert on quarantine. No PHI is in the file shape so no firewall is needed in the parser; ADR-001's CI guard at migration time provides defense-in-depth.

**Effort:** ~2 weeks solo engineer.

### Option B — claim-level CSV (fallback only)

Ventra's `Standard Data Extract` — multiple CSVs per delivery with claim-level rows and patient identifiers in the Invoice and Guarantor files.

**HHA's job:** parse all files, **strip PHI at parse time** (allowlist approach per the firewall section below), aggregate in memory at the grain HHA needs, upsert. The strip + aggregate stage runs *before* the V1-V14 validator catalog so the validators see only Tier-A rows.

**Effort:** ~5 weeks solo engineer (the extra ~3 weeks is entirely PHI-safety hardening at every boundary — see ADR-006 for the breakdown).

This document covers both. The Option B sections (HIPAA firewall, aggregation logic) are only executed if Ventra refuses the proposal.

## Auto-check validators (V1-V14)

Every drop runs through these checks in order. Any failure quarantines the drop and emails ops. V12 (FL-only) and V14 (source_system) are the two HHA cannot ever loosen — they are HIPAA/scope invariants per ADR-001 and ADR-005.

| # | Rule | Failure |
|---|---|---|
| V1 | `_MANIFEST.csv` parses; has columns `file_name, sha256, row_count` | quarantine |
| V2 | Every file referenced in manifest exists in `vendor-inbound/ventra/YYYY-MM-DD/` | quarantine |
| V3 | SHA-256 of each blob matches manifest checksum | quarantine |
| V4 | Row count of each file matches manifest | quarantine |
| V5 | Schema match — required columns present with correct Pydantic type | quarantine |
| V6 | `date` column in collections + ar_snapshot equals folder `drop_date` (drift detect) | quarantine |
| V7 | `month` in physician_monthly is first-of-month date | quarantine |
| V8 | Every `facility_no` exists in `masters.facilities` | quarantine + ops alert ("vendor sent unknown facility — config drift") |
| V9 | AR buckets sum to total within ±$1 rounding tolerance; `credit` bucket allowed negative, all others non-negative | quarantine |
| V10 | Collections sanity — `gross_charges + write_offs >= payments_received`; `payments_received >= 0` | quarantine |
| V11 | NPI is 10-digit numeric; `encounters_count >= 0`; `total_rvu >= 0` | quarantine |
| V12 | **FL-only invariant (ADR-005)** — every `facility_no` in HHA's Florida facility set; any other → quarantine + **INCIDENT** alert | quarantine + incident |
| V13 | Dedup — for each `(file_name, sha256)`: if same sha already in `processed_files` → log `dedup_skip` and skip entirely; if same `(drop_date, file_name)` but different sha → quarantine ("re-send with changed content; manual review required") | mixed |
| V14 | `source_system='VENTRA_FL_ATHENA'` (enforced by DB DEFAULT + CHECK on fact tables) | DB-level (cannot violate) |

Implementation lives in `jobs/ventra_ingest/validators.py` with one fixture per rule under `tests/fixtures/bad_drops/`.

## Azure resource architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ rg-hha-dashboard-prod (centralus)                                │
│                                                                  │
│  Storage Account: sthhaprod (SFTP enabled, Standard tier)        │
│    ├── ventra-incoming/ (SFTP-accessible to Ventra)              │
│    │      └── 2026-05-12/                                        │
│    │            collections.csv                                  │
│    │            ar_snapshot.csv                                  │
│    │            physician_monthly.csv  (monthly only)            │
│    │            _MANIFEST.csv  ← written last                    │
│    ├── ventra-incoming/processed/  (moved after successful ingest)│
│    └── ventra-quarantine/  (failed parses)                       │
│                                                                  │
│    Lifecycle policy: cool@7d, delete@30d                         │
│                                                                  │
│  Event Grid System Topic on sthhaprod                            │
│    Subscription: ventra-csv-arrived                              │
│    Filter: subject ENDS WITH "/_MANIFEST.csv"                    │
│    Target: Container Apps Job HTTP trigger                       │
│                                                                  │
│  Container Apps Environment: cae-hha-prod                        │
│    Container Apps Job: cj-hha-ventra-ingest                      │
│      Image: hharegistry.azurecr.io/ventra-ingest:latest          │
│      Replicas: 0 (scales to 0 between runs)                      │
│      Timeout: 30 min                                             │
│      Managed Identity: yes (reads KV, writes Blob + Postgres)    │
│      Env: DATABASE_URL_SYNC (from KV reference),                 │
│           STORAGE_ACCOUNT_NAME, AZURE_CLIENT_ID                  │
│                                                                  │
│  Azure Container Registry: hharegistry (Basic tier)              │
│    Repository: ventra-ingest                                     │
│    Tags: latest, sha-{commit}, semver                            │
│                                                                  │
│  Postgres flex (existing) — receives aggregates                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Code structure

The ingestion job lives at `hha-dashboard/jobs/ventra_ingest/`. Structure:

```
hha-dashboard/jobs/ventra_ingest/
├── Dockerfile
├── pyproject.toml
├── uv.lock
├── README.md (operational)
└── ventra_ingest/
    ├── __init__.py
    ├── main.py              # entrypoint, reads MANIFEST, dispatches
    ├── parse/
    │   ├── __init__.py
    │   ├── options.py       # detect Option A vs B from filenames
    │   ├── option_a.py      # pre-aggregated parser
    │   └── option_b.py      # claim-level parser + HIPAA firewall
    ├── aggregate/
    │   ├── __init__.py
    │   ├── collections.py   # → fact_collections_daily
    │   ├── ar_snapshot.py   # → fact_ar_snapshot
    │   └── physician.py     # → fact_revenue_by_physician_mo
    ├── persist/
    │   ├── __init__.py
    │   ├── upsert.py        # idempotent UPSERTs
    │   └── checksum.py      # file-checksum dedup
    ├── audit/
    │   ├── __init__.py
    │   └── run_log.py       # ingest.run_log writer
    ├── blob.py              # Azure Blob client (Managed Identity)
    └── settings.py          # config (pydantic-settings)
```

## The HIPAA firewall (Option B code path)

The most important code in this job. **Allowlist, not denylist.**

```python
# parse/option_b.py
import polars as pl

# What we KEEP. Anything not in this set is dropped.
ALLOWED_INVOICE_COLS = frozenset({
    "InvoiceNo",
    "FacilityNo",
    "PrimaryInsClass",     # for payer_class mapping
    "AccountStatus",
    "DischargeDate",
    "CreateDate",
    "SourceSystem",
    "PrimaryInsuranceFacilityKey",
    "PrimaryInsuranceKey",
    "IsInCollections",
    "CollectionBalance",
    "LastClaimDate",
    "LastStatementDate",
})

ALLOWED_CHARGELINE_COLS = frozenset({
    "InvoiceNo",
    "ChargeLine",
    "ChargeAmt",
    "PostingDate",
    "PrimaryPhysicianNPI",
    "SecondaryPhysicianNPI",
    "AdditionalPhysicianNPI",
    "ARPeriod",
    "RVU",
    "WorkRVU",
    "PlaceOfService",
    "SourceSystem",
})

ALLOWED_TRANSACTION_COLS = frozenset({
    "InvoiceNo",
    "ChargeLine",
    "PostingDt",
    "BankDepositDt",
    "TranID",
    "TranType",
    "TranAmt",
    "TranSource",
    "InsuranceClass",
    "TranComment",
    "ARPeriod",
    "SourceSystem",
})

# Files we drop entirely — fully PHI-bearing
DROPPED_FILES = frozenset({
    "Guarantor.csv",
    "HeldCharts.csv",
    "ChartEntry.csv",
})

def parse_invoice(path: Path) -> pl.DataFrame:
    """Parse Invoice.csv with PHI strip at parse time."""
    df = pl.read_csv(path)

    # 1. Detect any new columns we don't recognize — log + drop
    unknown = set(df.columns) - ALLOWED_INVOICE_COLS - PHI_COLS_KNOWN
    if unknown:
        logger.warning("ventra.parse.unknown_columns",
                       file="Invoice.csv",
                       columns=sorted(unknown))

    # 2. Select only allowed columns — PHI is dropped here
    df = df.select([c for c in df.columns if c in ALLOWED_INVOICE_COLS])

    # 3. Defense-in-depth: assert no forbidden column made it through
    assert "PatFName" not in df.columns
    assert "SSN" not in df.columns
    assert "MRN" not in df.columns
    assert "PatBirthDate" not in df.columns
    # ... (full forbidden list — see CI test)

    return df
```

Defense in depth:

1. **Allowlist** drops everything not explicitly permitted (closed-set).
2. **Assert** statements catch any future-Akhil typo that adds a forbidden column to the allowlist (open-set guard).
3. **`tests/test_ventra_firewall.py`** in CI parses a fixture row that contains every forbidden field and asserts the output DataFrame has none of them.
4. **`tests/test_schema_classification.py`** (existing) asserts no `facts.*` table has a forbidden column.

## Aggregation logic (Option B → fact tables)

### `fact_collections_daily`

Source: `ChargeLines` (charges) + `TransactionsAlt` (payments/adjustments/refunds).

```python
# aggregate/collections.py
def aggregate_collections(
    invoices: pl.DataFrame,
    chargelines: pl.DataFrame,
    transactions: pl.DataFrame,
    facility_map: pl.DataFrame,    # Ventra FacilityNo → HHA site_id
    payer_class_map: pl.DataFrame, # PrimaryInsClass → payer_class
) -> pl.DataFrame:
    """
    Output grain: (date, site_id, payer_class, source_system)
    """
    # Join invoice → chargelines for FacilityNo + payer
    charges = chargelines.join(
        invoices.select(["InvoiceNo", "FacilityNo", "PrimaryInsClass"]),
        on="InvoiceNo",
        how="inner",
    )

    # Map to our domain
    charges = (
        charges
        .join(facility_map, left_on="FacilityNo", right_on="ventra_facility_no")
        .join(payer_class_map,
              left_on="PrimaryInsClass",
              right_on="ventra_class_raw")
    )

    # Aggregate charges
    gross_by_day = (
        charges
        .group_by(["PostingDate", "site_id", "payer_class"])
        .agg(pl.col("ChargeAmt").sum().alias("gross_charges"))
    )

    # Same pattern for transactions: payments / adjustments / refunds
    # ... (split by TranType: Payment / Adjustment / Refund)

    # Filter to FL only (defense-in-depth — Ventra should have filtered)
    facility_map_fl = facility_map.filter(pl.col("state") == "FL")
    result = result.filter(
        pl.col("site_id").is_in(facility_map_fl["site_id"])
    )

    # Tag source_system
    result = result.with_columns(
        source_system=pl.lit("VENTRA_FL_ATHENA")
    )

    return result
```

### `fact_ar_snapshot`

Ventra's `Standard Data Extract` doesn't appear to ship a daily AR aging file directly — they ship per-invoice `CollectionBalance` + `IsInCollections` on the Invoice file. We compute aging from charge date + open balance.

```python
# aggregate/ar_snapshot.py
def compute_ar_snapshot(
    invoices: pl.DataFrame,
    chargelines: pl.DataFrame,
    snapshot_date: date,
) -> pl.DataFrame:
    """
    Compute AR aging from open invoices.
    Output grain: (snapshot_date, site_id, aging_bucket)
    """
    open_invoices = invoices.filter(pl.col("AccountStatus") == "Active")
    earliest_charge = (
        chargelines
        .group_by("InvoiceNo")
        .agg(pl.col("PostingDate").min().alias("first_charge_date"))
    )

    open_invoices = open_invoices.join(earliest_charge, on="InvoiceNo")
    open_invoices = open_invoices.with_columns(
        days_old=(pl.lit(snapshot_date) - pl.col("first_charge_date")).dt.days()
    )

    def bucket(days: int) -> str:
        if days < 0:
            return "credit"  # shouldn't happen but guard
        elif days <= 30:
            return "0-30"
        elif days <= 60:
            return "31-60"
        elif days <= 90:
            return "61-90"
        elif days <= 120:
            return "91-120"
        else:
            return "120+"

    open_invoices = open_invoices.with_columns(
        aging_bucket=pl.col("days_old").map_elements(bucket)
    )

    # Credit balances: CollectionBalance < 0 → "credit" bucket regardless of age
    credits = invoices.filter(pl.col("CollectionBalance") < 0)
    credits = credits.with_columns(aging_bucket=pl.lit("credit"))

    combined = pl.concat([open_invoices, credits])

    return (
        combined
        .join(facility_map, left_on="FacilityNo", right_on="ventra_facility_no")
        .filter(pl.col("state") == "FL")
        .group_by(["site_id", "aging_bucket"])
        .agg(pl.col("CollectionBalance").sum().alias("outstanding_amount"))
        .with_columns(
            snapshot_date=pl.lit(snapshot_date),
            source_system=pl.lit("VENTRA_FL_ATHENA"),
        )
    )
```

### `fact_revenue_by_physician_mo`

Source: `ChargeLines` (RVU + revenue + NPI) + `TransactionsAlt` (payments per encounter).

Grain: `(month, physician_npi)`. Run monthly, not daily.

```python
# aggregate/physician.py
def aggregate_physician_monthly(
    chargelines: pl.DataFrame,
    transactions: pl.DataFrame,
    month: date,
) -> pl.DataFrame:
    # Filter to charges in this month
    month_start = month.replace(day=1)
    month_end = (month_start + relativedelta(months=1)) - timedelta(days=1)

    charges = chargelines.filter(
        (pl.col("PostingDate") >= month_start) &
        (pl.col("PostingDate") <= month_end)
    )

    # Attribution: PrimaryPhysicianNPI (rendering provider)
    by_npi = (
        charges
        .group_by("PrimaryPhysicianNPI")
        .agg([
            pl.col("InvoiceNo").n_unique().alias("encounters_count"),
            pl.col("RVU").sum().alias("total_rvu"),
            pl.col("WorkRVU").sum().alias("total_work_rvu"),
            pl.col("ChargeAmt").sum().alias("revenue_attributed"),
        ])
    )

    return by_npi.with_columns(
        month=pl.lit(month_start),
        source_system=pl.lit("VENTRA_FL_ATHENA"),
    )
```

## Idempotency

Same file uploaded twice must produce the same database rows.

**Two layers:**

1. **File-checksum dedup** — every ingest computes SHA-256 of each file and stores in `ingest.file_checksum`. If a file with the same checksum already processed, skip.

   ```python
   # persist/checksum.py
   def already_processed(file_path: str, sha256: str, session) -> bool:
       result = session.execute(
           select(FileChecksum)
           .where(FileChecksum.path == file_path)
           .where(FileChecksum.sha256 == sha256)
           .where(FileChecksum.status == "completed")
       )
       return result.scalar() is not None
   ```

2. **UPSERT on natural key** — every fact table has a unique constraint matching its grain. Re-running with the same data is a no-op.

   ```sql
   INSERT INTO facts.collections_daily (...)
   VALUES (...)
   ON CONFLICT (site_id, posting_date, payer_class, source_system)
   DO UPDATE SET
       gross_charges = EXCLUDED.gross_charges,
       payments_received = EXCLUDED.payments_received,
       ...,
       created_at = now();
   ```

## Error handling

| Failure | Behavior |
|---|---|
| CSV won't parse (malformed) | Move file → `ventra-quarantine/<date>/`; write `ingest.run_log` failure row; **don't fail the whole job** if other files parse |
| New unknown column appears | Log warning, drop the column, continue. Akhil reviews log next morning. |
| TX site appears in feed | Log error, drop row, continue. Surface in daily ingest summary. |
| Postgres connection failure | Retry 3× with exponential backoff; if still failing, fail the job and alert. |
| File-checksum says already processed | Skip with log message; not an error. |
| Manifest arrives but no data files | Log error, fail the job. |
| Data files arrive but no manifest within 30 min | Cron-style watchdog (separate job) checks for orphans daily at 5 a.m. |

## Manifest pattern

Ventra writes 3 data files (or 1 on physician-monthly days). After all files land, they write `_MANIFEST.csv` last. Our Event Grid subscription filters to `_MANIFEST.csv` only — the ingest job never triggers on partial drops.

Manifest content:

```csv
date,file_count,checksum_collections,checksum_ar,checksum_physician
2026-05-12,3,sha256:abc...,sha256:def...,sha256:ghi...
```

Our job:

1. Receives Event Grid event with the manifest's blob path
2. Reads the manifest
3. Validates each listed file exists in the same folder
4. Verifies each file's SHA-256 matches the manifest
5. Proceeds to parse

**If Ventra can't write a manifest** (some standard cron dumps can't): fallback is a **fixed-time-window heuristic** — ingest 30 min after the first file in a daily folder lands. Less robust; documented in run_log.

## Bicep changes needed

`infra/env/prod.bicepparam` currently has:

```bicep
param enable_acr = false
param enable_container_jobs = false
```

To turn on Phase 2:

```bicep
param enable_acr = true
param enable_container_jobs = true
param enable_sftp = true
```

New Bicep modules required:

- `infra/modules/sftp.bicep` — enables SFTP on existing storage account, creates `ventra-incoming` + `ventra-quarantine` containers, sets lifecycle policy
- `infra/modules/eventgrid_ingestion.bicep` — system topic + subscription filtered to `_MANIFEST.csv`
- `infra/modules/container_apps_job.bicep` — Container Apps Environment + Job + Managed Identity

Update existing:

- `infra/main.bicep` — wire the new modules behind feature flags
- `infra/modules/keyvault.bicep` — grant the job's Managed Identity Key Vault Secrets User role

## SFTP user setup

Once SFTP is enabled, create a local SFTP user scoped to `ventra-incoming` only:

```bash
az storage account local-user create \
  --account-name sthhaprod \
  --user-name ventra \
  --permission-scope permissions=rwl service=blob resource-name=ventra-incoming \
  --has-ssh-key true \
  --has-ssh-password false
```

Generate an SSH key pair locally; upload the public key:

```bash
ssh-keygen -t ed25519 -f ./ventra-sftp-key -N ""
az storage account local-user update \
  --account-name sthhaprod \
  --user-name ventra \
  --ssh-authorized-key key="$(cat ./ventra-sftp-key.pub)"
```

Send Ventra:

- Endpoint: `sftp://ventra@sthhaprod.blob.core.windows.net`
- Public key: (the SSH key fingerprint they verify; private key stays on our side and is rotated via Key Vault)
- Folder convention: `/YYYY-MM-DD/`
- Manifest convention: write `_MANIFEST.csv` last

## Monitoring

The job writes structured logs via OpenTelemetry → Application Insights.

Key metrics:

- `ventra.ingest.duration_seconds` (histogram)
- `ventra.ingest.rows_processed` (counter, per-fact-table)
- `ventra.ingest.rows_stripped` (counter — for HIPAA audit)
- `ventra.ingest.errors` (counter, with `error_type` label)
- `ventra.ingest.quarantined_files` (counter)

Alerts (in Application Insights):

- Job not run in 26+ hours → page Akhil (daily expected by 7 a.m. CT)
- 3+ consecutive failures → page Akhil
- Quarantined file rate spikes (>5% of files in a week) → email Akhil

## How to test locally

```bash
cd hha-dashboard/jobs/ventra_ingest
uv sync
# Drop sample CSVs from Ventra's sandbox feed into ./fixtures/2026-05-12/
uv run python -m ventra_ingest.main --local --date 2026-05-12 \
  --fixtures-dir ./fixtures --database-url postgresql+psycopg://localhost/hha_dashboard_dev
```

CI runs the same with synthetic fixtures in `tests/fixtures/ventra/`.

## Rollout plan

| Step | Owner | Status |
|---|---|---|
| 1. Ventra responds to email (Option A vs B) | Ventra | Pending (PTO until 2026-05-14) |
| 2. Provision SFTP-enabled storage container | Akhil (Bicep) | Not started |
| 3. SSH key exchange with Ventra | Akhil + Ventra | Not started |
| 4. Build the ingest job container | Akhil | Not started |
| 5. Ventra delivers sample feed to sandbox | Ventra | Not started |
| 6. Build aggregator against sample data | Akhil | Not started |
| 7. Cutover to prod folder | Both | Not started |
| 8. Run for 2 weeks in shadow mode (write to facts.*_staging) | Both | Not started |
| 9. Reconciliation against Ventra's monthly report (target: ≤$1K/site variance) | Akhil + HHA finance | Not started |
| 10. Promote staging → prod, retire manual entry for FL | Akhil | Not started |

---

**Next read:** [API_ENDPOINT_CATALOG.md](API_ENDPOINT_CATALOG.md) for how the dashboard reads from these tables.
