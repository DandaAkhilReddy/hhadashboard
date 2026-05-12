# HIPAA compliance posture

> **For leadership, compliance reviewers, and auditors.** Plain English on what we do to protect patient health information. Engineering detail in [adr/001-hipaa-data-classification.md](adr/001-hipaa-data-classification.md). Last updated 2026-05-11.

## TL;DR

HHA Dashboard is **HIPAA-conscious by design**. We don't just check the boxes — we built the architecture so that patient health information **literally cannot** end up in our database, no matter what a developer types or what a vendor sends us.

The three pillars:

1. **No PHI in the database, ever.** Aggregates only. Raw patient data is read, summed, and discarded at the ingestion edge.
2. **Microsoft Azure BAA covers all infrastructure.** No data leaves the BAA-covered boundary.
3. **Every data change is audited** with the responsible user's identity attached, and audit log rows cannot be deleted.

## What HIPAA defines (quick refresher)

The HIPAA Privacy Rule covers **Protected Health Information (PHI)** — any data that links a patient identifier to a health condition or treatment. PHI includes 18 specific identifier categories: name, DOB, MRN, SSN, address, phone, email, dates of service per encounter, full-face photos, and so on.

HIPAA also defines a **Limited Data Set (LDS)** — PHI with most identifiers stripped but with some dates and ZIP-code data remaining. Even LDS requires a Data Use Agreement and is restricted.

HHA Dashboard handles **neither** PHI nor LDS in its persistent database. Everything in Postgres is operational aggregate data classified as "Tier A" (operational metrics with no link to any specific patient).

## Our 4-tier data classification

Every column in the database is tagged with a `data_class`:

| Tier | What it is | Where it lives |
|---|---|---|
| **A** | Operational aggregates (counts, sums, rates per site/payer/provider/month) | ✅ Postgres (the entire database) |
| **B** | Internal operational data (site names, NPIs, employment status, comp model) | ✅ Postgres |
| **C** | Limited Data Set (per-encounter timestamps, per-claim IDs, payer IDs) | ❌ **Never persisted** |
| **D** | Full PHI (patient names, DOB, SSN, MRN, addresses) | ❌ **Never persisted** |

This is enforced in two ways:

1. **A pre-commit hook** blocks any SQLAlchemy model that defines forbidden columns (`patient_*`, `mrn`, `claim_id`, etc.)
2. **A CI test** (`tests/test_schema_classification.py`) fails the build if any new column has `data_class=C` without sponsor approval

Engineering detail in [adr/001-hipaa-data-classification.md](adr/001-hipaa-data-classification.md).

## The HIPAA firewall

When Ventra sends claim-level data (Phase 2), this is how it stays out of our database:

```
Ventra sends claim-level CSV (contains PHI)
        ↓
SFTP upload to Azure Blob (raw drop, 30-day lifecycle, then auto-shred)
        ↓
Container Apps Job parses the CSV
        ↓
The job reads each row, strips forbidden columns, aggregates in memory
        ↓
ONLY the aggregates (date/site/payer totals) are written to Postgres
        ↓
Raw row is discarded. No PHI in the database.
```

If a developer accidentally tries to write a forbidden column to Postgres:

- CI test fails the build (column-classification check)
- Pre-commit hook blocks the commit (forbidden-column-name check)
- Even if both somehow miss, the Postgres trigger on the audit log captures every mutation — so a forensic auditor can trace what happened and when

This is **belt and suspenders**: three independent controls have to all fail for PHI to leak.

## BAA inventory

A Business Associate Agreement (BAA) is the legal contract that lets a vendor handle PHI on HHA's behalf. Every vendor in our data path has one — or PHI doesn't reach them.

| Vendor | Service | BAA status |
|---|---|---|
| **Microsoft** | Azure (App Service, Postgres, Storage, Key Vault, Container Jobs, Application Insights, Communication Services, Entra ID) | ✅ **Signed** — covered via HHA's M365 tenant |
| **Microsoft** | Microsoft 365 / Entra ID | ✅ **Signed** — same tenant BAA |
| **Ventra** | Revenue Cycle Management partner (Florida only) | 🟡 **Pending confirmation in writing** — gating Phase 2 cutover |
| **Athenahealth** | Underlying practice-management system | 🟡 **Via Ventra** — confirming the chain works downstream from Ventra's BAA, or HHA may need a separate Athena BAA |
| **Each hospital** | HHA is Business Associate of each hospital | 🟡 **Confirm with Legal** on a per-site basis |
| **GitHub** | Source code repository | ⚪ **N/A** — no PHI ever in code or issues |
| **No other vendors** | (No Datadog, Sentry, Slack, Resend, Cloudflare, etc.) | ⚪ **N/A** — none used |

The Ventra and Athena items are the **outstanding compliance work** before Phase 2 prod cutover.

## Audit trail

Every mutation to a sensitive table writes a row to the `audit.audit_log` table. The schema:

- `actor_upn` — the email address of the user who made the change
- `actor_role` — their role at the time (admin, exec, owner, etc.)
- `table_name` — which table was changed
- `operation` — INSERT, UPDATE, DELETE
- `row_id` — the primary key of the changed row
- `diff` — what changed (column-level)
- `occurred_at` — UTC timestamp

