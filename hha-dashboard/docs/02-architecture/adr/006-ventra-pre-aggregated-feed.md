# ADR-006: Pre-Aggregated Ventra Feed via SFTP

- **Status:** Proposed (pending Ventra written confirmation)
- **Date:** 2026-05-11
- **Deciders:** Akhil Reddy (proposing); CEO + CFO co-sponsors (data classification scope per ADR-001 + ADR-005)
- **Supersedes:** None
- **Related:** [ADR-001 — HIPAA data classification](001-hipaa-data-classification.md), [ADR-005 — FL/TX scope split](005-fl-tx-scope-split.md)

## Context

After the 2026-05-05 working call, Ventra sent us their "Standard Data Extract" spec ([standard-data-extract-files-specifications.xlsx](../../06-vendors/ventra/standard-data-extract-files-specifications.xlsx)). That format is row-level — Invoice + Guarantor sheets with patient identifiers, claim IDs, dates of service, and other Tier-C columns per ADR-001's classification table.

Accepting that shape and stripping PHI on receipt is technically possible, but it places the HIPAA firewall *inside* HHA's ingestion pipeline rather than at the BAA boundary. Every bug, every log line, every error message, every retry trace becomes a potential PHI-leak surface — and HHA is a one-engineer shop with no second pair of eyes on PHI handling.

The alternative is to ask Ventra to deliver **pre-aggregated CSVs** that contain only Tier-A columns (state-date-bucket aggregates with no patient or claim linkage). Ventra already computes these aggregations internally for their own client-facing monthly reports; exposing them via a new daily SFTP channel is a delivery-mechanism change on Ventra's side, not new logic.

Akhil sent the proposal to Ventra on 2026-05-11 (see [docs/06-vendors/ventra/FOLLOWUP_EMAIL.md](../../06-vendors/ventra/FOLLOWUP_EMAIL.md)). This ADR documents the architectural decision contingent on Ventra's written confirmation.

## Decision

### Part 1 — Three pre-aggregated CSVs delivered daily via SFTP

Ventra will write three CSV files into an HHA-controlled Azure Storage SFTP endpoint under `vendor-inbound/ventra/YYYY-MM-DD/`. Schema:

**File 1 — `collections.csv`** (daily grain)

| Column | Type | Notes |
|---|---|---|
| `date` | DATE | Calendar day, Central time, payment posting date |
| `facility_no` | INT | Joins to Ventra's Facility file (FL only per Part 4) |
| `payer_class` | TEXT | `commercial | medicare | medicaid | selfpay | other` |
| `gross_charges` | DECIMAL(18,2) | Sum of charges posted that day |
| `payments_received` | DECIMAL(18,2) | Cash received that day |
| `contractual_adjustments` | DECIMAL(18,2) | Contractual write-downs |
| `write_offs` | DECIMAL(18,2) | Patient + bad-debt write-offs |
| `payer_refunds` | DECIMAL(18,2) | Recoupments back to payers |
| `patient_refunds` | DECIMAL(18,2) | Refunds to patients |
| `net_revenue` | DECIMAL(18,2) | Computed by Ventra per their formula |
| `source_system` | TEXT | Ventra's `CB | MGS | VSQL | DUVA` value |

**File 2 — `ar_snapshot.csv`** (daily snapshot)

| Column | Type | Notes |
|---|---|---|
| `snapshot_date` | DATE | End-of-business Central time |
| `facility_no` | INT | FL only |
| `aging_bucket` | TEXT | `0-30 | 31-60 | 61-90 | 91-120 | 120+ | credit` |
| `outstanding_amount` | DECIMAL(18,2) | Negative allowed only in `credit` bucket |
| `source_system` | TEXT | Same enum |

**File 3 — `physician_monthly.csv`** (monthly at close, restate-friendly)

| Column | Type | Notes |
|---|---|---|
| `month` | DATE | First day of month, Central time |
| `physician_npi` | VARCHAR(10) | 10-digit NPI |
| `facility_no` | INT | Primary attribution facility for the month |
| `encounters_count` | INT | Distinct encounters billed under this provider |
| `total_rvu` | DECIMAL(9,2) | Sum of RVUs |
| `total_work_rvu` | DECIMAL(9,2) | Sum of work RVUs |
| `revenue_attributed` | DECIMAL(18,2) | Net revenue attributed to provider |
| `source_system` | TEXT | Same enum |

No 18 HIPAA identifiers in any column. No claim IDs, encounter IDs, dates of service, patient names, DOBs, MRNs, member IDs, subscriber or guarantor fields. The schema is Tier-A per ADR-001.

