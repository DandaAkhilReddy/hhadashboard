# HHA Medicine — Operations Dashboard · Architecture

> The canonical architecture entry point. Read this first.
>
> Companions: [DASHBOARD_PLAN.md](../../../DASHBOARD_PLAN.md) (what + why · scope), [docs/ONBOARDING.md](../03-engineering/ONBOARDING.md) (day-1 setup checklist), [docs/RUNBOOK.md](../04-operations/RUNBOOK.md) (operational procedures), [docs/adr/](../adr) (locked architectural decisions). This doc is the **how** — every component, every data flow, every wire.
>
> **For visual diagrams** of every component and data flow, see [DIAGRAMS.md](DIAGRAMS.md) (10 Mermaid diagrams). **For the full doc map:** [INDEX.md](../README.md).

---

## How to read this doc

If you have **5 minutes**, read §1 (At a glance) — invariants, stack, one-page diagram. That alone tells you the shape.

If you have **30 minutes**, also read §2 (The five planes) and skim §6 (Roles + RBAC). You'll know who can see what and where each piece lives.

If you're building or operating, read it cover-to-cover. Then bookmark [RUNBOOK.md](../04-operations/RUNBOOK.md) for incident playbooks and [ONBOARDING.md](../03-engineering/ONBOARDING.md) for environment setup.

### Table of contents

