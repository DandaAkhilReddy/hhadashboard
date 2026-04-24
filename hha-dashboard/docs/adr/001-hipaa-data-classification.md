# ADR-001: HIPAA Data Classification & Hosting Strategy

- **Status:** Accepted
- **Date:** 2026-04-23
- **Deciders:** Akhil Reddy (technical lead); CEO + CFO co-sponsors (pending charter sign-off)
- **Supersedes:** None

## Context

HHA Medicine operates as a Business Associate to each of the 11 hospitals where its doctors provide hospitalist care. Any claim-level data (claim_id, DOS, CPT, denial line items) received from Athenahealth via Ventra is **Protected Health Information (PHI)** under HIPAA — at minimum a Limited Data Set, even absent patient name.

Previous plan drafts (v3, v4) contained an internal contradiction: the written scope said "aggregates only, no PHI" but fact-table schemas included `claim_id`, `encounter_id`, and per-line DOS. That drift is exactly how HIPAA incidents happen in healthcare startups.

The stack selected for solo-build speed must be coherently BAA-covered end to end. Non-BAA vendors (Railway, Clerk free/pro, Resend free/pro, Sentry free/team, Cloudflare R2) were evaluated and rejected for any role that touches HHA data — even "manual HR entry only" data, because scope creep into PHI is a when-not-if question, and having a non-BAA vendor in the path at that moment triggers a breach.

This ADR establishes two invariants that govern every future decision:

1. **Every vendor in the data path has a signed BAA**
2. **Every database column is classified** — and nothing with `data_class: C` ever enters Postgres

## Decision

### Part 1 — Hosting