### Part 2 — Four operational rules enforced at delivery

1. **Folder per day.** Each delivery writes to a new `/YYYY-MM-DD/` folder. No overwrites of prior-day files.
2. **Manifest written last.** A `_MANIFEST.csv` file is written *after* all data files have landed, listing each file with its SHA-256 checksum and row count. HHA's ingest job triggers only on the manifest, so partial drops never pick up.
3. **Florida only.** Ventra filters to HHA's FL facility list at source. Texas operations run on a separate manual track inside HHA (per ADR-005). Any TX `facility_no` reaching HHA is a runtime invariant violation and fires an incident alert.
4. **Net-revenue formula documented in writing.** One paragraph from Ventra documenting how `net_revenue` is computed — which adjustment categories are deducted, payment-posting vs date-of-service basis, late-posting handling. Without this, HHA's monthly reconciliation against Ventra's client reports cannot close.

### Part 3 — HHA-side ingestion contract

HHA reads the manifest, validates the files, and writes pre-aggregated rows directly into three fact tables:

- `entries.fact_collections_daily` — keyed `(date, facility_no, payer_class)`
- `entries.fact_ar_snapshot` — keyed `(snapshot_date, facility_no, aging_bucket)`
- `entries.fact_revenue_by_physician_mo` — keyed `(month, physician_npi, facility_no)`

All three carry `source_system = 'VENTRA_FL_ATHENA'` enforced by DB DEFAULT + CHECK constraint per ADR-005. No row-level data ever lands in DB or memory beyond what these CSVs contain.

Implementation details and validator rules (V1–V14) live in [docs/03-engineering/INGESTION_VENTRA.md](../../03-engineering/INGESTION_VENTRA.md).

### Part 4 — Texas remains entirely out of scope

Per ADR-005, HHA has no Ventra contract for Texas operations. Nothing in this ADR or the ingestion build accepts, processes, or stores TX data from Ventra. The FL-only invariant is enforced both at Ventra's source filter (Part 2 rule 3) AND at HHA's parse-time validation (validator V12) — defense in depth.

If HHA ever contracts a TX collections vendor, that is a new ADR + new ingestion path, not a mutation of this one.

## Alternatives considered

### Alternative A: Accept Ventra's row-level Standard Data Extract, strip PHI on receipt

**Mechanics:** Ventra delivers row-level Invoice + Guarantor CSVs. HHA's parser strips forbidden columns at read time per ADR-001's allowlist, logs strip events to `audit.audit_log`, aggregates in-memory by (date, facility, payer_class), then writes the same fact-table rows.

**Why rejected:**

- Adds ~3 weeks of build time and an ongoing re-audit burden on every Ventra schema change
- Places the HIPAA firewall *inside* HHA's pipeline — every error path, log line, telemetry export, retry trace, and quarantine sidecar becomes a potential PHI-leak surface
- Reconciliation against Ventra's monthly client reports becomes harder: HHA's aggregations may diverge from Ventra's by rounding or formula drift; pre-aggregated path is by definition bit-identical
- Single-engineer shop: no second pair of eyes on PHI handling correctness; one missed redaction in a stack trace = reportable breach + regulatory inquiry + potential Wall of Shame listing per 45 CFR §164.408 if >500 patients affected
- Memory pressure: row-level extracts can be hundreds of MB/month; Container Apps Job with 1 GiB RAM cannot slurp; streaming parser adds complexity for no architectural benefit

The build-cost difference (2 weeks vs 5 weeks) is recoverable. The structural-safety difference (zero-PHI vs always-need-to-prove-no-leak) is not.

### Alternative B: Pull from Athena directly (bypass Ventra)

**Why rejected:** HHA's BAA with Ventra is the contractual envelope. Bypassing Ventra would require a new BAA with Athenahealth and re-architecting Ventra's role in the RCM chain. Out of scope for this dashboard; Ventra is HHA's RCM provider per the FL contract, not a transport layer.

### Alternative C: Continue manual finance entry indefinitely (no Ventra integration)

**Why rejected:** The existing `entries.monthly_finance_manual` path (Sandy/Maribel entering monthly numbers) is the *fallback*, not the target. Manual entry is monthly-latency, error-prone, and ties up named operators on data-entry work. Phase-2 plan explicitly calls for automation here.

## Consequences

### Build implications

