# HHA Medicine — Operations Dashboard: Build Plan v5 (Azure-only, HIPAA-first)

> **One-liner:** Single Next.js + FastAPI + Postgres dashboard for HHA exec leadership, hosted entirely on Azure under Microsoft's BAA, built solo with Claude Code. Every vendor has a signed BAA. Zero migration gates. Denial analytics out of scope (Ventra owns RCM). PHI handling explicit and enforced in schema.

---

## Why v5 exists

v4 had a "Railway now, Azure at Phase 2" split. That split was the single biggest risk in the plan. v5 kills it.

### What changed from v4

| Change | Reason |
|---|---|
| ❌ Removed Railway entirely | No BAA at any tier. Not acceptable for healthcare operations data. |
| ❌ Removed Clerk | Free/Pro tier has no BAA. Clerk Enterprise exists but adds vendor + cost + complexity for no gain. |
| ❌ Removed Resend | No BAA. |
| ❌ Removed Sentry | No BAA on Team tier. |
| ❌ Removed Cloudflare R2 | No BAA. |
| ❌ Removed the "P2 migration gate" | Nothing to migrate from. Azure from day one. |
| ✅ Auth = Entra ID direct via MSAL | Native, BAA-covered, free, works with every exec's existing Microsoft account. |
| ✅ Email = Azure Communication Services Email | BAA-covered, same API shape as Resend. |
| ✅ Error tracking = Application Insights + Log Analytics | BAA-covered, deeper integration than Sentry. |
| ✅ Backups = Azure Blob with immutability (WORM) | BAA-covered, legal-hold capable. |
| ✅ Secrets = Azure Key Vault with Managed Identity | No static secrets anywhere, BAA-covered. |
| ✅ IaC = Bicep | Azure-native, Claude Code fluent. |
| ✅ CI/CD = GitHub Actions with OIDC federated identity | No stored Azure credentials in GitHub. |
| ✅ Data plane + app plane both Azure from day one | No migration ever. |

### Cost envelope (no constraint, documenting anyway)

| Environment | Monthly |
|---|---|
| Dev (burstable SKUs) | ~$250 |
| Prod (P1v3, GP Postgres, zone redundant later) | ~$550 |
| **Total** | **~$800/mo** at full P1v3 prod + dev parallel |

For a healthcare services company with 11 hospital contracts, this is a rounding error. A single site's monthly subsidy is ~$100K–250K.

---

## Context (carried from v4, unchanged)

HHA provides hospitalist / Internal Medicine coverage at 11 contracted hospitals (7 FL + 4 TX). Physicians are W-2 salaried, 1099 per-diem, or hybrid / RVU. Payroll runs through Paycom. Revenue = hospital subsidies + insurance collections. **Ventra owns full RCM** on top of the Athenahealth tenant they host. Ventra fee = 5% of collections.

Artifacts that informed scope:

- `hha_team_dashboard.html` — single-file HTML prototype, 4 boards, 11 sites, localStorage
- `https://hhamedicine-production.up.railway.app/` — React SPA with richer modules (mock data). **The denial/billing modules overlap with Ventra's scope — they're out.**

Active pain points: FL collections ~$44K/day below target, AR >120d at 25% FL / 28% TX, Westside MD vacancy, Woodmont PIP, 61 providers below FMV.

---

## Scope — IN and OUT (unchanged from v4)

### IN scope

**4 team-view boards (mirror HTML):**

- **Operations** — today's census, 3-mo avg, MTD, variance, open shifts, contract thru, subsidy, MD status per site; state + overall totals
- **Finance (HHA-level only)** — daily/MTD collections vs target by state, AR aging 5-bucket by state, days in A/R, net collection rate (top-line), Ventra fee (5%), monthly revenue trend
- **Clinical Quality** — H&P within 24h %, DC within 48h %, avg LOS by state, Woodmont LOS watch, credentials expiring 30/60/90d
- **People & Pipeline** — headcount W-2 vs 1099, total open positions, open by site, 90-day rolling turnover, below-FMV count, coverage fill rate

**Doctor Scorecards (exec-only, locked visibility):**