- §1 [At a glance](#1-at-a-glance) — invariants · stack · one-page diagram
- §2 [The five planes](#2-the-five-planes) — identity / app / data / integration / ops
- §3 [Component deep-dives](#3-component-deep-dives) — Entra · Next.js · FastAPI · Postgres · Container Apps Jobs · Key Vault · ACS Email · Blob · App Insights
- §4 [Data model](#4-data-model) — schemas · tables · the 4 boards + Doctor Scorecards data shape
- §5 [Data flows](#5-data-flows) — login · daily census · monthly finance · alerts · Ventra ingest · Paycom sync
- §6 [Auth + RBAC](#6-auth--rbac) — 7 Entra groups · `comp_viewer` additive flag · enforcement layer
- §7 [HIPAA posture](#7-hipaa-posture) — Tier A/B/C/D · forbidden columns · pre-aggregate rule · audit chain
- §8 [CI/CD](#8-cicd) — GitHub Actions · OIDC federated identity · keyless deploy
- §9 [Local dev](#9-local-dev) — docker-compose · Mailpit · Adminer
- §10 [Observability](#10-observability) — App Insights · Log Analytics · structured logs
- §11 [Disaster recovery](#11-disaster-recovery) — managed PITR · pg_backup WORM · restore drill RTO/RPO
- §12 [Cost model (estimated monthly)](#12-cost-model-estimated-monthly)
- §13 [Decisions intentionally deferred](#13-decisions-intentionally-deferred)
- §14 [Reference: file-to-component cross-walk](#14-reference-file-to-component-cross-walk)

For day-1 environment setup, jump to [docs/ONBOARDING.md](../03-engineering/ONBOARDING.md).

---

## 1. At a glance

### Core invariants (the stuff that must not drift)

1. **Azure-only, BAA-covered end to end.** Every vendor in the data path has a signed BAA (Microsoft's via HHA's M365 tenant). Zero non-BAA vendors for data, auth, email, or observability.
2. **No PHI in the database.** Ever. Ingestion jobs pre-aggregate at the edge; only Tier A rollups persist. Enforced by CI test, not by policy document.
3. **Single stack, solo build.** Next.js 15 + FastAPI + PostgreSQL + Entra ID. No dual surfaces. No Power BI. No migration gates.
4. **Florida automated, Texas manual.** Ventra's Athena tenant is the FL-only RCM source. TX finance stays manual entry via the in-app form.
5. **Denials out of scope.** Ventra owns the RCM workflow end-to-end; dashboard surfaces HHA's top-line only.

### Stack summary

| Layer | Service | Purpose |
|---|---|---|
| Identity | **Azure Entra ID** | SSO, MFA, security groups → roles |
| Frontend | **Next.js 15 App Router** on Azure App Service Linux | Dashboard UI, role-gated entry forms |
| Backend | **FastAPI (Python 3.12)** on Azure App Service Linux | REST API, auth enforcement, DB access |
| Database | **Azure PostgreSQL Flexible Server 16** | Masters, entries, facts, audit, alerts (6 schemas) |
| Batch jobs | **Azure Container Apps Jobs** | Nightly Paycom sync, Ventra ingest (FL), daily digest, credential scan, pg_backup |
| Email | **Azure Communication Services Email** | Daily digest + credential expiry alerts |
| Secrets | **Azure Key Vault** (private endpoint) | Paycom/Ventra creds, JWT signing config |
| Object storage | **Azure Blob Storage (LRS + immutability)** | Daily pg_dump WORM, Ventra raw drop zone with 30-day lifecycle |
| Observability | **Application Insights + Log Analytics** | Structured logs, traces, alerts |
| IaC | **Bicep** | Whole Azure environment declarative |
| CI/CD | **GitHub Actions + OIDC federated identity** | Keyless deploy |
| Local dev | **docker-compose** (Postgres + Mailpit + Adminer) | Prod-mirror in one command |

### One-page diagram

```
                             USER (exec / owner)
                                     │
                                     │ Microsoft account + MFA
                                     ▼
                          ┌──────────────────────────┐
                          │  Entra ID (BAA-covered)  │
                          │  security groups → roles │
                          └─────────────┬────────────┘
                                        │ ID + access tokens
                                        ▼
                       ┌─────────────────────────────────┐
                       │  Next.js 15 (App Service)       │
                       │  MSAL.js · middleware.ts        │
                       │  · role-routed pages            │
                       └──────────────┬──────────────────┘
                                      │ HTTPS + bearer token
                                      ▼
                       ┌─────────────────────────────────┐
                       │  FastAPI (App Service)          │
                       │  JWT verify · require_role      │
                       │  · require_comp_viewer          │
                       │  · SQLAlchemy 2 async           │
                       └────┬──────────────────────┬─────┘
                            │ Managed Identity     │ Managed Identity
                            ▼                      ▼
                ┌───────────────────┐  ┌─────────────────────┐
                │  Key Vault        │  │  Postgres Flex 16   │
                │  (private EP)     │  │  (private EP)       │
                │  Paycom/Ventra    │  │  schemas: masters,  │
                │  secrets          │  │  entries, facts,    │
                └───────────────────┘  │  audit, alerts,dims │
                            ▲          └──────────▲──────────┘
                            │                     │
      ┌─────────────────────┴──────────┐          │
      │  Container Apps Jobs (cron)    │──────────┤
      │  · paycom_sync (nightly)       │          │
      │  · ventra_ingest (FL, P2+)     │          │
      │  · alert_digest (7am daily)    │          │
      │  · cred_scan (daily)           │          │
      │  · pg_backup (daily → Blob)    │          │
      └───────────┬─────────────────┬──┘          │
                  │                 │             │
                  ▼                 ▼             │
     ┌──────────────────────┐  ┌───────────────────┴─────┐
     │  ACS Email           │  │  Blob Storage (LRS)     │
     │  exec@hha inbox      │  │  · backups (WORM 30d)   │
     └──────────────────────┘  │  · ventra-raw (30d TTL) │
                               └─────────────────────────┘

                All boxes above live inside the VNet.
                Internet egress only for outbound API calls
                (Paycom, Ventra) via NAT gateway.

                App Insights + Log Analytics receive telemetry
                from every component via connection string.
```

---

## 2. The five planes

The architecture separates cleanly into five planes. Each has its own failure mode and operational concern.

| Plane | What's in it | Why it matters |
|---|---|---|
| **Identity** | Entra ID tenant, app registrations, security groups | Single gate. Compromise here = everything compromised. Managed by Azure, BAA-covered. |
| **Application** | Next.js + FastAPI on App Service | Stateless. Can be redeployed instantly. |
| **Data** | PostgreSQL Flex + Blob Storage | Stateful. Backups and PITR matter. Changes need migrations. |
| **Integration** | Container Apps Jobs (sync / ingest / email) + outbound connectors | The PHI firewall lives here. Jobs shred raw data after aggregating. |
| **Operations** | Key Vault, App Insights, Log Analytics, Azure Monitor alerts, backups | Observability + secrets + DR. |

Separating by plane also maps to blast-radius control — a bug in the integration plane (e.g., a bad Paycom sync) doesn't take down the app plane.

---

## 3. Component deep-dives

### 3.1 Entra ID (identity plane)

**Purpose:** single source of truth for who can log in and what they can see. Replaces Clerk/Auth0/custom auth entirely.

**Setup (one-time):**

- Two app registrations per environment:
  - `hha-dashboard-web-{dev|prod}` — public client, MSAL.js in browser, delegated permissions
  - `hha-dashboard-api-{dev|prod}` — confidential client, exposes scope `api://{api-client-id}/access_as_user`
- Web app has delegated permission to call API scope
- Seven Entra **security groups** (one per role — see §6):
  - `HHA-Dashboard-Admin`
  - `HHA-Dashboard-Exec`
  - `HHA-Dashboard-CompViewer` (additive, layered on top of `Exec`)
  - `HHA-Dashboard-Owner-Ops` / `-Finance` / `-Clinical` / `-HR`
- Token config adds `groups` claim (emitted as group object IDs in the JWT)

**Token flow:** MSAL.js in the browser acquires an ID token + access token, sends the access token as `Authorization: Bearer <jwt>` to FastAPI. FastAPI verifies signature against Entra's JWKS metadata, extracts `upn` + `groups` + (optional) `roles`.

**Conditional access:** enforced at the tenant level (MFA required, managed device optional). No app-level override.

**BAA:** covered by HHA's default M365 agreement.

---

### 3.2 Next.js 15 web (application plane)

**Purpose:** the only UI surface. Exec dashboards, role-gated manual entry forms, admin pages.

**Hosting:** Azure App Service Linux, Node 20 runtime. Single web app per environment.

**Key files:**

| File | Role |
|---|---|
| [`web/middleware.ts`](../../web/middleware.ts) | MSAL session check + Entra group → role mapping. Redirects unauthenticated to `/sign-in`; 403s role-blocked routes. |
| [`web/lib/auth.ts`](../../web/lib/auth.ts) *(Session 2)* | MSAL.js config, token acquisition, silent refresh |
| [`web/lib/api-client.ts`](../../web/lib/api-client.ts) | Typed `fetch()` wrappers that attach bearer token |
| [`web/lib/api-types.ts`](../../web/lib/api-types.ts) | **Generated** by `openapi-typescript` from `/openapi.json`. Never edited by hand. |
| `web/app/(dashboard)/*` | Overview + Operations / Finance / Clinical / People boards + Doctor Scorecards |
| `web/app/(entry)/*` | Role-gated forms: daily-census (Crystal), monthly-finance (Sandy/Maribel), weekly-clinical (Aneja/Reddy), weekly-hr (Andrea), admin (sites/contracts/physicians/credentials) |

**Rendering model:** server components by default, fetching from FastAPI server-side. Client components only where hooks or interactivity needed (forms, charts).

**Styling:** Tailwind + shadcn/ui (installed components under `web/components/ui/`) + Tremor (chart primitives) + Recharts (lower-level charts).

**Type safety:** `tsc --strict`, `biome` for lint+format (single tool replaces eslint+prettier). `npm run gen-types` regenerates `api-types.ts` — this is the contract between web and api.

---

### 3.3 FastAPI backend (application plane)

**Purpose:** the only API. All data reads + writes flow through here. Enforces RBAC + audit.

**Hosting:** Azure App Service Linux, Python 3.12. Gunicorn + uvicorn workers behind App Service's built-in HTTP proxy.

**Structure:**

```
api/app/
├── main.py              # FastAPI app, middleware, lifespan, router includes
├── settings.py          # Pydantic Settings from env / Key Vault
├── deps.py              # DB session, get_current_user, require_role, require_comp_viewer
├── core/
│   ├── logging.py       # structlog JSON config (PII-scrubbed)
│   └── telemetry.py     # OpenTelemetry exporter → App Insights (Session 2+)
├── models/              # SQLAlchemy 2.0 async Mapped[] types
│   ├── base.py          # Base + TimestampMixin + DataClass enum
│   ├── masters.py       # Site, Contract, Physician, CompAgreement, Credential, SiteCoverage
│   ├── entries.py       # (Session 3) DailyEntry, MonthlyFinanceManual, WeeklyClinical, WeeklyHrManual, SubsidyPayment
│   ├── facts.py         # (Session 4) FactHeadcountDaily, FactRvuPaycheck, FactCollectionsDaily, FactArSnapshot, ...
│   ├── audit.py         # (Session 3) AuditLog
│   └── alerts.py        # (Session 3) AlertSubscription
├── schemas/             # Pydantic I/O — one module per resource
├── routers/             # /api/v1/{sites,operations,finance,clinical,people,scorecards,entries,admin,alerts}
└── services/
    ├── comp.py          # (Session 5) effective_comp across time-variant agreements; below-FMV
    ├── scorecard.py     # (Session 5) Overall Rank composite
    ├── audit.py         # (Session 3) SQLAlchemy event listener writing AuditLog on every mutation
    └── alerts.py        # (Session 3) threshold evaluation
```

**Every endpoint** has:

1. `Depends(get_current_user)` — verifies Entra JWT, returns `CurrentUser(upn, roles, comp_viewer)`
2. Optional `Depends(require_role(...))` — 403 if user's role not in allowlist
3. Optional `Depends(require_comp_viewer)` — 403 if not CEO/CFO/admin
4. `async with AsyncSession(...)` — every DB op is async
5. Returns a Pydantic model (typed, validated)

**Dev-stub auth:** when `ENV=dev`, `Authorization: Dev admin` header bypasses Entra verification. The dev stub never ships in prod builds — controlled by the env check in `deps.py`.

---

### 3.4 PostgreSQL Flexible Server 16 (data plane)

**Purpose:** system of record for everything the dashboard tracks. Private-endpoint only.

**Config:**

- SKU: `Standard_B2ms` dev / `Standard_D2ds_v5` prod
- Storage: 128 GB dev / 512 GB prod (auto-grow enabled)
- Backup: 7-day PITR (native), geo-redundant for prod
- High availability: single-AZ dev, zone-redundant prod
- Private endpoint into the VNet `app-subnet` — no public connectivity
- Admin connection via Azure AD only (no Postgres password auth for humans)
- Extensions: `btree_gist` (required for `comp_agreements` GIST exclusion)

**Schemas:** six Postgres schemas (not databases) — see §4.

**Connection pooling:** PgBouncer sidecar on App Service *(Session 7 optimization)*. For MVP, SQLAlchemy's built-in async pool with `pool_pre_ping=True` suffices.

**Migrations:** Alembic, colocated at `api/alembic/`. Every migration reversible. Schema changes run in dev → staging → prod with manual approval gate.

---

### 3.5 Azure Blob Storage (data plane / DR)

**Purpose:** immutable backups + Ventra raw drop zone.

**Accounts:** one storage account per environment: `sthhadashboard{dev|prod}`.

**Containers:**

| Container | Purpose | Lifecycle |
|---|---|---|
| `backups` | Daily `pg_dump` from the backup Container Apps Job | **Immutability policy (WORM)** — 30-day retention, time-based unlock only |
| `ventra-raw-drops` | Raw Ventra files (CSV/835) SFTP'd or uploaded. Ingestion job aggregates then **deletes** | 30-day auto-shred (lifecycle policy) |
| `exports` | User-initiated exports (PDF board deck) | 90-day retention |

**Access:** via Managed Identity from the backup / ingest jobs. Private endpoint into the `app-subnet`. No public access at any tier.

**Immutability mechanism:** Azure Storage's [time-based immutability policy](https://learn.microsoft.com/en-us/azure/storage/blobs/immutable-time-based-retention-policy-overview) — backup blobs cannot be modified or deleted for 30 days even by the account owner. Satisfies healthcare legal-hold requirements.

---

### 3.6 Azure Key Vault (operations)

**Purpose:** holds every secret the app and jobs need. No secret ever in code, env files, or App Service app settings.

**Secrets stored:**

- `paycom-client-id`, `paycom-client-secret`, `paycom-client-code`
- `ventra-sftp-username`, `ventra-sftp-private-key`, `ventra-api-client-id`, `ventra-api-client-secret` *(P2+)*
- `acs-connection-string` (ACS Email)
- `app-insights-connection-string`

**Access pattern:** App Service and Container Apps Jobs both have system-assigned Managed Identity. Each MI is granted `Key Vault Secrets User` role on the specific secrets it needs (least-privilege). At startup, the app pulls secrets via `azure.identity.DefaultAzureCredential` + `azure.keyvault.secrets.SecretClient`.

**No Entra JWT signing secret needed** — Entra signs its own tokens; FastAPI only verifies against the Entra JWKS endpoint.

**Private endpoint** into the VNet. No public network access.

---

### 3.7 Azure Container Apps Jobs (integration plane)

**Purpose:** run the scheduled batch jobs. Better than Azure Functions for these workloads because Container Apps Jobs start faster, pause when idle, and handle multi-minute runs without cold-start tax.

**Jobs:**

| Job | Schedule | Purpose |
|---|---|---|
| `paycom-sync` | nightly 02:00 ET | Pull employees (W-2 + 1099), terminations, RVU totals, schedules, open reqs; write to `facts.fact_headcount_daily`, `facts.fact_terminations`, `facts.fact_rvu_paycheck`, `facts.fact_open_positions`, `facts.fact_scheduled_shifts` |
| `ventra-ingest` *(P2+, FL only)* | nightly 04:00 ET | Read Ventra drop (CSV/API/835), edge-aggregate, write only Tier A rollups to `facts.fact_collections_daily`, `facts.fact_ar_snapshot`, `facts.fact_revenue_by_physician_mo`, `facts.fact_physician_productivity_daily`; delete raw file after success |
| `alert-digest` | daily 07:00 ET | Query current metrics, evaluate thresholds, render HTML digest, send to `alert_subscriptions.subscribe_digest = true` via ACS |
| `cred-scan` | daily 06:30 ET | Find credentials expiring in 30/60/90 days; email Crystal + affected MD |
| `pg-backup` | daily 03:00 ET | `pg_dump --format=custom --compress=9` → upload to Blob WORM container; record success in `ops.backup_log` |

All jobs:

- Built as Python Docker images (one image per job) stored in Azure Container Registry
- Run with system-assigned Managed Identity
- Pull secrets from Key Vault on start
- Connect to Postgres via private endpoint
- Log to App Insights (structured JSON)
- Exit code 0 = success; non-zero triggers Azure Monitor alert to ops email

**Why not Functions:** cold starts on Python (2–5 s) are noticeable; paycom-sync can run 60+ seconds and we'd hit timeouts. Container Apps Jobs bill per second active, scale-to-zero, perfect fit.

---

### 3.8 Azure Communication Services Email (integration plane)

**Purpose:** send email from the dashboard (alert digest + credential expiry). Replaces Resend/SendGrid/Mailgun with a BAA-covered Microsoft service.

**Setup:** one ACS resource + one Email Communication Services resource + one verified sender domain (`donotreply@hhamedicine.com`). Links to the existing HHA M365 domain via DNS TXT/MX records.

**Usage pattern** (from `alert-digest` / `cred-scan` jobs):

```python
from azure.communication.email import EmailClient

client = EmailClient(acs_endpoint, credential=DefaultAzureCredential())
await client.begin_send({
    "senderAddress": "donotreply@hhamedicine.com",
    "content": {"subject": "HHA daily digest · 2026-04-24", "html": digest_html},
    "recipients": {"to": [{"address": upn} for upn in subscribers]},
})
```

**No PHI in email bodies.** Digests use aggregate site-level labels only (e.g., "Westside census 198 vs avg 265") — never patient-identifying content.

---

### 3.9 Application Insights + Log Analytics (operations)

**Purpose:** all telemetry in one place. Replaces Sentry (no BAA at our tier) with a Microsoft service that's BAA-covered.

**What flows in:**

- **FastAPI:** OpenTelemetry auto-instrumentation for HTTP + SQLAlchemy + outbound HTTPX; custom `structlog` events tagged with `correlation_id`, `upn`, `request_id`
- **Next.js:** `@azure/monitor-opentelemetry` for server-side traces + errors; browser-side errors via the App Insights JavaScript SDK
- **Container Apps Jobs:** structured JSON logs + custom events (`paycom_sync.success`, `ventra_ingest.rows_aggregated`, etc.)
- **Postgres:** query performance metrics (slow query log → Log Analytics)

**Telemetry PII scrubbing:** custom processor in `core/logging.py` strips known PHI-adjacent field names from log events before they leave the app. Runs in every log path.

**Alerts configured:**

| Alert | Condition | Action |
|---|---|---|
| API error rate > 1% (5-min window) | App Insights metric | Email ops |
| API p99 latency > 2s (5-min window) | App Insights metric | Email ops |
| Any Container App Job fails | Non-zero exit code | Email ops |
| Backup job didn't run in 26 hours | Log Analytics query | Pager |
| Postgres connection pool exhaustion | Metric | Email ops |
| Schema classification test fails in CI | GitHub Actions status | Block PR |

---

### 3.10 VNet + Private Endpoints (networking)

**VNet:** `vnet-hha-dashboard-{dev|prod}` · address space `10.20.0.0/16`.

**Subnets:**

| Subnet | CIDR | Purpose | Delegations |
|---|---|---|---|
| `app-subnet` | `10.20.1.0/24` | App Service VNet integration | `Microsoft.Web/serverFarms` |
| `pe-subnet` | `10.20.2.0/24` | Private endpoints for Postgres, Key Vault, Storage | (none — PE type-specific) |
| `containerapps-subnet` | `10.20.4.0/23` | Container Apps environment (requires `/23`) | `Microsoft.App/environments` |
| `nat-subnet` | `10.20.6.0/24` | NAT Gateway for outbound egress (Paycom, Ventra) | (none) |

**Private endpoints** created for:

- Postgres Flex (no public endpoint)
- Key Vault (public access disabled)
- Storage Account (public access disabled)

**Egress:** outbound traffic to Paycom/Ventra goes through the NAT Gateway on `nat-subnet`, giving us a stable outbound IP to allowlist with vendors.

**Inbound:** only App Service's public HTTPS endpoint is reachable from the internet. Everything else is VNet-only.

---

## 4. Data model

### 4.1 Schemas

Six Postgres schemas inside one database. Separation is logical (namespacing + grants), not physical.

| Schema | Purpose | Data tier |
|---|---|---|
| `masters` | Relatively static reference entities: sites, contracts, physicians, comp agreements, credentials, coverage | Mostly B (HR/directory), some D (public), some A (contract financials) |
| `entries` | Manual user-entered numbers: daily census, weekly clinical, monthly finance (TX always + FL fallback), subsidy payments | A (aggregate) |
| `facts` | Integration-sourced aggregates: headcount, terminations, RVU paychecks, collections, AR, per-MD monthly revenue | Mostly A, some B |
| `audit` | Immutable audit log — one row per mutation on sensitive tables | B |
| `alerts` | `alert_subscriptions` — who gets what emails | B |
| `dims` | Generic dimensions: `dim_date` | D |

### 4.2 Key tables — FL/TX split and source_system

The most important schema detail per the 2026-04-23 scope decision: **FL and TX finance data never mix**. Enforced via a `source_system` column on every finance-related table:

```sql
monthly_finance_manual (
    id, month, state,
    collections_usd, ar_over_120_pct, ncr_pct,
    source_system text not null,   -- 'HHA_TX_MANUAL' or 'VENTRA_FL_FALLBACK'
    entered_by_upn text,
    created_at, updated_at
)

fact_collections_daily (
    date, state, amount_usd,
    source_system text not null,   -- 'VENTRA_FL_ATHENA' (only FL automated for now)
    ...
)
```

Finance board tiles read rows filtered by `source_system` and label them accordingly ("FL · Ventra" vs "TX · manual"). A bug that mixes the two = immediate incident.

### 4.3 `comp_agreements` — time-variant comp model

```sql
masters.comp_agreements (
    id, physician_id,
    effective_from, effective_to,       -- nullable; NULL = currently active
    employment_type,                    -- 'W2' | '1099'
    base_salary_usd,                    -- any/all of these may be null
    per_diem_rate_usd,
    rvu_rate_usd,
    rvu_threshold_annual,
    call_stipend_usd,
    fmv_benchmark_usd,                  -- MGMA IM hospitalist 50th %ile at time of agreement
    notes,
    created_by_upn, created_at, updated_at,

    CONSTRAINT ck_effective_dates
        CHECK (effective_to IS NULL OR effective_to >= effective_from),

    -- GIST exclusion: no overlapping date ranges per physician
    CONSTRAINT ex_comp_agreements_no_overlap EXCLUDE USING GIST (
        physician_id WITH =,
        daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[)') WITH &&
    )
)
```

The GIST exclusion constraint (powered by `btree_gist`) guarantees no two agreements for the same physician overlap in time. `services/comp.py` then computes `effective_comp(physician, as_of=today)` by looking up the single agreement valid at `today`.

### 4.4 The audit log

```sql
audit.audit_log (
    id bigserial primary key,
    table_schema text not null,
    table_name text not null,
    row_pk text not null,         -- stringified primary key
    action text not null,         -- 'INSERT' | 'UPDATE' | 'DELETE'
    diff jsonb not null,          -- {field: {old, new}}
    changed_by_upn text not null,
    changed_at timestamptz not null default now()
)
```

Written by a SQLAlchemy `after_flush` event listener in `services/audit.py` for every mutation on:

- `masters.physicians`
- `masters.comp_agreements`
- `masters.contracts`
- `entries.monthly_finance_manual`
- `entries.weekly_clinical`
- `entries.weekly_hr_manual`
- `entries.subsidy_payments`

Never logs data-tier C content (there is none — that's the point). Useful for "who changed Dr. X's below-FMV flag on what date" — the question regulators will eventually ask.

### 4.5 All columns are classified

Every SQLAlchemy column declares `info={"data_class": "A" | "B" | "C" | "D"}`. See [`docs/adr/001-hipaa-data-classification.md`](adr/001-hipaa-data-classification.md) for the full matrix. The CI test `tests/test_schema_classification.py` enforces this — **no Tier C column can ever land in the repo.**

---

## 5. Data flows

### 5.1 User sign-in

```
Browser                Entra ID            Next.js (App Svc)       FastAPI (App Svc)
   │                      │                      │                       │
   │ 1. GET /             │                      │                       │
   ├─────────────────────────────────────────────▶                       │
   │                      │                      │                       │
   │ 2. middleware.ts: no session → redirect to sign-in                  │
   ◀─────────────────────────────────────────────┤                       │
   │                      │                      │                       │
   │ 3. GET /sign-in → MSAL redirect to Entra    │                       │
   ├─────────────────────▶                       │                       │
   │                      │                      │                       │
   │ 4. Microsoft login + MFA                    │                       │
   ◀─────────────────────┤                       │                       │
   │                      │                      │                       │
   │ 5. callback w/ code → exchange for tokens   │                       │
   ├─────────────────────▶                       │                       │
   │                      │                      │                       │
   │ 6. ID + access tokens (access has groups[]) │                       │
   ◀─────────────────────┤                       │                       │
   │                      │                      │                       │
   │ 7. Store tokens, redirect to /              │                       │
   ◀─────────────────────────────────────────────┤                       │
   │                      │                      │                       │
   │ 8. GET / w/ session cookie                  │                       │
   ├─────────────────────────────────────────────▶                       │
   │                      │                      │                       │
   │ 9. server component calls API with bearer token                     │
   │                      │                      ├──────────────────────▶│
   │                      │                      │  Authorization:       │
   │                      │                      │  Bearer <access>      │
   │                      │                      │                       │ 10. verify JWT
   │                      │                      │                       │ against JWKS
   │                      │                      │                       │ → CurrentUser
   │                      │                      ◀──────────────────────┤
   │                      │                      │ data                  │
   │ 11. rendered page    │                      │                       │
   ◀─────────────────────────────────────────────┤                       │
```

### 5.2 Viewing a dashboard tile

```
Next.js server component           FastAPI                    Postgres
        │                             │                           │
        │ fetch('/api/v1/operations   │                           │
        │   /sites-today')            │                           │
        ├────────────────────────────▶│                           │
        │                             │ JWT verify → CurrentUser  │
        │                             │ require_role(*any)        │
        │                             │                           │
        │                             │ SELECT ... FROM           │
        │                             │ masters.sites, entries.   │
        │                             │ daily_entries             │
        │                             ├──────────────────────────▶│
        │                             │                           │
        │                             ◀──────────────────────────┤
        │                             │ compute variance etc      │
        │                             │ in-memory (Python)        │
        │ list[SitesTodayOut]         │                           │
        ◀────────────────────────────┤                           │
        │                             │                           │
        │ React tree → HTML           │                           │
```

### 5.3 User submits manual entry (daily census)

```
Browser           Next.js (client form)         FastAPI                    Postgres
   │                   │                           │                           │
   │ user types 198    │                           │                           │
   │ clicks "Save"     │                           │                           │
   ├──────────────────▶│                           │                           │
   │                   │                           │                           │
   │                   │ POST /api/v1/entries/     │                           │
   │                   │   daily-census            │                           │
   │                   │ w/ bearer token           │                           │
   │                   ├──────────────────────────▶│                           │
   │                   │                           │ require_role(             │
   │                   │                           │   'admin', 'owner_ops'    │
   │                   │                           │ )                         │
   │                   │                           │                           │
   │                   │                           │ INSERT INTO               │
   │                   │                           │   entries.daily_entries   │
   │                   │                           ├──────────────────────────▶│
   │                   │                           │                           │
   │                   │                           │ [SQLAlchemy after_flush   │
   │                   │                           │  event fires]             │
   │                   │                           │                           │
   │                   │                           │ INSERT INTO               │
   │                   │                           │   audit.audit_log         │
   │                   │                           ├──────────────────────────▶│
   │                   │                           │                           │
   │                   │                           │ COMMIT                    │
   │                   │                           ├──────────────────────────▶│
   │                   │                           │                           │
   │                   │ 201 Created w/ saved row │                           │
   │                   ◀──────────────────────────┤                           │
   │ "saved ✓"         │                           │                           │
   ◀──────────────────┤                           │                           │
```

### 5.4 Paycom nightly sync (Session 2+)

```
Container App Job: paycom-sync               Postgres
         │                                       │
         │ 1. Start (Managed Identity)           │
         │                                       │
         │ 2. Fetch secrets from Key Vault       │
         │    (paycom-client-id, secret, code)   │
         │                                       │
         │ 3. OAuth2 to Paycom                   │
         │    POST https://api.paycomonline.net  │
         │    /oauth2/token                      │
         │    → access_token                     │
         │                                       │
         │ 4. GET /api/v4/{client-code}/         │
         │    employees?limit=500                │
         │    → list[employee_raw]               │
         │                                       │
         │ 5. Transform + filter:                │
         │    - reject any field matching        │
         │      FORBIDDEN_FIELDS                 │
         │    - map Paycom enum to our enum      │
         │    - compute daily FTE from shifts    │
         │                                       │
         │ 6. Upsert into facts.fact_headcount_  │
         │    daily (date=today, physician_id,   │
         │    employment_type, status, fte)      │
         ├──────────────────────────────────────▶│
         │                                       │
         │ 7. Same for terminations, RVU         │
         │    paychecks, open requisitions       │
         ├──────────────────────────────────────▶│
         │                                       │
         │ 8. Log summary event to App Insights  │
         │    (rows_synced, duration_ms,         │
         │     error_count)                      │
         │                                       │
         │ 9. exit 0                             │
```

Jobs are idempotent — re-running the same date range overwrites same rows.

### 5.5 Ventra FL nightly ingest *(P2+, the PHI firewall)*

```
Container App Job: ventra-ingest            Blob Storage          Postgres
         │                                       │                    │
         │ 1. List new files in container        │                    │
         │    ventra-raw-drops/                  │                    │
         │    (put there by Ventra SFTP or       │                    │
         │     manual upload)                    │                    │
         ├──────────────────────────────────────▶│                    │
         │                                       │                    │
         │ 2. Download file (CSV or 835)         │                    │
         ◀──────────────────────────────────────┤                    │
         │                                       │                    │
         │ 3. THE FIREWALL:                      │                    │
         │    for each raw row:                  │                    │
         │      strip forbidden fields           │                    │
         │      audit the strip event            │                    │
         │    aggregate in memory:               │                    │
         │      by (date, 'FL')                  │                    │
         │        → fact_collections_daily       │                    │
         │      by (snapshot_date, 'FL', bucket) │                    │
         │        → fact_ar_snapshot             │                    │
         │      by (month, physician_id)         │                    │
         │        → fact_revenue_by_physician_mo │                    │
         │                                       │                    │
         │    (raw rows never touch Postgres)    │                    │
         │                                       │                    │
         │ 4. Bulk INSERT aggregates with        │                    │
         │    source_system='VENTRA_FL_ATHENA'   │                    │
         ├────────────────────────────────────────────────────────────▶│
         │                                       │                    │
         │ 5. Mark file as processed in the      │                    │
         │    manifest; original stays in Blob   │                    │
         │    where 30-day lifecycle policy      │                    │
         │    will auto-delete                   │                    │
         ├──────────────────────────────────────▶│                    │
         │                                       │                    │
         │ 6. exit 0                             │                    │
```

**Zero Tier-C data persisted.** The raw file's `claim_id`, `dos`, `cpt_per_line`, `patient_*` fields exist only in memory inside the job, for the duration of aggregation, and are then garbage-collected. The raw file itself on Blob auto-shreds at 30 days.

### 5.6 Daily email digest (7 AM ET)

```
Container App Job: alert-digest                 Postgres                    ACS Email
         │                                           │                          │
         │ 1. Query alert_subscriptions              │                          │
         │    WHERE subscribe_digest = true          │                          │
         ├──────────────────────────────────────────▶│                          │
         │                                           │                          │
         │ 2. For each metric the digest covers:     │                          │
         │    - today's FL + TX census               │                          │
         │    - yesterday's collections vs target    │                          │
         │    - AR > 120 days %                      │                          │
         │    - open shifts count                    │                          │
         │    - active alerts (MD vacancy, etc.)     │                          │
         │    compute + classify green/yellow/red    │                          │
         │                                           │                          │
         │ 3. Render Jinja template → HTML + plain   │                          │
         │                                           │                          │
         │ 4. Send via ACS Email, one recipient      │                          │
         │    at a time (BCC-style, no PHI in body)  │                          │
         ├──────────────────────────────────────────────────────────────────────▶│
         │                                           │                          │
         │ 5. Log send results to App Insights       │                          │
         │ 6. exit 0                                 │                          │
```

### 5.7 Credential expiry scan (daily)

```
cred-scan job → Postgres: SELECT physician.name, credential.type, credential.expires_on
                          FROM masters.credentials
                          JOIN masters.physicians ...
                          WHERE expires_on BETWEEN today AND today + interval '90 days'

                → Split into 3 tiers: <30 days (urgent), 30-60 (warning), 60-90 (info)
                → Render per-tier email → ACS Email → Crystal + affected MDs
                → Write summary event to App Insights
```

### 5.8 Daily Postgres backup (3 AM ET)

```
pg-backup job                           Postgres (read replica)     Blob (backups container)
       │                                          │                         │
       │ 1. pg_dump --format=custom               │                         │
       │    --compress=9 --no-owner               │                         │
       │    --file=/tmp/hha-{date}.dump           │                         │
       │    postgres://... (Managed Identity)    │                         │
       ├─────────────────────────────────────────▶│                         │
       │ ◀────────────────────────────────────────┤                         │
       │ (dump file in /tmp)                      │                         │
       │                                          │                         │
       │ 2. Compute SHA-256 of dump               │                         │
       │ 3. Upload to Blob with WORM tag:         │                         │
       │    hha-{date}.dump + .sha256 sidecar     │                         │
       │    (immutability kicks in immediately)   │                         │
       ├───────────────────────────────────────────────────────────────────▶│
       │                                          │                         │
       │ 4. Insert success row into              │                         │
       │    audit.backup_log                      │                         │
       ├─────────────────────────────────────────▶│                         │
       │                                          │                         │
       │ 5. exit 0                                │                         │
```

Quarterly, `scripts/restore-drill.sh` restores the latest backup into an ephemeral DB and runs `SELECT COUNT(*)` comparisons to verify integrity. Outcome logged in `docs/RUNBOOK.md`.

---

## 6. Auth + RBAC

### 6.1 Roles matrix

| Role | Who | Dashboard | Entry forms | Admin pages | Comp detail |
|---|---|---|---|---|---|
| `admin` | Reddy | all | all | ✅ | ✅ |
| `exec` | CEO, COO, CFO, CMO | all | ❌ | ❌ | only if `comp_viewer` |
| `comp_viewer` (**flag**) | CEO, CFO (additive on top of `exec`) | all | ❌ | ❌ | ✅ |
| `owner_ops` | Crystal Anderson | all | daily-census | ❌ | ❌ |
| `owner_finance` | Sandy Collins, Maribel Reyes | all | monthly-finance | ❌ | ❌ |
| `owner_clinical` | Dr. Aneja, Dr. V. Reddy | all | weekly-clinical | ❌ | ❌ |
| `owner_hr` | Andrea Simon | all | weekly-hr | ❌ | ❌ |

`comp_viewer` is a flag, not a standalone role. A user with `exec` + `comp_viewer` sees the comp detail on scorecards; an `exec`-only user sees everything else but not comp.

### 6.2 Entra group → role mapping

Groups claim in the JWT arrives as a list of group object IDs. `api/app/deps.py` maps them to roles:

```python
GROUP_TO_ROLE = {
    settings.entra_group_admin: "admin",
    settings.entra_group_exec: "exec",
    settings.entra_group_owner_ops: "owner_ops",
    settings.entra_group_owner_finance: "owner_finance",
    settings.entra_group_owner_clinical: "owner_clinical",
    settings.entra_group_owner_hr: "owner_hr",
}
COMP_VIEWER_GROUP = settings.entra_group_comp_viewer
```

One Entra group → one role. Membership in `CompViewer` sets `comp_viewer=True` on top of whatever role(s) the user already has.

### 6.3 Enforcement — three lines of defense

1. **Next.js middleware** (`web/middleware.ts`) — short-circuits at the edge: unauthenticated → `/sign-in`; wrong role → `403`. Prevents the page HTML from being rendered at all.
2. **FastAPI dependency** (`api/app/deps.py`) — verifies JWT signature, decodes claims, checks role on every endpoint. Returns 401/403 immediately.
3. **Integration test** (`api/tests/test_rbac.py`, Session 2) — asserts an `exec`-only user gets 403 on comp endpoints; an `owner_hr` user gets 403 on `/entry/daily-census`.

Three lines because a bug in one is caught by another. Defense in depth.

---

## 7. HIPAA posture

Full details in [`docs/adr/001-hipaa-data-classification.md`](adr/001-hipaa-data-classification.md). Summary:

### Four tiers

| Tier | Description | Allowed in DB |
|---|---|---|
| **A** | Operational aggregates | ✅ |
| **B** | HR / Workforce / Directory | ✅ (comp-gated by `comp_viewer`) |
| **C** | PHI / Limited Data Set | ❌ **NEVER** |
| **D** | Public / Reference | ✅ |

### The PHI firewall

Any external feed (Ventra/Athena) that *might* carry Tier-C data is read by a Container App Job, aggregated in memory, and only Tier-A rollups are written to Postgres. Raw source files land in a Blob container with 30-day auto-shred. **Claim IDs, encounter IDs, DOS per line — never written to disk in our infra.**

### Forbidden column names

The CI test `tests/test_schema_classification.py` rejects any column named:

```
claim_id, encounter_id, dos, dos_per_line, service_date,
cpt_per_line, hcpcs_per_line, icd_per_line,
patient_name, patient_dob, patient_id, patient_mrn, mrn,
member_id, subscriber_id, subscriber_name,
guarantor_id, guarantor_name, policy_number
```

Plus: every column must declare `info["data_class"]`, no column may be Tier C, all values must be in {A, B, C, D}. Four separate assertions. If any fails, PR doesn't merge.

---

## 8. CI/CD

### 8.1 Branch strategy

- `main` — protected, only merges from PRs, auto-deploys to dev
- Feature branches: `feat/<name>`, `fix/<name>`, `chore/<name>`, `docs/<name>`
- Release tags `v1.0.0`, `v1.1.0`, ... trigger manual-approval deploy to prod

### 8.2 GitHub Actions OIDC federated identity

No Azure credentials stored in GitHub. Instead:

1. An Entra app registration `github-oidc-hha-dashboard` has a **federated credential** trusting GitHub's OIDC issuer, scoped to `repo:DandaAkhilReddy/hha-dashboard:environment:{dev|prod}`
2. The app is granted `Contributor` on the dev resource group, `Contributor` + manual approval on prod
3. GitHub Actions workflow uses `azure/login@v2` with `client-id`, `tenant-id`, `subscription-id` — no secret
4. GitHub exchanges its OIDC token for an Azure token via the federated credential

### 8.3 Workflows

| Workflow | Trigger | Actions |
|---|---|---|
| `ci.yml` | every push, every PR | lint (ruff + biome + tsc), type-check (mypy + tsc), pytest (incl. HIPAA classification guard), vitest |
| `deploy-dev.yml` | merge to `main` | apply Bicep to dev, deploy api + web + jobs, run smoke tests |
| `deploy-prod.yml` | manual approval on tagged release | apply Bicep to prod, deploy, run smoke tests, rollback on failure |

### 8.4 CI gates that block merge

- Any failing test
- Mypy / tsc type error
- Ruff / biome lint error
- HIPAA classification test failure
- Forbidden column name detected
- Migration missing `downgrade()`

---

## 9. Local dev

Mirror of prod via `docker-compose`:

| Service | Port | Purpose |
|---|---|---|
| `postgres` | 5432 | PostgreSQL 16 with the 6 schemas + btree_gist pre-created via `init-schemas.sql` |
| `adminer` | 8080 | DB browser (dev only) |
| `mailpit` | 8025 (UI) / 1025 (SMTP) | Email catcher — alert-digest tests send here, not ACS |

**Dev auth** is a stub: `Authorization: Dev <role>` header bypasses Entra. Only works when `ENV=dev`. In Session 2 this stub co-exists with real MSAL (MSAL preferred when available, stub as fallback for local-only).

**Dev DB URL** in `.env`:

```
DATABASE_URL=postgresql+asyncpg://hha:hha@localhost:5432/hha_dashboard
DATABASE_URL_SYNC=postgresql+psycopg://hha:hha@localhost:5432/hha_dashboard
```

**OneDrive caveat:** never run `uv sync` or `npm install` inside the OneDrive folder — use `robocopy` to `C:\dev\hha-dashboard` first. See [QUICKSTART.md](../../QUICKSTART.md) step 0.

---

## 10. Observability

| Dimension | Tool | Source |
|---|---|---|
| Structured logs | App Insights (via OpenTelemetry) | `structlog` JSON in both FastAPI + jobs |
| HTTP traces | App Insights | OTel auto-instrumentation in FastAPI |
| DB query perf | Log Analytics | Postgres slow-query log |
| Browser errors | App Insights | `@microsoft/applicationinsights-web` |
| Uptime | Azure Monitor availability test | HTTPS GET /health every 5 min |
| Custom metrics | App Insights custom events | `paycom_sync.rows_synced`, `ventra_ingest.strip_events`, etc. |

Every request carries a `correlation_id` generated at the edge (Next.js middleware) and propagated via header to FastAPI, into DB queries, and into logs. You can trace one user click from HTML render back to the SQL query.

---

## 11. Disaster recovery

| Asset | RPO | RTO | Recovery path |
|---|---|---|---|
| Postgres | 5 min (native PITR) | 15 min | Azure portal: point-in-time restore |
| Postgres (catastrophic) | 24 hours (daily Blob backup) | 1 hour | `pg_restore` from WORM Blob |
| Blob (accidental deletion) | 0 (immutability policy + soft-delete 14 days) | 5 min | Storage portal undelete |
| App Service | 0 | 5 min | Redeploy from GitHub Actions |
| Key Vault | 0 (soft-delete + purge-protection 90 days) | 10 min | Recover soft-deleted secret |

Quarterly restore drill runs `scripts/restore-drill.sh` against the latest WORM backup into a staging DB and verifies row counts against the live DB. Results logged in `docs/RUNBOOK.md`.

---

## 12. Cost model (estimated monthly)

### Dev environment

| Service | SKU | Monthly |
|---|---|---|
| App Service Plan | B2 Linux | ~$55 |
| Postgres Flex | B2ms, 128 GB | ~$65 |
| Storage Account | LRS, ~20 GB | ~$2 |
| Key Vault | Standard | ~$1 |
| Container Apps env | Consumption (jobs scale to zero) | ~$5 |
| ACS Email | < 5K emails/mo | ~$0.20 |
| App Insights + LA | < 1 GB/mo | ~$3 |
| NAT Gateway | 1 gateway | ~$33 |
| Private endpoints (3) | | ~$25 |
| VNet, misc | | ~$10 |
| **Dev total** | | **~$200/mo** |

### Prod environment

| Service | SKU | Monthly |
|---|---|---|
| App Service Plan | P1v3 Linux (2 instances) | ~$150 |
| Postgres Flex | D2ds_v5, ZR, 512 GB | ~$250 |
| Storage Account | ZRS, ~200 GB + egress | ~$20 |
| Key Vault | Standard | ~$1 |
| Container Apps env | Consumption | ~$10 |
| ACS Email | < 10K emails/mo | ~$0.50 |
| App Insights + LA | < 5 GB/mo | ~$15 |
| NAT Gateway | 1 gateway | ~$33 |
| Private endpoints (3) | | ~$25 |
| VNet, misc | | ~$15 |
| **Prod total** | | **~$520/mo** |

**Combined (dev + prod running simultaneously): ~$720/mo.** For a healthcare services company of HHA's scale (single-site subsidies in the $100K–$250K/mo range), this is immaterial.

---

## 13. Decisions intentionally deferred

- **Entries / Facts / Audit / Alerts schemas** — Session 3+. Only `masters` models exist in Session 1.
- **Real Entra JWT verification** — Session 2. Dev-stub auth only in Session 1.
- **Audit log event listener** — Session 3, before any user-mutation endpoints land.
- **`services/comp.py` effective_comp calc** — Session 5 with Doctor Scorecards.
- **`services/scorecard.py` Overall Rank composite** — Session 5.
- **Bicep modules** — Session 7, after local stack works end-to-end.
- **GitHub Actions workflows** — Session 7.
- **Container Apps Job Docker images** — Session 8+ (Paycom), P2 (Ventra), Session 3 (backup).

Each deferred item has a session number; none are lost.

---

## 14. Reference: file-to-component cross-walk

| File | Component | Section |
|---|---|---|
| [`api/app/main.py`](../../api/app/main.py) | FastAPI | §3.3 |
| [`api/app/deps.py`](../../api/app/deps.py) | Auth + DB session | §3.3, §6 |
| [`api/app/settings.py`](../../api/app/settings.py) | Pydantic Settings (env + Key Vault) | §3.6 |
| [`api/app/models/base.py`](../../api/app/models/base.py) | `Base` + `DataClass` enum | §4.5 |
| [`api/app/models/masters.py`](../../api/app/models/masters.py) | Masters schema | §4.1 |
| [`api/alembic/versions/0001_initial.py`](../../api/alembic/versions/0001_initial.py) | Initial migration + GIST exclusion | §3.4, §4.3 |
| [`api/tests/test_schema_classification.py`](../../api/tests/test_schema_classification.py) | HIPAA CI guard | §7 |
| [`scripts/seed_sites.py`](../../scripts/seed_sites.py) | Seed 11 sites | §5 |
| [`scripts/init-schemas.sql`](../../scripts/init-schemas.sql) | Local Postgres schema bootstrap | §9 |
| [`web/middleware.ts`](../../web/middleware.ts) | Route guard | §6.3 |
| [`web/app/page.tsx`](../../web/app/page.tsx) | Overview page | §5.2 |
| [`web/next.config.ts`](../../web/next.config.ts) | `/api/*` proxy in dev | §9 |
| [`docker-compose.yml`](../../docker-compose.yml) | Local dev stack | §9 |
| [`docs/adr/001-hipaa-data-classification.md`](adr/001-hipaa-data-classification.md) | HIPAA ADR | §7 |
| [`CLAUDE.md`](../../CLAUDE.md) | Claude Code contract | (global) |
| [`QUICKSTART.md`](../../QUICKSTART.md) | Local run steps | §9 |

---

_Last updated 2026-04-23 · v1 · Session 1 baseline_
