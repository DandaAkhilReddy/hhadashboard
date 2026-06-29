# ADR-007: Ventra Hybrid — Dual-Source Parallel-Run (Standard Spec + Pre-Aggregated)

- **Status:** Accepted
- **Date:** 2026-05-25 (zip + signed-TranAmt deltas added 2026-06-28)
- **Deciders:** Akhil Reddy; Ventra (Gilda Romero / Dinesh Reddy Kandari)
- **Supersedes:** Partially supersedes [ADR-006](006-ventra-pre-aggregated-feed.md) — both feeds now run in parallel rather than pre-aggregated-only
- **Related:** [ADR-001 — HIPAA data classification](001-hipaa-data-classification.md), [ADR-005 — FL/TX scope split](005-fl-tx-scope-split.md), [ADR-006 — pre-aggregated feed](006-ventra-pre-aggregated-feed.md)

## Context

Ventra accepted the **Hybrid Option** on 2026-05-29: implement Option 1
(their row-level **Standard Data Extract**, which contains PHI) as the
interim while building toward Option 2 (HHA's **pre-aggregated** feed, no
PHI). Rather than a sequential cutover, HHA runs **both feeds in parallel**
and reconciles them. This is safer than a blind flip: aggregation drift
between HHA's math and Ventra's surfaces as a reconciliation alert instead
of a silent dashboard discrepancy, and the row-level feed is an audit-grade
independent reference even after Option 2 stabilizes.

Ventra's 2026-06-15 spec sheet + 2026-06-22 follow-up pinned the wire
contract. The follow-up changed two assumptions baked into the original
build: delivery is now a **single zip** (not files + `_MANIFEST.csv`), and
`TranAmt` is **signed**.

## Decision

### 1. Both feeds write the same fact tables, tagged by `source_system`

`fact_collections_daily`, `fact_ar_snapshot`, `fact_revenue_by_physician_mo`
carry `source_system ∈ {VENTRA_FL_STDSPEC_AGG, VENTRA_FL_PREAGG}` in their
natural key (migration 0013). A daily reconciliation job
(`entries.ventra_recon`) compares the two per (date, facility, payer). The
dashboard defaults to `VENTRA_FL_PREAGG` once Option 2 is stable; the
row-level path stays running as the reconciliation/audit source.

### 2. Standard Spec is PHI-stripped at the edge (allowlist)

HHA ingests **5 files** — Invoice, ChargeLines, Physician, Facility,
**TransactionsAlt** (the last is required to reconstruct collections). Every
file is stripped to an **allowlist** of known-safe columns *before* any row
reaches memory-aggregation, the DB, a log, or telemetry. A new PHI column
Ventra adds later is dropped by default. The denylist remains as a
defense-in-depth tripwire (V15). No PHI is ever persisted (ADR-001). Raw
inbound files auto-delete after 30 days.

### 3. Facility identity resolves at ingest

Ventra keys by `FacilityNo` (2284–2290); HHA stores `masters.sites.id`
(1–7). The mapping lives in `dims.facility_codes` (migration 0014), seeded
by facility-name correspondence. Unmapped FacilityNo → quarantine (V8);
non-FL site → incident (V12 / ADR-005).

### 4. Delivery: stdspec is a single zip, no manifest (2026-06-28 delta)

Per Ventra's 2026-06-22 reply, the **stdspec** feed delivers one
`HHA_Extact_YYYYMMDD.zip` per drop — there is no `_MANIFEST.csv`.

- Event Grid triggers on the `.zip` BlobCreated event; the `data.api`
  advanced filter (incl. `FlushWithClose`) ensures it fires only on a
  completed upload, never a partial zip.
- Integrity is the zip's own **per-member CRC32** (validated on unzip),
  replacing the manifest sha256/row_count checks. A corrupt member fails
  closed to quarantine (V1).
- Presence of all 5 files is required (V2). Dedup (V13) keys on the **zip's
  sha256** — one `ops.processed_files` row per drop.
- The drop date is parsed from the zip filename (`YYYYMMDD`).

The **preagg** feed keeps the `_MANIFEST.csv`-last contract (unchanged).

### 5. `TranAmt` is signed (2026-06-28 delta)

Ventra confirmed `TranAmt` carries its natural sign (a payment reversal is a
negative Payment). The aggregator accumulates the **signed** sum per bucket
so same-type reversals net (payment +100 then −50 = 50, not 150), then emits
the column **magnitude** for the non-negative fact columns. The accounting
formulas are unchanged:

- `net_revenue = payments_received − payer_refunds − patient_refunds`
- AR open balance = charges − payments − adjustments − write_offs + refunds

A (date, facility, payer) group whose payments **net negative** fails closed
as **V10** rather than abs-flipping (which would overstate collections) —
this also surfaces a sign-convention mismatch on the first real drop.

## Consequences

- **Positive:** no blind cutover; reconciliation catches drift; row-level
  feed is an independent audit reference; PHI never persists; the zip model
  is atomic + simpler (one trigger, CRC integrity) than manifest-last.
- **Negative:** two pipelines + a reconciliation job to operate; ~$50/mo
  extra storage/queue cost on top of the SFTP fee; the exact per-`TranType`
  sign convention and the `InsuranceClass` value vocabulary are still open
  with Ventra (tracked in [SFTP_HANDOFF.md](../../06-vendors/ventra/SFTP_HANDOFF.md)).
- **Sunset:** keep both feeds ≥ 90 days of clean reconciliation, then decide
  whether to retire the row-level path. Not blocking.

## Status notes

- ADR-006 (pre-aggregated only) is partially superseded — the pre-aggregated
  feed remains exactly as specified there; this ADR adds the parallel
  row-level feed + reconciliation and updates the stdspec delivery contract.
- ADR-005 (FL-only, TX manual) is unchanged and enforced at runtime by V12.