- Name + employment_type + comp_model + status
- RVU Generated (Paycom)
- Revenue per FTE (from Athena monthly per-MD, P2+)
- Encounters/day (Athena, P2+)
- Documentation Score (Athena timestamps, P2+)
- Chart Turnaround (P2+)
- Overall Rank composite (exec-only; doctors never see own rank or peers')

**Alerting:** in-app banners + daily 7am email digest + credential expiry alerts (30/60/90d).

**Compliance foundations:**

- Audit log on every mutation to sensitive tables (P0 deliverable)
- Time-variant `comp_agreements` for real hybrid comp tracking
- `alert_subscriptions` table (edit recipients without redeploying)
- Daily Postgres backup with immutability

### OUT of scope — Ventra's job or not HHA-relevant

- Any denial analytics — Ventra owns RCM end-to-end
- Claim-level browser, patient PHI, 835 denial lines, appeals workflow
- Charge lag, timely filing, clean claim rate, denial overturn, prior auth approval, coding accuracy
- Patient satisfaction / HCAHPS / portal adoption / payment plans / self-pay collections
- Cost-side P&L, per-site margin, investor view
- Hospital HL7/FHIR census feeds (Phase 4+)
- Real-time refresh

---

## HIPAA posture

### The rule

Every vendor in the data path has a BAA. Every environment that stores or processes HHA operations data is BAA-covered. Every column is classified. Nothing with `data_class: C` (Limited Data Set, e.g. claim_id, encounter_id, per-patient DOS) ever enters the database — ingestion jobs pre-aggregate at the edge.

See `/docs/adr/001-hipaa-data-classification.md` (already drafted) for full classification matrix.

### BAA inventory

| Vendor | Service | BAA? |
|---|---|---|
| Microsoft | Azure (App Service, Postgres, Blob, Key Vault, Container Apps Jobs, Monitor, Communication Services, Entra ID) | ✅ Default via HHA's M365 tenant |
| Microsoft | Microsoft 365 / Entra ID | ✅ Default |
| Ventra | RCM provider | ⏳ Confirm in writing — gating for P2 |
| Athenahealth | underlying PM (via Ventra tenant) | ⏳ Confirm via Ventra |
| Each hospital | HHA is Business Associate of each | ⏳ Confirm status with Legal |
| GitHub | Source control — no PHI ever in code or issues | n/a |

### Phase 2 caveat

When Ventra data starts flowing, **the ingestion job is the PHI gatekeeper**. It reads Ventra's feed, aggregates in memory at the edge, writes only Tier A rollups to the database. Claim-level records are never persisted. Raw files Ventra drops via SFTP land in an Azure Blob container with 30-day retention and are shredded afterward.

---

## The stack — final

| Layer | Choice | Why |
|---|---|---|
| **Frontend** | Next.js 15 App Router + Tailwind + shadcn/ui + Tremor + Recharts | Modern, Claude Code native, matches intended UX pattern |
| **Backend** | FastAPI (Python 3.12) | Your stack; Pydantic; async; OpenAPI; Claude Code fluent |
| **Database** | Azure Database for PostgreSQL Flexible Server 16 | Managed, BAA-covered, private endpoint, point-in-time restore |
| **ORM** | SQLAlchemy 2.0 async + Alembic | Typed models; co-located under `/api/alembic/` |
| **Auth** | Entra ID direct via MSAL (browser + server) | BAA-native, free, exec users already have Microsoft accounts |
| **Frontend host** | Azure App Service Linux (Node 20) | Same plan as API, simpler ops |
| **Backend host** | Azure App Service Linux (Python 3.12) | Same plan as web |
| **Scheduled jobs** | Azure Container Apps Jobs (cron) | BAA-covered, pauses when idle, better than Functions for batch |
| **Email** | Azure Communication Services Email | BAA-covered, straight-forward API |
| **Error tracking / logs** | Application Insights + Log Analytics | BAA-covered; deeper than Sentry |
| **Secrets** | Azure Key Vault + Managed Identity | No static secrets anywhere |
| **Object storage / backups** | Azure Blob Storage (LRS with soft-delete + immutability policy) | BAA-covered, WORM-capable |
| **TS types** | `openapi-typescript` generated from FastAPI `/openapi.json` | No drift |
| **Source control** | GitHub (DandaAkhilReddy/hha-dashboard) | No PHI in repo ever |
| **IaC** | Bicep | Azure-native |
| **CI/CD** | GitHub Actions with OIDC federated identity to Azure | Keyless, no static creds |
| **Local dev** | docker-compose (Postgres + Mailpit + Adminer) | Mirror of prod schema |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     AZURE SUBSCRIPTION: hha-production                    │
│                     (covered by Microsoft BAA via HHA M365 tenant)        │
│                                                                           │
│  ┌───────────────────────────┐        ┌────────────────────────────────┐  │
│  │  Users (execs + owners)    │───▶│  Entra ID — HHA tenant          │  │
│  │  Microsoft accounts        │        │  (SSO, MFA, conditional access)│  │
│  └───────────────────────────┘        └────────────┬───────────────────┘  │
│                                                     │ MSAL tokens         │
│  ┌──────────────────────────────────────────────────▼───────────────┐    │
│  │            VNet: 10.20.0.0/16                                     │    │
│  │                                                                   │    │
│  │  ┌─────────────────────┐     ┌──────────────────────┐             │    │
│  │  │ App Service (web)   │◀───▶│ App Service (api)    │             │    │
│  │  │ Next.js 15          │     │ FastAPI              │             │    │
│  │  │ MSAL.js             │     │ MSAL server-side     │             │    │
│  │  │ Tremor + Recharts   │     │ SQLAlchemy 2 async   │             │    │
│  │  └─────────────────────┘     └──────────┬───────────┘             │    │
│  │     System-assigned MI         MI       │                         │    │
│  │            │                            ▼                         │    │
│  │            │          ┌─────────────────────────────────┐         │    │
│  │            │          │ Azure Postgres Flex 16          │         │    │
│  │            │          │ (private endpoint, no public)   │         │    │
│  │            │          │ schemas: masters, entries,      │         │    │
│  │            │          │          facts, audit, alerts   │         │    │
│  │            │          └─────────────────────────────────┘         │    │
│  │            │                                                      │    │
│  │            ▼                                                      │    │
│  │  ┌──────────────────────┐    ┌──────────────────────┐             │    │
│  │  │ Key Vault            │    │ Blob Storage         │             │    │
│  │  │ (private endpoint)   │    │ - backups (immutable)│             │    │
│  │  │ Ventra/Paycom creds  │    │ - Ventra raw drops   │             │    │
│  │  │ MSAL signing secrets │    │ - exports            │             │    │
│  │  └──────────────────────┘    └──────────────────────┘             │    │
│  │                                                                   │    │
│  │  ┌──────────────────────────────────────────────────────────┐     │    │
│  │  │ Container Apps Jobs (cron, MI-auth)                      │     │    │
│  │  │  • paycom_sync         (nightly, P1+)                    │     │    │
│  │  │  • ventra_ingest       (nightly, P2+, aggregate at edge) │     │    │
│  │  │  • alert_digest        (7am daily)                       │     │    │
│  │  │  • cred_scan           (daily)                           │     │    │
│  │  │  • pg_backup           (daily → Blob WORM)               │     │    │
│  │  └──────────────────────────────────────────────────────────┘     │    │
│  │                                                                   │    │
│  │  ┌──────────────────────────────────────────────────────────┐     │    │
│  │  │ App Insights + Log Analytics (telemetry, PII-scrubbed)   │     │    │
│  │  └──────────────────────────────────────────────────────────┘     │    │
│  │                                                                   │    │
│  │  ┌──────────────────────────────────────────────────────────┐     │    │
│  │  │ Communication Services — Email (BAA-covered)             │     │    │
│  │  └──────────────────────────────────────────────────────────┘     │    │
│  └───────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Monorepo layout

```
hha-dashboard/
├── CLAUDE.md                         # context for every Claude Code session
│                                     # (this plan + ADR + conventions)
├── README.md
├── docker-compose.yml                # local: postgres + mailpit + adminer
├── .env.example
├── .github/
│   └── workflows/
│       ├── deploy-dev.yml            # OIDC federated identity → Azure
│       ├── deploy-prod.yml           # manual approval gate
│       └── ci.yml                    # lint, typecheck, pytest, schema test
│
├── infra/                            # Bicep IaC — full Azure environment
│   ├── main.bicep
│   ├── modules/
│   │   ├── vnet.bicep
│   │   ├── postgres.bicep
│   │   ├── appservice.bicep
│   │   ├── keyvault.bicep
│   │   ├── storage.bicep
│   │   ├── containerjobs.bicep       # cron jobs
│   │   ├── acs-email.bicep
│   │   ├── monitor.bicep
│   │   └── rbac.bicep
│   ├── env/
│   │   ├── dev.bicepparam
│   │   └── prod.bicepparam
│   └── bootstrap.sh
│
├── api/                              # FastAPI
│   ├── pyproject.toml                # managed by uv
│   ├── app/
│   │   ├── main.py
│   │   ├── settings.py
│   │   ├── deps.py                   # MSAL JWT verify, DB session, require_role, require_comp_viewer
│   │   ├── models/
│   │   │   ├── masters.py
│   │   │   ├── entries.py
│   │   │   ├── facts.py
│   │   │   ├── audit.py
│   │   │   └── alerts.py
│   │   ├── schemas/                  # Pydantic v2
│   │   ├── routers/
│   │   │   ├── operations.py
│   │   │   ├── finance.py
│   │   │   ├── clinical.py
│   │   │   ├── people.py
│   │   │   ├── scorecards.py
│   │   │   ├── entries.py
│   │   │   ├── admin.py
│   │   │   └── alerts.py
│   │   ├── services/
│   │   │   ├── comp.py               # effective_comp, below_fmv
│   │   │   ├── scorecard.py          # Overall Rank composite
│   │   │   ├── audit.py              # SQLAlchemy event listener
│   │   │   └── alerts.py             # threshold evaluation
│   │   └── core/
│   │       ├── logging.py            # structlog, PII-scrubbed
│   │       └── telemetry.py          # OpenTelemetry → App Insights
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   └── tests/                        # pytest, schema classification test, audit test
│
├── web/                              # Next.js 15
│   ├── package.json                  # includes `gen-types` script
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── middleware.ts                 # MSAL session + role routing
│   ├── app/
│   │   ├── (auth)/sign-in/
│   │   ├── (dashboard)/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx              # Overview
│   │   │   ├── operations/
│   │   │   ├── finance/
│   │   │   ├── clinical/
│   │   │   ├── people/
│   │   │   ├── scorecards/
│   │   │   └── revenue-trends/
│   │   └── (entry)/
│   │       ├── daily-census/
│   │       ├── monthly-finance/
│   │       ├── weekly-clinical/
│   │       ├── weekly-hr/
│   │       └── admin/
│   ├── components/                   # shadcn/ui + Tremor wrappers
│   ├── lib/
│   │   ├── api-client.ts
│   │   ├── api-types.ts              # GENERATED — do not edit
│   │   ├── auth.ts                   # MSAL config
│   │   └── roles.ts                  # role helpers
│   └── __tests__/
│
├── jobs/                             # Container Apps Jobs (Python)
│   ├── paycom_sync/
│   │   ├── Dockerfile
│   │   └── main.py
│   ├── ventra_ingest/                # P2+, aggregate at edge
│   ├── alert_digest/
│   ├── cred_scan/
│   ├── pg_backup/                    # pg_dump → Blob with immutability
│   └── shared/                       # common utilities
│
├── scripts/
│   ├── setup-github-oidc.sh
│   ├── seed-sites.py
│   └── restore-drill.sh              # quarterly backup restore test
│
└── docs/
    ├── adr/
    │   ├── 001-hipaa-data-classification.md
    │   ├── 002-rbac-model.md
    │   ├── 003-audit-log.md
    │   └── 004-backup-dr.md
    ├── ARCHITECTURE.md
    ├── METRICS.md
    ├── RUNBOOK.md                    # incident response, secret rotation, restore
    └── ONBOARDING.md                 # for any future engineer
```

---

## Data model (Postgres schemas)

Unchanged from v4. Summary — see `/docs/adr/001` for full classification.

**`masters`** — `sites`, `contracts`, `physicians`, `comp_agreements` (time-variant with GIST exclusion on `daterange` to prevent overlaps), `credentials`, `site_coverage`

**`entries`** — `daily_entries`, `weekly_clinical`, `weekly_hr_manual`, `monthly_finance_manual`, `subsidy_payments`

**`facts`** — `fact_headcount_daily`, `fact_terminations`, `fact_open_positions`, `fact_rvu_paycheck`, `fact_scheduled_shifts` (P1 Paycom); `fact_collections_daily`, `fact_ar_snapshot`, `fact_revenue_by_physician_mo`, `fact_physician_productivity_daily` (P2 Athena, pre-aggregated)

**`audit`** — `audit_log (id, table_schema, table_name, row_pk, action, diff jsonb, changed_by, changed_at)` — written by SQLAlchemy event listener on every mutation to sensitive tables

**`alerts`** — `alert_subscriptions (id, user_upn, email, subscribe_digest, subscribe_cred_90, subscribe_cred_30, subscribe_collections_miss)`

**`dims`** — `dim_date`

**Every column carries `data_class` in SQLAlchemy `info={}`.** CI test asserts no column with `data_class: C` exists.

---

## Auth & RBAC

### Entra ID setup (one-time)

1. Register two Entra apps: `hha-dashboard-web-{env}` and `hha-dashboard-api-{env}`
2. Expose API scope: `api://{api-client-id}/access_as_user`
3. Web app gets delegated permission to call the API scope
4. Create Entra security groups — one per role
5. Add users to groups; role claim flows through the token

### Roles

| Role | Who | Access |
|---|---|---|
| `admin` | Reddy | full (admin pages, all entry, all dashboards) |
| `exec` | CEO, COO, CFO, CMO | all dashboards (no entry, no admin) |
| `comp_viewer` | CEO, CFO | **additive flag** — unlocks comp detail + Overall Rank + below-FMV reasons |
| `owner_ops` | Crystal | dashboards + `/entry/daily-census` |
| `owner_finance` | Sandy, Maribel | dashboards + `/entry/monthly-finance` |
| `owner_clinical` | Dr. Aneja, Dr. Reddy | dashboards + `/entry/weekly-clinical` |
| `owner_hr` | Andrea | dashboards + `/entry/weekly-hr` |

### Enforcement

- **Next.js middleware:** reads MSAL session → checks Entra group membership → routes or 403s
- **FastAPI `deps.py`:** `require_role(*roles)` decorator on every route; `require_comp_viewer` on comp endpoints
- **Integration test:** exec-without-comp_viewer gets 403 on `/api/v1/scorecards/{id}/comp`

---

## Data ingestion rules (the PHI firewall)

### Manual entry (P0+)

Execs and owners type aggregate numbers into forms. Schema rejects anything resembling PHI (no free-text clinical narratives; numeric + enum only where possible).

### Paycom (P1)

Workforce data. Not PHI. Ingests to `fact_headcount_daily`, `fact_terminations`, `fact_open_positions`, `fact_rvu_paycheck`. No patient link anywhere.

### Ventra (P2+, ingestion-edge aggregation)

Whatever shape Ventra gives us (CSV, API, 835 files), the ingestion job follows this strict pattern:

```
for each raw record from Ventra:
    validate against expected shape
    strip any forbidden field (patient_*, member_id, mrn, subscriber_*, guarantor_*)
    log strip events to audit
aggregate in memory:
    by (date, state) → fact_collections_daily
    by (snapshot_date, state, bucket) → fact_ar_snapshot
    by (month, physician_id) → fact_revenue_by_physician_mo
write ONLY aggregates to Postgres
shred raw file from Blob after 30 days (lifecycle policy)
```

`claim_id`, `encounter_id`, `dos`, `cpt_per_line` — **never persisted to Postgres**. Read, used for aggregation, discarded.

---

## Phased roadmap

### Phase 0 — Foundation (Week 1–2)

**Status as of 2026-04-26** (see [hha-dashboard/docs/SESSION_RECAP_2026-04-25.md](hha-dashboard/docs/SESSION_RECAP_2026-04-25.md) for the full PR list):

| Bucket | State |
|---|---|
| Code (FastAPI + Next.js scaffolds, models, alembic, audit, MSAL, scorecards) | **Done** — PRs #1–#12 merged |
| Bicep scaffold (postgres + app service + dev/prod params + CI workflow) | **Done** — PRs #13 + #14 merged |
| Bicep VNet + Key Vault modules (compile-only) | **Open** — PR #15 |
| Bicep remaining (blob, container jobs, monitor, ACS, RBAC) | **Pending** — Sessions 10–11 |
| App Service VNet integration + KV references in app_settings | **Pending** — Session 10 |
| Live Azure deployment | **Pending** — needs subscription + workstation IP + KV admin password |
| Entra app registrations + security groups | **Pending** — Reddy / tenant admin parallel track |
| GitHub Actions OIDC + deploy workflows | **Pending** — Session 10 |

**Azure resources (via Claude Code + Bicep):**

- [ ] Azure subscription `hha-production` under HHA tenant (you create this manually, one-time)
- [ ] Resource group `rg-hha-dashboard-dev`
- [x] **VNet with app + private-endpoint subnets** — `vnet.bicep` in PR #15
- [x] **Postgres Flex (B2ms burstable for dev)** — Bicep module merged in PR #13; VNet injection mode added in PR #15
- [x] **Key Vault with private endpoint** — `keyvault.bicep` in PR #15 (empty vault; secret seeding in Session 10 via bootstrap.sh)
- [ ] Blob Storage with immutability policy on `backups` container *(Session 10)*
- [x] **App Service Plan (B2 for dev, P1v3 for prod)** — PR #13 merged
- [x] **Two App Services (web + api)** — PR #13 merged (App Service VNet integration in Session 10)
- [ ] Application Insights + Log Analytics *(Session 11)*
- [ ] Communication Services with Email domain *(Session 11)*
- [ ] Container Apps environment for cron jobs *(Session 10)*

**Entra:**

- [ ] Two app registrations (web, api) *(parallel track per `docs/ENTRA_SETUP.md`)*
- [ ] Security groups for each role
- [ ] Add 2 test users (you + one other) to `admin` and `exec` groups

**Code (Claude Code):**

- [x] **FastAPI scaffold: `/health`, `/ready`, MSAL JWT dep, OpenAPI** — PR #8 merged
- [x] **Next.js scaffold: Tailwind, Tremor, shadcn/ui, MSAL.js, middleware** — PR #9 merged
- [x] **SQLAlchemy models for all schemas, every column `data_class`-tagged** — Session 1 merged
- [x] **Alembic initial migration + seed script (11 sites from HTML)** — Session 1 merged
- [x] **Audit log event listener wired + tested** — replaced by Postgres triggers in PR #7 merged
- [ ] Backup Container Apps Job: `pg_dump` → Blob with immutability, tested via restore drill *(Session 10)*
- [x] **CI pipeline: lint, typecheck, pytest, schema classification test** — PR #14 merged
- [x] **ADR-001 committed** — Session 1 merged

**Engineering gate (you alone):** deploy via `az deployment group create`; sign in via Microsoft; overview renders with 11 seeded sites; enter a Westside census → persists; audit log captures insert; manual backup job succeeds; restore drill from backup succeeds; row counts match.

### Phase 1 — Board parity + Paycom + backfill (Weeks 3–6)

**Code:**

- [ ] All 4 board pages pulling from FastAPI (Operations, Finance, Clinical, People)
- [ ] Entry pages (role-gated) for Crystal / Sandy / Aneja / Andrea
- [ ] Admin page (sites, contracts, physicians, comp_agreements, credentials)
- [ ] `services/comp.py` — `effective_comp` across time-variant agreements; below-FMV calc
- [ ] Alert evaluation + daily digest (ACS Email) + credential scan
- [ ] `alert_subscriptions` table + admin UI
- [ ] Doctor Scorecards page — Paycom-sourced tiles populated; Athena tiles "coming soon"

**Paycom (parallel track):**

- [ ] Submit API enablement request (assume 4–6 weeks)
- [ ] When available: `jobs/paycom_sync` — nightly pull to `fact_headcount_daily`, `fact_terminations`, `fact_open_positions`, `fact_rvu_paycheck`
- [ ] If delayed: ship P1 without automation; Andrea enters weekly HR manually

**Historical backfill:**

- [ ] Import 12 months of manual finance + clinical + HR from Excel via one-time script

**Exec gate:** Crystal enters today's census for all FL sites in under 2 minutes. Sandy enters last month's finance summary. Two execs independently sign in the next morning and agree numbers match reality. Two weeks of daily use without a critical bug.

### Phase 2 — Ventra / Athena integration (Weeks 7–14, gated on Ventra)

**Blocking item:** Ventra BAA confirmed + data access path agreed.

**Ventra path decision tree:**

| Ventra answer | Work |
|---|---|
| Pre-aggregated monthly CSV via SFTP | `jobs/ventra_ingest` parses CSV, writes to `fact_collections_daily` + `fact_ar_snapshot`. No edge-aggregation needed (already aggregate). |
| Daily CSV with claim-level rows | Edge-aggregate in Python before insert. Strip claim_id. Raw files land in Blob, shredded after 30d. |
| API with claim-level data | Same edge-aggregation, but streamed via API pagination. |
| Raw 835/837 EDI | Add `pyx12` parser, same edge rule. |

**Code:**

- [ ] `jobs/ventra_ingest` (one of the above shapes)
- [ ] Retire manual monthly finance entry (keep as emergency fallback)
- [ ] Doctor Scorecards: fill Revenue/FTE, Encounters/day, Documentation Score, Chart Turnaround, Overall Rank composite
- [ ] Revenue Trends page

**Exec gate:** For chosen month, Finance board FL/TX collections match Ventra's report within $1K. AR aging snapshot reconciles month-end.

### Phase 3 — Polish (Weeks 15–16)

- [ ] Mobile responsive pass (execs use iPhone)
- [ ] In-app alert banners + threshold color tiles
- [ ] App Insights dashboards + alert rules
- [ ] RUNBOOK.md: incident response, secret rotation, restore drill, on-call
- [ ] PR template with HIPAA classification section
- [ ] Quarterly compliance checklist (review BAA status, rotate KV secrets, restore drill, audit log sample)

### Phase 4 — Future / optional

- Hospital census feeds (HL7/FHIR) per-hospital
- Credentialing SaaS integration (Modio / MD-Staff)
- Cost-side P&L with GL integration
- Commenting / annotations on tiles
- PDF export for monthly board deck

---

## Claude Code workflow

### CLAUDE.md (repo root)

The repo includes `CLAUDE.md` at root with:

- This build plan (v5)
- ADR-001 (HIPAA classification)
- Coding conventions (async SQLAlchemy, Pydantic v2, shadcn/Tremor, MSAL)
- Commit message format + PR template
- Forbidden operations ("never add claim_id to any table")

Every Claude Code session reads this automatically. Keep it updated.

### MCP servers to configure

```bash
claude mcp add azure    -- npx -y @azure/mcp@latest server
claude mcp add github   -- npx -y @modelcontextprotocol/server-github
claude mcp add postgres -- npx -y @modelcontextprotocol/server-postgres "$DATABASE_URL"
# Microsoft 365 MCP (you already have this connector)
```

### Daily loop

1. Pick a ticket from the phase backlog
2. `claude` in repo root → paste ticket
3. Claude Code reads CLAUDE.md, plans, executes, runs tests
4. You review the diff, push a branch
5. PR → CI runs → merge → GitHub Actions deploys to dev
6. Smoke test in dev → manual-approval gate deploys to prod

### Ticket template

```
Read CLAUDE.md. Then:

<what you want>

Constraints:
- No new dependencies without justifying in ADR
- No column with data_class: C added to schema
- All new sensitive-table mutations must be covered by audit tests
- Tests pass; mypy clean; ruff clean
- Commit as: "<conventional commit>"
```

---

## What only you can do (not Claude Code)

| Task | Why |
|---|---|
| Create Azure subscription + HHA tenant association | Tenant admin action |
| Add execs to Entra security groups | Directory admin |
| Sign MSA / BAA with Ventra | Legal/business |
| Request Paycom API access | Paycom's paperwork |
| Crystal / Sandy / MD interviews (scheduling depth, workflow, data sources) | Human interviews |
| Final number validation with CFO | Requires business knowledge |
| Privacy/Security Officer assignment at HHA | Organizational decision |
| CEO/CFO sign-off on ADR-001 | Governance |

Do these in parallel with Claude Code building. Don't serialize.

---

## Week 0 kick-off — what to do before any code

### Monday

1. **Project charter email to CEO/CFO/CMO/COO.** Names you the technical lead, ratifies the 4-board scope, sets expectations on phases.
2. **Pull HHA's Microsoft BAA** from M365 Admin → Service Trust → verify coverage.
3. **Assign Privacy + Security Officers** at HHA. If it's you, get it in writing.

### Tuesday

4. **Create Azure subscription** `hha-production` under HHA's M365 tenant.
5. **Create Entra security groups:** `HHA-Dashboard-Admin`, `HHA-Dashboard-Exec`, `HHA-Dashboard-CompViewer`, `HHA-Dashboard-Owner-Ops`, `-Finance`, `-Clinical`, `-HR`.
6. **Create GitHub repo** `DandaAkhilReddy/hha-dashboard` (private).

### Wednesday

7. **Commit CLAUDE.md + ADR-001 + this v5 plan to the repo.** Before any code. These are the contract.
8. **Claude Code Ticket #1:** "Read CLAUDE.md. Scaffold the monorepo structure from the plan. Add `.gitignore`, `README.md`, `.env.example`, `docker-compose.yml`, empty directories per the tree. No application code yet — just the spine."

### Thursday–Friday

9. **Claude Code Ticket #2:** Deploy the Bicep to Azure dev. Run `what-if`, review, apply. Save outputs.
10. **Claude Code Ticket #3:** Wire GitHub Actions OIDC federated identity. Test a no-op deploy.

End of Week 0: empty app running on Azure at `app-hha-web-dev.azurewebsites.net`, authenticated with your Microsoft account, nothing but a hello-world page. Every piece of the compliance foundation in place.

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Ventra BAA delayed | Medium | P0–P1 ship with manual entry; no Ventra dep until P2 |
| Paycom API provisioning slow (4–6wk) | High | P1 ships with manual HR entry; automation is a delta |
| HIPAA drift ("just add claim_id for debugging") | Medium | ADR-001 + CI schema test + PR template |
| Comp data leak via scorecards | Medium | `comp_viewer` flag enforced at middleware + router; integration test |
| Overall Rank screenshot leaks to a doctor | Medium | Exec-only; no doctor logins; watermark exports |
| Solo bus factor | High | CLAUDE.md + RUNBOOK.md + ARCHITECTURE.md current at all times |
| Scope creep (denials, P&L, investor view) | High | ADR + OUT list; every new request = new phase with sign-off |

---

## Business sponsorship

**Co-sponsors: CEO + CFO.** Dual sign-off. Reddy remains technical lead.

Rationale for dual:

- CEO ratifies this as a company-wide strategic initiative, not a finance-only tool
- CFO owns the pain (Finance board is the most politically loaded — collections miss, Ventra fee, subsidy coverage, below-FMV)
- Pairs authority with domain ownership
- Protects against either sponsor leaving mid-build

Operating agreement:

- Phase gates need **both** co-sponsors' sign-off before advancing
- Scope changes (anything in the OUT list moving to IN) need both
- Day-to-day technical decisions stay with Reddy
- Monthly 30-min status touchpoint with both co-sponsors in Phase 1+

The Monday charter email is addressed to both; names the technical lead (Reddy); lists the 4-board scope; lists the OUT list explicitly; sets the phase-gate expectation; attaches ADR-001.

---

## One-liner (final)

Azure-only, BAA-covered end-to-end, single Next.js + FastAPI + Postgres stack, built solo with Claude Code, zero migration risk, explicit PHI firewall via ingestion-edge aggregation, denials out of scope because Ventra owns RCM.

---

## Scope update — 2026-04-23: Florida-first, Texas manual

Decided by Akhil: **focus automation on Florida first; Texas stays manual entry only** for the current plan.

- **Ventra handles HHA's Florida book only.** The BI / data conversation kicked off by Gilda Romero (2026-04-23) is scoped to FL. Athena integration in Phase 2 is FL-only.
- **Texas is manual entry for now.** Sandy / Maribel enter TX monthly finance numbers via the in-app form (same pattern as the pre-automation FL fallback). No TX RCM vendor integration in this plan.
- **Finance board** displays FL and TX **side-by-side** on one board with **labeled source** per tile ("Ventra FL" vs "TX manual"). Schema adds `source_system` column to `monthly_finance_manual` and `fact_collections_daily` so the two books never mix.
- **Operations / Clinical / People / Scorecards** boards continue to cover all 11 sites (FL + TX) — Paycom serves both states equally, so nothing changes for those boards.
- **Reversing this** requires a new ADR: HHA adopting a TX RCM partner would trigger a parallel BAA + data-access negotiation and a new phase.

What this means for the active conversations:

- **Ventra reply (this week):** scoped to Florida book. See [VENTRA_REPLY_DRAFT.md](VENTRA_REPLY_DRAFT.md).
- **No TX RCM outreach needed.**
- **Phase 2 Ventra decision tree** still applies but FL-only.

---

_Last updated 2026-04-23 — v5 + FL-first scope decision_