The trigger uses a PostgreSQL session-scoped GUC (`audit.upn`) so that even raw SQL changes and cron-job-driven inserts capture the actor identity. See [adr/003-audit-chain.md](adr/003-audit-chain.md) for the technical design.

**Properties:**

- Audit rows **cannot be deleted** (no DELETE permission on `audit.audit_log` for app users)
- Audit rows are **included in daily backups** to immutable Blob storage (WORM)
- Audit log retention: 7 years (HIPAA standard for healthcare records)
- Audit log review cadence: monthly spot-check by Akhil; quarterly comprehensive review

## Encryption

| At rest | In transit |
|---|---|
| Postgres: AES-256 (Azure-managed keys) | TLS 1.2+ enforced |
| Blob Storage: AES-256 | TLS 1.2+ enforced |
| Key Vault secrets: HSM-protected | TLS 1.2+ enforced |
| Backups: AES-256 (additional encryption) | TLS 1.2+ enforced |

Customer-managed keys (CMK) for Postgres data-at-rest are deferred until HIPAA auditor specifically requires it. Default Azure-managed keys are compliant with the BAA terms.

## Access controls

| Layer | Control |
|---|---|
| **Identity** | Entra ID with MFA enforced via Conditional Access |
| **Authorization** | Role-based — 7 Entra security groups (admin, exec, comp_viewer, 4 owner roles). See [adr/002-rbac-model.md](adr/002-rbac-model.md) |
| **API endpoint** | Every endpoint requires authentication; sensitive endpoints check role membership |
| **Database** | App service uses a least-privilege Postgres user (no DDL except via migrations); managed identity → Key Vault for connection string |
| **Audit** | Every access to sensitive data writes to audit log |

## Incident response

If a HIPAA-relevant incident happens (suspected breach, accidental disclosure, lost device, suspicious audit log entry):

1. **Detect** — alerts in Application Insights or user report
2. **Contain** — disable affected accounts via Entra; rotate credentials via Key Vault; isolate affected systems
3. **Eradicate** — patch root cause
4. **Recover** — restore from known-good backup if data integrity is in question
5. **Learn** — post-mortem within 48 hours; update runbook; notify HHA legal who handles BAA disclosure obligations

Full runbook in [SECURITY_INCIDENT_PLAYBOOK.md](SECURITY_INCIDENT_PLAYBOOK.md).

## What HIPAA requires us to NOT do (and we don't)

- ❌ Store patient identifiers in the database
- ❌ Log PHI to application logs (a `structlog` processor scrubs known identifiers)
- ❌ Use non-BAA-covered third-party services (no Sentry, Datadog, Slack, Resend, etc.)
- ❌ Allow public network access to Postgres (firewall denies all by default; AllowAllAzureServices is intentional and documented as a Phase 3 follow-up to tighten)
- ❌ Use weak password hashing (bcrypt cost=12 or argon2id)
- ❌ Allow shared admin accounts (every action is attributed to a specific Entra user)

## What we do that goes beyond minimum HIPAA

- ✅ **Aggregate-only architecture** — most HIPAA-compliant systems just secure their PHI; we don't have any.
- ✅ **CI-enforced classification** — column-level rules block bad code from merging.
- ✅ **Trigger-based audit** — captures all mutation paths, not just ORM writes.
- ✅ **Immutable backups** — WORM lock prevents backup tampering.
- ✅ **Quarterly restore drill** — verified RTO and RPO, not theoretical.

## What an auditor would see

If HHA's HIPAA compliance officer or an external auditor reviews this system, they get:

1. This document and the ADRs as the **policy** narrative
2. The CI test results and pre-commit hook output as **technical enforcement**
3. The Bicep templates as the **infrastructure-as-code** evidence
4. The audit log as the **runtime evidence**
5. The BAA inventory as the **contractual evidence**
6. The restore drill log as the **operational evidence**

All artifacts are reproducible. None depend on tribal knowledge.

## Review cadence

| Cadence | Who | What |
|---|---|---|
| **Continuous** | CI | Every PR runs `tests/test_schema_classification.py` |
| **Weekly** | Akhil | Review of any new audit log anomalies |
| **Monthly** | Akhil | BAA inventory check, secret rotation status |
| **Quarterly** | Akhil + HHA Legal | Restore drill, BAA renewal check, audit log comprehensive review |
| **Annually** | HHA Compliance Officer | Full HIPAA posture review, BAA roster, training |

## Open items

| Item | Owner | Target |
|---|---|---|
| Ventra BAA written confirmation | Ventra | Pre Phase 2 cutover |
| Athena BAA chain confirmation | Ventra → HHA Legal | Pre Phase 2 cutover |
| Re-enable Key Vault purge protection | Akhil | Phase 3 (next sprint) |
| Tighten Postgres firewall (drop AllowAllAzureServices) | Akhil | Phase 3 (when VNet integration is on) |

---

**Next read for leadership:** [EXECUTIVE_OVERVIEW.md](EXECUTIVE_OVERVIEW.md) (recap) or back to [INDEX.md](INDEX.md)
**Next read for engineering:** [adr/001-hipaa-data-classification.md](adr/001-hipaa-data-classification.md)
**Next read for on-call:** [SECURITY_INCIDENT_PLAYBOOK.md](SECURITY_INCIDENT_PLAYBOOK.md)
