# Data model

> **For engineers.** Every schema, every table, every column. Cross-reference to SQLAlchemy model files and HIPAA classification.
>
> Source of truth for schema **structure** is `hha-dashboard/api/app/models/`. This doc is the human-readable reference.
>
> Visual ERD in [DIAGRAMS.md § 9](DIAGRAMS.md#9-schema-erd). HIPAA classification rules in [adr/001-hipaa-data-classification.md](adr/001-hipaa-data-classification.md). Last updated 2026-05-11.

## Six schemas, one database

Postgres physical database: `hha_dashboard` on `psql-hha-prod.postgres.database.azure.com`.

| Schema | Purpose | Audit triggers? |
|---|---|---|
| `masters` | Reference data — sites, physicians, contracts, payer mappings | ✅ Yes |
| `entries` | Manual entry — census, monthly finance, open positions | ✅ Yes |
| `facts` | Automated aggregated facts from Ventra/Paycom/jobs | ✅ Yes |
| `audit` | Audit log itself (append-only) | ❌ No (target table) |
| `alerts` | Alert routing and history | ✅ Yes |
| `dims` | Dimension tables (Phase 2+) | ✅ Yes |

## Data classification recap

Every column carries a `data_class` tag in its SQLAlchemy `info={}`. Four tiers:

| Tier | What it is | Allowed in Postgres? |
|---|---|---|
| **A** | Operational aggregates | ✅ Yes |
| **B** | Internal operational data | ✅ Yes |
| **C** | Limited Data Set (per-encounter timestamps, claim_id) | ❌ Never |
| **D** | Full PHI (patient name, DOB, SSN, MRN) | ❌ Never |

`tests/test_schema_classification.py` walks the SQLAlchemy registry and fails CI if any new column has `data_class=C` without sponsor approval (or `data_class=D` at all).

---

## `masters` schema

Reference data. Slow-changing. Source-of-truth for site and physician identity.

### `masters.sites`

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | B | Surrogate primary key |
| `site_code` | varchar(20) | B | Internal site code (e.g. `WESTSIDE`, `WOODMONT`) |
| `npi` | varchar(10) | B | NPI of the facility |
| `name` | varchar(100) | B | Full facility name |
| `state` | varchar(2) | B | `FL` or `TX` |
| `client_no` | int | B | Ventra-internal client/facility ID (FL sites only) |
| `service_line` | varchar(50) | B | E.g. ED, Hospitalist |
| `is_active` | boolean | B | Soft-delete flag |
| `created_at` | timestamptz | B | Audit timestamp |
| `updated_at` | timestamptz | B | Audit timestamp |

**Indexes:** unique on `site_code`, unique on `npi`.
**SQLAlchemy model:** `api/app/models/site.py:Site`
**Seed source:** `scripts/seed_sites.py` (11 rows: 9 FL + 2 TX as of 2026-05-04)

### `masters.physicians`

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | B | Surrogate PK |
| `npi` | varchar(10) | B | NPI (unique) |
| `first_name` | varchar(50) | B | First name (operational, not patient — physician) |
| `last_name` | varchar(50) | B | Last name |
| `doc_type` | varchar(20) | B | `Doctor` or `Midlevel` |
| `employment_type` | varchar(20) | B | `W2`, `1099`, `Locum` |
| `is_active` | boolean | B | Soft-delete flag |
| `primary_site_id` | int (FK) | B | Primary attribution site |

**Note:** physicians' names are tier B (internal operational data, not patient PHI). They appear on scorecards.

### `masters.contracts`

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | B | |
| `site_id` | int (FK) | B | Site under contract |
| `start_date` | date | B | |
| `end_date` | date | B | nullable for open-ended |
| `contract_type` | varchar(50) | B | `Hospitalist`, `ED`, etc. |
| `is_active` | boolean | B | |

### `masters.comp_agreements`

Time-variant compensation agreements per physician. Implements the "Stark / AKS comp viewer" model from [adr/002-rbac-model.md](adr/002-rbac-model.md).

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | B | |
| `physician_id` | int (FK) | B | |
| `effective_from` | date | B | |
| `effective_through` | date | B | nullable for current |
| `comp_model` | varchar(50) | B | `Salary`, `RVU`, `Hybrid`, `1099` |
| `base_amount` | decimal(18,2) | B | If salaried |
| `rvu_rate` | decimal(9,2) | B | If RVU model |
| `created_by_upn` | varchar(100) | B | Who entered the agreement |
| `created_at` | timestamptz | B | |

**RBAC:** read access requires `comp_viewer` Entra group membership (additive flag, see ADR-002).

### `masters.payer_class_map`

Maps Ventra's raw `PrimaryInsClass` values to our 5-bucket payer class.

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | B | |
| `ventra_class_raw` | varchar(50) | B | E.g. `BCBS PPO`, `Medicare Advantage` |
| `payer_class` | varchar(20) | B | One of `commercial`, `medicare`, `medicaid`, `selfpay`, `other` |

---

## `entries` schema

Hand-entered data. Forms in the web UI write here.

### `entries.census_daily`

The Phase 1 census-portal table. Source for the Operations board.

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | A | |
| `site_id` | int (FK) | A | |
| `entry_date` | date | A | Calendar date the census is for (not entry time) |
| `census_count` | int | A | Number of patients on census |
| `source` | varchar(20) | A | `portal` or `manual` (admin web UI) |
| `notes` | text | A | Optional free text (no PHI) |
| `created_by_upn` | varchar(100) | A | Who entered |
| `created_at` | timestamptz | A | |

**Uniqueness:** `(site_id, entry_date)` — only one row per site per day; updates UPSERT.

### `entries.monthly_finance_manual`

Used for **Texas** sites only (Florida is automated through Ventra). Sandy/Maribel enter monthly totals.

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | A | |
| `site_id` | int (FK) | A | |
| `month` | date | A | First-of-month |
| `gross_charges` | decimal(18,2) | A | |
| `collections` | decimal(18,2) | A | |
| `ar_balance_end_of_month` | decimal(18,2) | A | |
| `source_system` | varchar(30) | A | Always `HHA_TX_MANUAL` here |
| `created_by_upn` | varchar(100) | A | |
| `created_at` | timestamptz | A | |

### `entries.open_positions`

Manual entry of open positions, used by People & Pipeline board.

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | A | |
| `site_id` | int (FK) | A | |
| `role` | varchar(100) | A | Position title |
| `opened_date` | date | A | |
| `target_fill_date` | date | A | |
| `status` | varchar(20) | A | `open`, `offered`, `filled`, `cancelled` |

---

## `facts` schema

Aggregate facts. Sources: Ventra (Phase 2), Paycom (Phase 4), and computed from `entries.*`.

### `entries.fact_collections_daily` *(Ventra pre-aggregated, ADR-006)*

Daily collections from Ventra (FL only). Live as of migration 0011. **Lives in `entries` schema, not `facts`** — the original plan was a separate `facts` schema but the build landed everything under `entries.*` to keep the audit-trigger configuration scope flat. Same Tier-A classification either way.

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | A | Surrogate; natural unique below |
| `date` | date | A | Payment posting date (Central time) |
| `facility_no` | int | A | Joins to `masters.sites.id` (v1; future: `masters.sites.ventra_facility_no` if Ventra insists on their IDs) |
| `payer_class` | varchar(20) | A | CHECK in (`commercial`, `medicare`, `medicaid`, `selfpay`, `other`) |
| `gross_charges` | numeric(18,2) | A | CHECK >= 0 |
| `payments_received` | numeric(18,2) | A | CHECK >= 0 |
| `contractual_adjustments` | numeric(18,2) | A | default 0 |
| `write_offs` | numeric(18,2) | A | default 0 |
| `payer_refunds` | numeric(18,2) | A | default 0 |
| `patient_refunds` | numeric(18,2) | A | default 0 |
| `net_revenue` | numeric(18,2) | A | Ventra-computed (see net-revenue formula doc) |
| `source_system` | varchar(30) | A | DB CHECK locked to `'VENTRA_FL_ATHENA'` |
| `state` | char(2) | A | DB CHECK locked to `'FL'` |
| `ingest_run_id` | uuid | A | FK-equivalent to `ops.ingest_run.run_id` (no DB FK — app-enforced) |
| `created_at` | timestamptz | A | |
| `updated_at` | timestamptz | A | UPSERT bumps |

**Uniqueness (UPSERT key):** `(date, facility_no, payer_class)` — `uq_collections_daily_natural`.
**Indexes:** `date`, `facility_no`, `ingest_run_id`.
**Audit trigger:** `audit_fact_collections_daily_change` (migration 0011 + `app.services.audit.AUDITED_TABLES`).
**RBAC:** read access via `GET /api/v1/finance/daily-collections`, gated to `owner_finance` / `admin` / `exec`.

### `entries.fact_ar_snapshot` *(Ventra pre-aggregated, ADR-006)*

AR aging snapshot. Daily snapshots preferred; month-end acceptable for v1.

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | A | |
| `snapshot_date` | date | A | End-of-business Central time |
| `facility_no` | int | A | |
| `aging_bucket` | varchar(10) | A | CHECK in (`0-30`, `31-60`, `61-90`, `91-120`, `120+`, `credit`) |
| `outstanding_amount` | numeric(18,2) | A | CHECK >= 0 unless `aging_bucket = 'credit'` |
| `source_system` | varchar(30) | A | DB CHECK locked to `'VENTRA_FL_ATHENA'` |
| `state` | char(2) | A | DB CHECK locked to `'FL'` |
| `ingest_run_id` | uuid | A | |
| `created_at`, `updated_at` | timestamptz | A | |

**Uniqueness (UPSERT key):** `(snapshot_date, facility_no, aging_bucket)`.
**RBAC:** read access via `GET /api/v1/finance/ar-snapshot`, gated to `owner_finance` / `admin` / `exec`.

### `entries.fact_revenue_by_physician_mo` *(Ventra pre-aggregated, ADR-006)*

Per-physician monthly metrics. Drives Doctor Scorecards.

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | A | |
| `month` | date | A | First-of-month; CHECK `month = date_trunc('month', month)::date` |
| `physician_npi` | varchar(10) | A | CHECK `~ '^[0-9]{10}$'` |
| `facility_no` | int | A | Primary attribution facility for the month |
| `encounters_count` | int | A | CHECK >= 0 |
| `total_rvu` | numeric(9,2) | A | CHECK >= 0, default 0 |
| `total_work_rvu` | numeric(9,2) | A | CHECK >= 0, default 0 |
| `revenue_attributed` | numeric(18,2) | A | |
| `source_system` | varchar(30) | A | DB CHECK locked to `'VENTRA_FL_ATHENA'` |
| `state` | char(2) | A | DB CHECK locked to `'FL'` |
| `ingest_run_id` | uuid | A | |
| `created_at`, `updated_at` | timestamptz | A | |

**Uniqueness (UPSERT key):** `(month, physician_npi, facility_no)`.
**Indexes:** `month`, `physician_npi`, `ingest_run_id`.
**RBAC:** read access via `GET /api/v1/finance/physician-monthly`, gated to `owner_finance` / `admin` / `exec` (NOT `comp_viewer` — revenue is non-comp).

**Chart-turnaround columns deferred:** the earlier plan included `chart_turnaround_median_hours` + `pct_notes_signed_within_24h`. ADR-006 narrowed the v1 spec to revenue + RVU + encounter count only; chart-turnaround signals stay in `entries.weekly_clinical` (manually entered) for now.

### `facts.headcount_daily`

Headcount from Paycom (Phase 4) or manual entry.

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | A | |
| `site_id` | int (FK) | A | |
| `snapshot_date` | date | A | |
| `w2_count` | int | A | |
| `contractor_count` | int | A | |
| `total_count` | int | A | |
| `source_system` | varchar(30) | A | `PAYCOM` or `HHA_MANUAL` |

### `facts.rvu_paycheck`

RVU per physician per pay period.

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | A | |
| `physician_id` | int (FK) | A | |
| `pay_period_end` | date | A | |
| `rvu_count` | decimal(9,2) | A | |
| `paycheck_amount` | decimal(18,2) | A | |
| `source_system` | varchar(30) | A | |

### `facts.terminations`

Departures from Paycom.

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | A | |
| `site_id` | int (FK) | A | |
| `physician_id` | int (FK) | A | nullable (some terminations are non-physician) |
| `termination_date` | date | A | |
| `reason_code` | varchar(50) | A | Voluntary / involuntary / contract-end |

### `facts.scorecard_snapshot`

Computed scorecard rankings per physician per month. Materialized by a nightly job; not authoritative source — just for fast read.

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | A | |
| `month` | date | A | |
| `physician_id` | int (FK) | A | |
| `overall_rank_score` | decimal(9,2) | A | Composite — see [boards/DOCTOR_SCORECARDS.md](../05-product/boards/DOCTOR_SCORECARDS.md) for formula |
| `rvu_pct_of_peers` | decimal(5,2) | A | |
| `revenue_per_fte_rank` | int | A | |

---

## `audit` schema

### `audit.audit_log`

**Append-only.** No DELETE permission for app users. Backed up to immutable Blob daily.

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | bigint (PK) | B | |
| `actor_upn` | varchar(100) | B | Who made the change (set via `audit.upn` GUC) |
| `actor_role` | varchar(50) | B | Their effective role at the time |
| `table_schema` | varchar(50) | B | Schema name |
| `table_name` | varchar(100) | B | Table name |
| `operation` | varchar(10) | B | `INSERT`, `UPDATE`, `DELETE` |
| `row_id` | bigint | B | PK of the changed row |
| `diff` | jsonb | B | Column-level diff (`{col: {old, new}}`) |
| `occurred_at` | timestamptz | B | UTC timestamp |

**Trigger function:** `audit.log_change()` — fires AFTER INSERT/UPDATE/DELETE on every audited table. Reads `current_setting('audit.upn', true)` for the actor.
**Retention:** 7 years (HIPAA standard).
**Backup:** included in nightly `pg_dump` → Blob WORM.

ADR-003 covers the design rationale: [adr/003-audit-chain.md](adr/003-audit-chain.md).

---

## `ops` schema *(Phase 1B — ingest telemetry)*

Operational state for the Ventra ingest pipeline (and any future vendor pipelines that adopt the same shape). Created in migration 0012. **NOT in `AUDITED_TABLES`** — auditing the auditor adds noise without value.

### `ops.ingest_run`

One row per Container Apps Job replica execution. INSERTed by `IngestRun.start()` (status `running`); UPDATEd by `IngestRun.complete()` to a terminal status. Operators query this for "did Ventra deliver today?" and post-incident forensics.

| Column | Type | Class | Description |
|---|---|---|---|
| `run_id` | uuid (PK) | A | `gen_random_uuid()` default |
| `vendor` | text | A | `'ventra'` (extensible for future vendors) |
| `drop_date` | date | A | YYYY-MM-DD folder under `vendor-inbound/` |
| `manifest_path` | text | A | Full blob path of the manifest that triggered this run |
| `status` | text | A | CHECK in (`queued`, `running`, `succeeded`, `failed`, `quarantined`) |
| `started_at` | timestamptz | A | `now()` default |
| `completed_at` | timestamptz | A | nullable until terminal state |
| `files_count` | int | A | nullable; CHECK >= 0 |
| `rows_in` | int | A | total rows seen across all data files; CHECK >= 0 |
| `rows_out` | int | A | total rows written to fact tables; CHECK >= 0 |
| `error_message` | text | A | populated on `failed` / `quarantined` |
| `error_details` | jsonb | A | structured rule + line_no + facility_no etc. |
| `correlation_id` | uuid | A | App Insights cross-system trace key |

**Indexes:** `(status, started_at DESC)` for queue-style queries, `(vendor, drop_date)` for drop-history queries, `correlation_id` for cross-system tracing.

### `ops.processed_files`

Dedup ledger for V13 (vendor re-delivery detection). One row per data file successfully ingested. Composite PK + UNIQUE on `(vendor, sha256)` so the same file content can't be processed twice across different drops.

| Column | Type | Class | Description |
|---|---|---|---|
| `vendor` | text | A | PK part 1 |
| `drop_date` | date | A | PK part 2 |
| `file_name` | text | A | PK part 3 |
| `blob_path` | text | A | full path under vendor-inbound for replay |
| `sha256` | char(64) | A | CHECK `~ '^[0-9a-f]{64}$'` |
| `row_count` | int | A | CHECK >= 0 |
| `processed_at` | timestamptz | A | `now()` default |
| `run_id` | uuid (FK → ops.ingest_run.run_id) | A | RESTRICT — never cascade-delete runs |

**Uniqueness:** PK `(vendor, drop_date, file_name)` + secondary UNIQUE `(vendor, sha256)`.
**V13 contract:** orchestrator queries `WHERE vendor='ventra' AND drop_date=:dd` to classify each manifest entry as fresh / already_processed / conflict.

---

## `alerts` schema

### `alerts.alert_subscriptions`

Who gets which alerts at what cadence.

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | B | |
| `email` | varchar(255) | B | Recipient |
| `role` | varchar(50) | B | E.g. `exec`, `owner_finance` |
| `categories` | jsonb | B | E.g. `["census_variance", "ar_threshold", "credentials_30d"]` |
| `frequency` | varchar(20) | B | `daily`, `weekly`, `realtime` |
| `is_active` | boolean | B | |

**Seed:** `scripts/seed_alert_subscriptions.py` (currently seeds `areddy@hhamedicine.com` exec/daily/all).

### `alerts.alert_history`

Log of which alerts have fired.

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | bigint (PK) | B | |
| `subscription_id` | int (FK) | B | |
| `fired_at` | timestamptz | B | |
| `category` | varchar(50) | B | |
| `payload` | jsonb | B | The summary that was emailed |

---

## `dims` schema (Phase 2+)

Dimension tables for slowly-changing reference data we don't own.

### `dims.facility_codes` (planned)

Maps Ventra's `FacilityNo` → HHA's `site_id`.

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | B | |
| `ventra_facility_no` | int | B | Unique |
| `site_id` | int (FK) | B | |
| `effective_from` | date | B | |
| `effective_through` | date | B | nullable |

### `dims.payer_class` (planned)

The 5 payer-class enum values + their order.

| Column | Type | Class | Description |
|---|---|---|---|
| `code` | varchar(20) (PK) | B | `commercial`, etc |
| `display_name` | varchar(50) | B | Human-readable |
| `sort_order` | int | B | Display order on charts |

---

## How to add a new column

The checklist for adding a column anywhere in `facts`, `entries`, or `masters`:

1. **Add to the SQLAlchemy model** with `info={"data_class": "A"}` (or B; never C or D).
2. **Generate alembic migration**: `cd api && uv run alembic revision --autogenerate -m "add <field> to <table>"`
3. **Inspect the migration** — autogen sometimes misses constraints.
4. **Run CI locally**: `cd api && uv run pytest tests/test_schema_classification.py` — must pass.
5. **Pre-commit hook** runs on commit and blocks if column name matches a forbidden pattern (`patient_*`, `mrn`, etc.).
6. **Update this doc** with the new column row.

If the column genuinely needs `data_class=C`, that's a sponsor decision. Don't do it without ADR.

## How to drop a column

1. Confirm nothing reads it (grep `api/`, `web/`, jobs/)
2. Mark deprecated in the model for one release
3. Alembic migration drops the column
4. **Update audit_log expectations** — old audit log rows may reference the dropped column in their `diff` jsonb; that's fine, just don't break the trigger.
5. Update this doc.

---

**Next read:** [INGESTION_VENTRA.md](../03-engineering/INGESTION_VENTRA.md) — how data gets INTO these tables.