All HHA Dashboard infrastructure runs in a single Azure subscription (`hha-production`) under HHA's existing Microsoft 365 tenant. Microsoft's standard BAA (automatically covered by HHA's M365 agreement) covers every Azure service we use: App Service, Postgres Flexible Server, Blob, Key Vault, Container Apps, Monitor/App Insights, Communication Services, Entra ID.

No other cloud. No other SaaS vendor in the data path. The only external system allowed to touch HHA operations data is Ventra (RCM provider) — and only after written BAA confirmation.

### Part 2 — Data classification (the four tiers)

Every column in every SQLAlchemy model must declare a `data_class` tag via `info={"data_class": "A"|"B"|"C"|"D"}`. CI test `tests/test_schema_classification.py` enforces.

| Tier | Name | What it covers | Handling |
|---|---|---|---|
| **A** | **Operational aggregates** | Counts, sums, percentages at date/state/site/bucket grain with no patient linkage | Standard Postgres storage. Any role with valid authz can read. |
| **B** | **HR / Workforce / Directory** | Physician name, NPI, DEA, employment_type, comp rates, site_coverage, credential expiry, open positions, turnover | Standard Postgres. **Comp detail additionally requires `comp_viewer` flag.** HR confidentiality rules apply (Stark/AKS). |
| **C** | **PHI / Limited Data Set** | Claim ID, encounter ID, DOS per line, CPT per line, patient name, DOB, MRN, member ID, subscriber ID, guarantor, any 18 HIPAA identifiers | **NEVER PERSISTED.** Read in memory by ingestion jobs only, aggregated, discarded. Raw source files (if any) land in Blob with 30-day auto-shred lifecycle. |
| **D** | **Public / Reference** | Site address, contract PDF URL, dim_payer.name, dim_date | Open — no classification controls. |

### Part 3 — Full data classification matrix

| Column | Table | Tier | Notes |
|---|---|---|---|
| site.name, state, hospital_system, address | masters.sites | D | Public directory info |
| contract.start_date, end_date, annual_subsidy_usd | masters.contracts | A | Aggregate, no patient |
| physician.name, npi, dea, email | masters.physicians | B | NPI is public registry; name is directory |
| physician.status, pip_start_date | masters.physicians | B | HR status |
| comp_agreement.base_salary_usd, per_diem_rate_usd, rvu_rate_usd, fmv_benchmark_usd | masters.comp_agreements | B | Gated by `comp_viewer` |
| credential.type, hospital_id, issued_on, expires_on | masters.credentials | B | HR / regulatory |
| site_coverage.role, start_date, end_date | masters.site_coverage | B | Who covers where |
| daily_entries.census, open_shifts | entries.daily_entries | A | Site-day aggregate count |
| weekly_clinical.hp_pct, dc_pct, avg_los_days | entries.weekly_clinical | A | Week-site % / avg |
| weekly_hr_manual.turnover_90d_pct | entries.weekly_hr_manual | A | Aggregate % |
| monthly_finance_manual.collections_usd, ar_over_120_pct, ncr_pct | entries.monthly_finance_manual | A | State-month aggregate |
| subsidy_payments.expected_usd, received_usd | entries.subsidy_payments | A | Contract-month aggregate |
| fact_headcount_daily.employment_type, status, fte | facts.fact_headcount_daily | B | HR count per physician per day |
| fact_terminations.term_date, voluntary | facts.fact_terminations | B | HR event |
| fact_open_positions.count | facts.fact_open_positions | A | Aggregate |
| fact_rvu_paycheck.rvus, rvu_pay_usd | facts.fact_rvu_paycheck | B | Comp, gated |
| fact_scheduled_shifts.shift_type, status | facts.fact_scheduled_shifts | B | HR schedule |
| fact_collections_daily.amount_usd | facts.fact_collections_daily | A | State-date aggregate — no patient, no claim |
| fact_ar_snapshot.bucket, amount_usd | facts.fact_ar_snapshot | A | State-date-bucket aggregate |
| fact_revenue_by_physician_mo.amount_usd | facts.fact_revenue_by_physician_mo | A | Physician-month aggregate (no encounter link) |
| fact_physician_productivity_daily.encounter_count, pct_hp_24h, pct_dc_48h, avg_hours_to_sign | facts.fact_physician_productivity_daily | A | Physician-date aggregate (no encounter_id) |
| audit_log.diff (jsonb) | audit.audit_log | B | Records HR/comp changes; no PHI |
| alert_subscriptions.email | alerts.alert_subscriptions | B | User directory |
| **claim_id** | — | **C** | **FORBIDDEN — never create this column** |
| **encounter_id** | — | **C** | **FORBIDDEN** |
| **dos (per encounter)** | — | **C** | **FORBIDDEN** |
| **cpt_per_line** | — | **C** | **FORBIDDEN** |
| **patient_name, patient_dob, mrn, member_id, subscriber_*, guarantor_*** | — | **C** | **FORBIDDEN** |
| **835 denial line items** | — | **C** | **FORBIDDEN — Ventra's scope entirely** |

### Part 4 — The PHI firewall (ingestion-edge aggregation)

When Ventra data starts flowing in Phase 2, the ingestion job enforces the classification policy in code:

```python
# jobs/ventra_ingest/main.py — pseudocode
for raw_record in read_ventra_source(feed):
    # 1. VALIDATE shape against expected schema
    record = VentraRawRecord.model_validate(raw_record)

    # 2. STRIP forbidden fields (log strip events to audit_log)
    forbidden = set(record.keys()) & FORBIDDEN_FIELDS
    if forbidden:
        audit_strip(record.claim_id if 'claim_id' in record else None, forbidden)

    # 3. AGGREGATE in memory only
    rollups.collections_by_state_date[(record.dos[:10], record.state)] += record.amount_paid
    rollups.ar_by_state_bucket[...] += ...
    rollups.revenue_by_md_month[(record.dos[:7], record.physician_id)] += ...

# 4. WRITE aggregates only
await session.execute(insert(FactCollectionsDaily).values(...))
# The raw record is now out of memory and never touched Postgres

# 5. SHRED raw source file after 30 days (Blob lifecycle policy)
```

`claim_id`, `encounter_id`, `dos` — read, used for computation, **discarded**. Never serialized to disk in our infrastructure.

### Part 5 — Forbidden vendors (for this data path)

The following vendors are **not allowed** to handle HHA Dashboard data at any tier, because they do not offer BAAs at the tiers available to us:

- Railway (no BAA at any tier currently)
- Clerk (BAA is Enterprise-only)
- Resend (no BAA on free/pro)
- Sentry (BAA is Business tier+; use Application Insights instead)
- Cloudflare R2 (no BAA; use Azure Blob instead)
- Vercel (BAA is Enterprise-only)

If a future ADR wants to reintroduce any of these, it must (a) upgrade to BAA-tier, (b) have Legal approval of the executed BAA, and (c) pass a scope analysis proving the vendor only touches Tier D or no HHA data.

### Part 6 — Governance

- Every PR touching `api/app/models/` or `api/alembic/versions/` must pass `tests/test_schema_classification.py` (CI gate).
- Every PR must check the HIPAA classification checklist in the PR template.
- Quarterly: Akhil runs `scripts/restore-drill.sh` to verify backup integrity; documents pass/fail in `docs/RUNBOOK.md`.
- Quarterly: Akhil audits `audit_log` for unusual patterns (mass reads by a single UPN, reads of comp data by non-comp_viewer accounts).
- Annually: review this ADR and the BAA inventory.

## Consequences

### Positive

- Zero migration risk — we start on BAA-covered infra and stay there
- HIPAA compliance is a property of the schema and ingestion code, not a policy document
- Audit log + immutable backups provide legal-hold capability
- PR gate catches drift before it hits production

### Negative

- ~$800/mo Azure cost vs ~$50/mo Railway — acceptable for a healthcare services company of HHA's scale
- Entra ID setup is more code than Clerk (~30 min vs 5 min) — one-time cost
- Application Insights is noisier to configure than Sentry — one-time cost

### Neutral

- Per-physician revenue aggregates (Tier A) still require Ventra to provide pre-aggregated data OR to provide claim-level data that we aggregate at the edge. Either works under this ADR.

## Reversal criteria

This ADR is reversible only if:

1. HHA's risk posture changes (e.g., acquired by a system that mandates a different cloud)
2. Microsoft drops Azure from its BAA (extremely unlikely)
3. A replacement vendor offers a BAA-tier product with equivalent security posture AND Legal approves the executed BAA AND the scope analysis proves minimal exposure

Mere cost optimization is **not** a reversal criterion.

## Enforcement

- `tests/test_schema_classification.py` — CI fails if any column is missing `info.data_class` or has value `C`
- Pre-commit hook — blocks filenames/column names matching the forbidden list
- PR template — required HIPAA checklist
- `scripts/audit-schema.sh` — manual on-demand classification report

## References

- DASHBOARD_PLAN.md § HIPAA posture
- CLAUDE.md § HIPAA non-negotiables
- 45 CFR § 164.514(b)(2) — Safe Harbor de-identification standard
- HHS OCR Guidance — De-identification methods

_Last updated: 2026-04-23_
