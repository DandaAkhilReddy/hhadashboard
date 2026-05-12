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

### `facts.collections_daily`

Daily collections from Ventra (FL) or rolled-up from `entries.monthly_finance_manual` (TX).

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | A | |
| `site_id` | int (FK) | A | |
| `posting_date` | date | A | Payment posting date (Central time) |
| `payer_class` | varchar(20) | A | `commercial`, `medicare`, `medicaid`, `selfpay`, `other` |
| `source_system` | varchar(30) | A | `VENTRA_FL_ATHENA` or `HHA_TX_MANUAL` |
| `gross_charges` | decimal(18,2) | A | |
| `payments_received` | decimal(18,2) | A | |
| `contractual_adjustments` | decimal(18,2) | A | |
| `write_offs` | decimal(18,2) | A | |
| `payer_refunds` | decimal(18,2) | A | |
| `patient_refunds` | decimal(18,2) | A | |
| `net_revenue` | decimal(18,2) | A | Pre-computed by Ventra (preferred) or derived |
| `created_at` | timestamptz | A | |

**Uniqueness:** `(site_id, posting_date, payer_class, source_system)` — UPSERT key.
**RBAC:** read access requires `exec` or `comp_viewer` role.

### `facts.ar_snapshot`

AR aging snapshot. Daily snapshots preferred; month-end acceptable for v1.

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | A | |
| `site_id` | int (FK) | A | |
| `snapshot_date` | date | A | End-of-business Central time |
| `aging_bucket` | varchar(20) | A | `0-30`, `31-60`, `61-90`, `91-120`, `120+`, `credit` |
| `outstanding_amount` | decimal(18,2) | A | Negative values only in `credit` bucket |
| `source_system` | varchar(30) | A | |

**Uniqueness:** `(site_id, snapshot_date, aging_bucket, source_system)`.

### `facts.revenue_by_physician_mo`

Per-physician monthly metrics. Drives Doctor Scorecards.

| Column | Type | Class | Description |
|---|---|---|---|
| `id` | int (PK) | A | |
| `month` | date | A | First-of-month |
| `physician_npi` | varchar(10) | A (FK to masters.physicians.npi) | |
| `facility_no` | int | A | Primary attribution facility for the month |
| `encounters_count` | int | A | Distinct encounters this month |
| `total_rvu` | decimal(9,2) | A | |
| `total_work_rvu` | decimal(9,2) | A | |
| `revenue_attributed` | decimal(18,2) | A | |
| `chart_turnaround_median_hours` | decimal(9,2) | A | Provisional — only if Ventra captures |
| `pct_notes_signed_within_24h` | decimal(5,2) | A | Provisional |
| `source_system` | varchar(30) | A | |

**Uniqueness:** `(month, physician_npi, source_system)`.
**RBAC:** read access requires `exec` only (no `comp_viewer` — scorecards are exec-only, per ADR-002).

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