- Three new fact tables in migration `0011_ventra_facts.py`
- `ops` schema with `ingest_run` + `processed_files` in `0012_ingest_ops.py`
- Storage account gets `isHnsEnabled` + `isSftpEnabled` + a Ventra local-user with SSH key authorization
- Event Grid system topic + subscription on `_MANIFEST.csv` → Storage Queue → KEDA-triggered Container Apps Job
- Existing `jobs/ventra_ingest/parser.py` (built for an earlier single-row monthly CSV shape) gets rewritten to handle the 3-file daily shape
- API gains read endpoints under `/api/v1/finance/*` for the three fact tables
- Cost: +~$220/mo for SFTP-enabled storage per [Azure pricing](https://learn.microsoft.com/en-us/azure/storage/blobs/secure-file-transfer-protocol-support). Documented in `01-leadership/COST_AND_CAPACITY.md`.

### Operational implications

- Operator runbook covers SFTP credential rotation (quarterly), quarantine triage, manual re-trigger of a failed drop, and Azure Monitor alerts on validation failures
- ACS Email notifications fire on success (to Crystal + Akhil) and quarantine/failure (to ops list)
- Azure Monitor alert if no `ventra.ingest_complete` event arrives between 02:00–14:00 ET on a working day — catches silent failure (Ventra rotates their key, network blip, etc.)

### Reconciliation discipline

Because HHA's aggregations are now bit-identical to Ventra's source aggregations (we don't re-derive anything), monthly reconciliation against Ventra's client report is a direct match. A divergence > $1 in any line item is a real bug to investigate, not "rounding."

### What this ADR explicitly REJECTS

- **Accepting any row-level claim, encounter, or patient data from Ventra.** The agreed shape is aggregates only. If Ventra later proposes adding row-level fields "for context," the answer is no — propose new aggregate columns instead.
- **HHA computing aggregations from a row-level source on a future vendor.** This ADR sets the precedent for any future vendor: pre-aggregated at source, or we don't accept the feed.
- **Mixing the FL feed with anything TX-flavored.** ADR-005 stands; V12 enforces.

### Decision contingency

This ADR is **Proposed**, not **Accepted**. If Ventra refuses the pre-aggregated shape in writing, the ADR will be revised to either:

- Accept Alternative A explicitly (with the PHI-safety hardening plan documented as a separate ADR amendment), or
- Recommend a different vendor relationship change to the CEO + CFO co-sponsors

Until Ventra confirms in writing, no Bicep `enable_sftp=true` flag flips in prod and no SSH key gets installed.

## Verification

- `tests/test_schema_classification.py` — confirms `fact_collections_daily`, `fact_ar_snapshot`, `fact_revenue_by_physician_mo` contain no forbidden column names. CI fails any migration that adds one.
- `jobs/ventra_ingest/tests/test_validators.py` — V12 (FL-only invariant) rejects any drop containing a non-FL `facility_no`.
- `jobs/ventra_ingest/tests/fixtures/bad_drops/tx_facility/` — fixture demonstrating that a TX `facility_no` reaching the pipeline is quarantined + fires incident alert.
- Manual: after first real Ventra drop arrives in dev, run `SELECT DISTINCT source_system FROM entries.fact_collections_daily` — must return only `VENTRA_FL_ATHENA`.
- Manual: reconcile first month of `fact_collections_daily` totals against Ventra's monthly client report PDF. Variance must be $0 in every line; any drift indicates a delivery-side bug to flag to Ventra.

## References

- [docs/06-vendors/ventra/FOLLOWUP_EMAIL.md](../../06-vendors/ventra/FOLLOWUP_EMAIL.md) — the proposal sent to Ventra
- [docs/06-vendors/ventra/standard-data-extract-files-specifications.xlsx](../../06-vendors/ventra/standard-data-extract-files-specifications.xlsx) — Ventra's row-level format (rejected as input shape)
- [docs/03-engineering/INGESTION_VENTRA.md](../../03-engineering/INGESTION_VENTRA.md) — implementation plan for the agreed shape
- [ADR-001 — HIPAA data classification](001-hipaa-data-classification.md) — the Tier-A/B/C/D classification table this ADR depends on
- [ADR-005 — FL/TX scope split](005-fl-tx-scope-split.md) — the `source_system` invariant + FL-only Ventra contract
- [api/alembic/versions/0011_ventra_facts.py](../../../../api/alembic/versions/0011_ventra_facts.py) — fact-table migration (to be created)
- [api/alembic/versions/0012_ingest_ops.py](../../../../api/alembic/versions/0012_ingest_ops.py) — ops schema migration (to be created)
