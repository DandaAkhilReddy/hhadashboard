# Ventra SFTP handoff (Phase 4 hybrid)

Operator-facing reference for the two Ventra SFTP feeds. Locked against
Ventra's real spec (`Standard Data Extract - Files Specifications.xlsx`,
received 2026-06-15).

## The two feeds

HHA runs **both** Ventra deliveries in parallel and reconciles them:

| Feed | SFTP user | Path | Files | PHI | Lifecycle |
|---|---|---|---|---|---|
| **Standard Data Extract** (Option 1, row-level) | `ventrastdspec` | `vendor-inbound/ventra/stdspec/YYYY-MM-DD/` | 5 (below) | yes (stripped at edge) | 30 days |
| **Pre-aggregated** (Option 2) | `ventrapreagg` | `vendor-inbound/ventra/preagg/YYYY-MM-DD/` | 3 (collections/ar/physician) | no | 90 days |

> SFTP local-user names are lowercase-alphanumeric (Azure requirement — no
> hyphens). The full SFTP username is `<storage-account>.ventrastdspec` /
> `<storage-account>.ventrapreagg`. The `.pub` key filenames keep the
> hyphen (`ventra-stdspec.pub`) — those are just file names.
>
> **Dev endpoint (live 2026-06-17):** host
> `sthhavendordev5801224b.blob.core.windows.net:22`, users
> `sthhavendordev5801224b.ventrastdspec` /
> `sthhavendordev5801224b.ventrapreagg`. Firewall is Deny-by-default; add
> Ventra's egress IPs with
> `az storage account network-rule add -g rg-hha-dashboard-dev --account-name sthhavendordev5801224b --ip-address <ip>`.

Both land on the same storage account; Event Grid fires on each feed's
`_MANIFEST.csv`; separate Container Apps Jobs process each.

## Standard Data Extract — the 5 files HHA ingests

Per the 2026-06-15 decision HHA requests files **1-4 + 5** and declines
6-10 (and Guarantor, #9):

| # | File | What HHA uses it for |
|---|---|---|
| 1 | **Invoice** | InvoiceNo → FacilityNo + payer class (PrimaryInsClass). Header linkage. |
| 2 | **ChargeLines** | Gross charges (ChargeAmt), RVU/WorkRVU, billed NPI, posting date. |
| 3 | **Physician** | NPI → provider name + type (Tier-B directory). |
| 4 | **Facility** | FacilityNo → name + client. |
| 5 | **TransactionsAlt** | Payments / adjustments / refunds — **required** to reconstruct collections. |

Files 1-4 alone give charges + RVU + encounters but **no payments**;
TransactionsAlt (#5) is what makes the collections numbers reconstructable
and the reconciliation against the pre-aggregated feed meaningful.

### PHI handling

The Invoice + ChargeLines + (declined) Guarantor files carry patient PHI
(MRN, names, SSN, DOB, addresses, policy IDs, CPT/ICD). HHA strips every
PHI column **at the parser edge** via an allowlist — only a small set of
non-PHI columns per file is kept, everything else is dropped before any
row reaches memory-aggregation, the DB, a log, or telemetry. Raw inbound
files auto-delete after 30 days. No PHI is ever persisted (ADR-001).

## Facility mapping

Ventra keys by `FacilityNo` (2284-2290); HHA keys by `masters.sites.id`
(1-7). The mapping lives in `dims.facility_codes` (migration 0014) and is
resolved at ingest — the fact tables store the HHA site_id:

| Ventra FacilityNo | Ventra name | HHA site |
|---|---|---|
| 2284 | Jackson Memorial Hospital | Jackson Memorial |
| 2285 | HCA Florida JFK Main Hospital | JFK Main Med Ctr |
| 2286 | HCA Florida JFK North Hospital | JFK North Med Ctr |
| 2287 | HCA Florida Palms West Hosp | Palms West Hospital |
| 2288 | HCA Florida University Hosp | University Hospital |
| 2289 | HCA Florida Westside Hospital | Westside Regional |
| 2290 | HCA Florida Woodmont Hospital | Woodmont Hospital |

A FacilityNo with no active mapping → the drop is **quarantined (V8)** until
the mapping is added (fail-closed). A FacilityNo that maps to a non-FL site
→ **incident (V12 / ADR-005)**.

## Manifest contract (both feeds)

Ventra writes `_MANIFEST.csv` **LAST**, after every data file is fully
uploaded — this is the trigger. Format:

```
file_name,sha256,row_count
Invoice.csv,<64-hex-sha256>,12345
ChargeLines.csv,<64-hex-sha256>,98765
Physician.csv,<64-hex-sha256>,42
Facility.csv,<64-hex-sha256>,7
TransactionsAlt.csv,<64-hex-sha256>,54321
```

Rules:
- **Manifest last** — Event Grid only fires on `_MANIFEST.csv`; a partial
  drop never triggers a job.
- **One folder per drop date** — `YYYY-MM-DD` (UTC).
- File names are matched by **stem** (case + extension insensitive), so
  `Invoice.csv` / `invoice.CSV` / `Invoice.txt` all resolve. The exact
  delivered filename + extension + delimiter is an open confirmation item
  (see below).
- **FL only** — both feeds are Florida-only (ADR-005). Any non-FL facility
  quarantines + raises an incident.
- **Restate** — to correct a drop, re-deliver under the same date; the
  pipeline detects the sha256 change (V13) and routes to manual review.

## Install the public keys + deploy

```powershell
# After az login:
.\scripts\deploy-ventra-sftp.ps1 -ImportKeys "docs\06-vendors\ventra\sftp-keys"
```

Prints the SFTP host + the two usernames to share back with Ventra.

## Open confirmation items (ask Ventra)

1. **Exact delivered filenames + extension + delimiter** (`Invoice.csv`?
   `.txt`? pipe-delimited?). The pipeline is stem/extension-tolerant but
   the manifest `file_name` must match what's uploaded.
2. **InsClass / InsuranceClass value vocabulary** — the exact strings
   Ventra uses (to map → HHA's commercial/medicare/medicaid/selfpay/other).
   The normalizer defaults unknown values to `other`.
3. **TranAmt sign convention** — are payments positive or negative? The
   aggregator currently uses magnitude (abs) per the fact tables'
   non-negative columns; confirm against the first sample.
4. **Pre-aggregated feed also keys on FacilityNo 2284-2290** (assumed yes).

## Quarantine triage

A quarantined drop copies its files to
`vendor-quarantine/ventra/stdspec/YYYY-MM-DD/` plus a `_REJECT_REASON.txt`
sidecar (PHI-free). The sidecar's INCIDENT CLASS line says which playbook
to follow:
- `validation_failure` — schema / manifest issue. Email ops; coordinate
  with Ventra on the file.
- `adr_005` — non-FL facility. Security playbook + investigate.
- `v15_phi_leak` — a PHI column survived the strip layer. **Deploy revert +
  24h HIPAA-reportability review.** Should be impossible given the
  allowlist; if it fires, treat as a hard incident.
