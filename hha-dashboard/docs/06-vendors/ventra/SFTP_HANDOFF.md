# Ventra SFTP handoff (Phase 4 hybrid)

Operator-facing reference for the two Ventra SFTP feeds. Locked against
Ventra's real spec (`Standard Data Extract - Files Specifications.xlsx`,
received 2026-06-15) and their 2026-06-22 follow-up (zip delivery, signed
TranAmt, confirmed filenames).

## The two feeds

HHA runs **both** Ventra deliveries in parallel and reconciles them:

| Feed | SFTP user | Path | Files | PHI | Lifecycle |
|---|---|---|---|---|---|
| **Standard Data Extract** (Option 1, row-level) | `ventrastdspec` | `vendor-inbound/ventra/stdspec/` (one **zip** per drop) | 5 CSVs inside `HHA_Extact_YYYYMMDD.zip` | yes (stripped at edge) | 30 days |
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

Both land on the same storage account. Event Grid fires the **stdspec** job
on the drop **`.zip`** and the **preagg** job on its `_MANIFEST.csv`;
separate Container Apps Jobs process each.

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

## Delivery contract

### Standard Data Extract (stdspec) — single zip, no manifest

Per Ventra's 2026-06-22 reply, the stdspec feed is **one zip per drop**
(no `_MANIFEST.csv`):

- **Filename:** `HHA_Extact_YYYYMMDD.zip` (Ventra's spelling — "Extact";
  the pipeline tolerates "Extract" too). The `YYYYMMDD` is the drop /
  business date and is parsed as the drop date.
- **Contents:** exactly 5 comma-delimited CSVs with header rows —
  `Invoice.csv`, `ChargeLines.csv`, `Physician.csv`, `Facility.csv`,
  `TransactionsAlt.csv` (matched by stem, case-insensitive; `__MACOSX/` +
  dotfile noise is ignored).
- **Trigger:** Event Grid fires on the `.zip` BlobCreated event. The
  `data.api` advanced filter (incl. `FlushWithClose`) ensures it only fires
  once the upload is complete — never a partial zip.
- **Integrity:** the zip's own per-member CRC32 is the integrity check
  (validated on unzip). A corrupt member fails closed to quarantine (V1) —
  this replaces the old per-file sha256/row_count manifest checks.
- **Presence:** all 5 files must be in the zip (V2) or the drop quarantines.
- **Restate:** to correct a drop, re-deliver a zip with the same date; the
  pipeline dedups on the **zip's sha256** (V13) and routes a changed-content
  re-send to manual review.
- **Zip-bomb guard:** > 50 members or > 500 MB uncompressed → V1.

### Pre-aggregated (preagg) — manifest-last (unchanged)

The preagg feed keeps the `_MANIFEST.csv`-last contract: Ventra writes
`_MANIFEST.csv` after the 3 data files; Event Grid fires on it.
`file_name,sha256,row_count` per row; one folder per `YYYY-MM-DD` (UTC).

**FL only** — both feeds are Florida-only (ADR-005). Any non-FL facility
quarantines + raises an incident.

## Install the public keys + deploy

```powershell
# After az login:
.\scripts\deploy-ventra-sftp.ps1 -ImportKeys "docs\06-vendors\ventra\sftp-keys"
```

Prints the SFTP host + the two usernames to share back with Ventra.

## Checking connection activity (who connected, from what IP)

The **Transactions** platform metric is always-on but has **no source IP** —
it can tell you "something happened" but not "core-prd-mft01 connected." For
a definitive, IP-stamped answer you need the diagnostic **logs**.

Connection logging was enabled 2026-06-29 (dev) — currently ad-hoc via CLI,
**not yet codified in Bicep (TODO: add a `diagnosticSettings` on the vendor
blob service gated on `enable_monitor`):**

- Log Analytics workspace: `log-hha-vendor-dev` (RG `rg-hha-dashboard-dev`).
- Diagnostic setting `vendor-sftp-diag` on the blob service →
  `StorageRead` / `StorageWrite` / `StorageDelete`.

It is **forward-only** (no retroactive capture). Logs appear in the
workspace ~5–15 min after an event. Query (Logs blade on
`log-hha-vendor-dev`):

```kql
StorageBlobLogs
| where TimeGenerated > ago(2h)
| where CallerIpAddress startswith "52.177.111.231"   // core-prd-mft01 egress
| project TimeGenerated, CallerIpAddress, AuthenticationType, OperationName, Uri, StatusCode, StatusText
| order by TimeGenerated desc
```

`AuthenticationType == "LocalUserPublicKey"` = an SFTP key-auth connection;
`StatusCode`/`StatusText` shows success vs auth/permission failure. Recreate
the setting if the account is redeployed:

```bash
# Git Bash: MSYS_NO_PATHCONV=1 is required or the leading-slash resource IDs get mangled.
MSYS_NO_PATHCONV=1 az monitor diagnostic-settings create --name vendor-sftp-diag \
  --resource "<account-id>/blobServices/default" \
  --workspace "<log-hha-vendor-dev-id>" \
  --logs '[{"category":"StorageRead","enabled":true},{"category":"StorageWrite","enabled":true},{"category":"StorageDelete","enabled":true}]'
```

## Allowlisting a vendor egress IP

The firewall is deny-by-default; a vendor can't connect until their egress
IP is allowlisted:

```bash
az storage account network-rule add -g rg-hha-dashboard-dev \
  --account-name sthhavendordev5801224b --ip-address <vendor-egress-ip>
```

Current dev allowlist (2026-06-29): `71.227.196.232` (workstation),
`52.177.111.231` + `4.151.247.225` (Ventra `core-prd-mft01`).

## Confirmation items

Resolved by Ventra's 2026-06-22 reply:

- ✅ **Filenames + format** — `Invoice` / `ChargeLines` / `Physician` /
  `Facility` / `TransactionsAlt`, `.csv`, comma-delimited.
- ✅ **Delivery** — single zip per drop (no `_MANIFEST.csv`) for stdspec.
- ✅ **TranAmt sign** — signed (positive/negative). The aggregator nets
  same-type reversals and stores column magnitudes; a net-negative payments
  group fails closed as V10.

Still open (asked in the 2026-06-22 reply):

1. **Per-`TranType` sign convention** — Payment +, Refund −, Adjustment
   sign, and Transfer handling — so HHA's net-collections math matches
   Ventra's books.
2. **InsuranceClass / PrimaryInsClass value vocabulary** — exact strings →
   HHA's commercial/medicare/medicaid/selfpay/other. Unknown → `other`.
3. **Zip atomicity** — confirm the zip is visible only when fully written
   (rename-on-complete or visibility-on-close).
4. **Pre-aggregated feed also keys on FacilityNo 2284-2290** (assumed yes).

## Quarantine triage

A quarantined drop copies its files to
`vendor-quarantine/ventra/stdspec/YYYY-MM-DD/` plus a `_REJECT_REASON.txt`
sidecar (PHI-free). The sidecar's INCIDENT CLASS line says which playbook
to follow:

- `validation_failure` — schema / zip / presence issue (V1, V2, V5, V10,
  V13). Email ops; coordinate with Ventra on the file.
- `adr_005` — non-FL facility. Security playbook + investigate.
- `v15_phi_leak` — a PHI column survived the strip layer. **Deploy revert +
  24h HIPAA-reportability review.** Should be impossible given the
  allowlist; if it fires, treat as a hard incident.
