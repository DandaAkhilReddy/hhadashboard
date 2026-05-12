# Architecture diagrams

> **Visual reference for the HHA Dashboard architecture.** Pair with the narrative deep-dive in [ARCHITECTURE.md](ARCHITECTURE.md). All diagrams are Mermaid (text-based, version-controlled, rendered natively on GitHub). To render in SharePoint/PDF, run [scripts/export-to-pdf.sh](../scripts/export-to-pdf.sh).
>
> Last updated 2026-05-11.

## Diagram index

1. [System context (C4 Level 1)](#1-system-context-c4-level-1) — who talks to what
2. [Container diagram (C4 Level 2)](#2-container-diagram-c4-level-2) — what's inside
3. [Deployment topology](#3-deployment-topology) — Azure resources
4. [Entra ID auth flow](#4-entra-id-auth-flow) — exec sign-in
5. [Census portal auth flow](#5-census-portal-auth-flow) — kiosk login
6. [Ventra ingestion data flow](#6-ventra-ingestion-data-flow) — Phase 2
7. [HIPAA firewall flow](#7-hipaa-firewall-flow) — what gets stripped where
8. [Audit chain](#8-audit-chain) — who-did-what-when propagation
9. [Schema ERD](#9-schema-erd) — Postgres relationships
10. [Phase progression timeline](#10-phase-progression-timeline)

---

## 1. System context (C4 Level 1)

The top-level view: who uses HHA Dashboard, and what external systems it depends on.

```mermaid
flowchart TB
    classDef person fill:#08427b,stroke:#073b6f,color:#fff
    classDef system fill:#1168bd,stroke:#0e5ba6,color:#fff
    classDef external fill:#999,stroke:#8a8a8a,color:#fff

    execs["HHA Executives<br/>(CEO, CFO, CMO, COO)<br/>~4 users"]:::person
    owners["Department Owners<br/>(Crystal, Sandy, Maribel,<br/>Aneja, Reddy, Andrea)<br/>~6 users"]:::person
    sites["Site Leaders<br/>(daily census entry)<br/>~11 users (one per site)"]:::person

    dashboard["HHA Dashboard<br/>Web app + API<br/>(Phase 1 live, Phase 2 in design)"]:::system

    entra["Microsoft Entra ID<br/>HHA M365 tenant"]:::external
    ventra["Ventra Health<br/>RCM partner — Florida only"]:::external
    athena["Athenahealth<br/>Practice management<br/>(accessed via Ventra)"]:::external
    paycom["Paycom<br/>HR / payroll<br/>(Phase 4 optional)"]:::external

    execs -->|"view all dashboards"| dashboard
    owners -->|"monthly entry forms"| dashboard
    sites -->|"daily census via /census"| dashboard

    dashboard -->|"sign-in (MSAL)"| entra
    dashboard -->|"daily SFTP pull<br/>(Phase 2)"| ventra
    ventra -.->|"sources patient data"| athena
    dashboard -.->|"optional API pull<br/>(Phase 4)"| paycom
```

**Key facts in this diagram:**

- **20 users max.** Not a public system.
- **Entra ID** is the only auth provider — there's no separate password store.
- **Ventra is Florida-only.** Texas operations are manual entry inside the dashboard (per ADR-005).
- **Paycom is dashed** because it's a future Phase 4 integration, not built.

---

## 2. Container diagram (C4 Level 2)

What's inside the "HHA Dashboard" box from the system context.

```mermaid
flowchart TB
    classDef person fill:#08427b,stroke:#073b6f,color:#fff
    classDef container fill:#438dd5,stroke:#3c7fc0,color:#fff
    classDef db fill:#438dd5,stroke:#3c7fc0,color:#fff,stroke-dasharray: 5 5
    classDef external fill:#999,stroke:#8a8a8a,color:#fff

    user["User (browser)"]:::person

    subgraph Azure ["Azure (rg-hha-dashboard-prod, centralus)"]
        web["app-hha-web-prod<br/>Next.js 15 (App Router)<br/>Linux App Service B1<br/>Renders UI, MSAL.js sign-in"]:::container
        api["app-hha-api-prod<br/>FastAPI (Python 3.12)<br/>Linux App Service B1<br/>Endpoints, RBAC, business logic"]:::container

        pg["psql-hha-prod<br/>Postgres Flexible Server 16<br/>Burstable B1ms<br/>masters / entries / facts /<br/>audit / alerts / dims schemas"]:::db

        kv["kv-hha-prod2<br/>Key Vault<br/>secrets + connection strings"]:::container

        blob["sthhaprod<br/>Storage Account<br/>backups (WORM) + uploads +<br/>future Ventra raw drops"]:::container

        eg["Event Grid<br/>(Phase 2)<br/>BlobCreated triggers"]:::container

        ca["Container Apps Jobs<br/>(Phase 2)<br/>Ventra ingestion, backups,<br/>alert digest"]:::container

        ai["Application Insights +<br/>Log Analytics<br/>traces, metrics, logs"]:::container

        acs["Azure Communication<br/>Services Email<br/>daily digest, alerts"]:::container
    end

    entra["Microsoft Entra ID<br/>HHA M365 tenant"]:::external
    ventra["Ventra SFTP"]:::external

    user -->|"HTTPS"| web
    user -->|"OAuth redirect"| entra
    web -->|"Authorization: Bearer<br/>(hha_session cookie or MSAL)"| api
    web -.->|"server-side renders"| api

    api -->|"async SQLAlchemy<br/>asyncpg"| pg
    api -->|"Managed Identity"| kv
    api -->|"Managed Identity"| blob
    api -->|"OpenTelemetry"| ai
    api -.->|"send email"| acs

    ventra -.->|"SFTP push<br/>(Phase 2)"| blob
    blob -.->|"BlobCreated"| eg
    eg -.->|"trigger"| ca
    ca -.->|"upsert aggregates"| pg

    web -->|"Managed Identity"| kv
    web -->|"OpenTelemetry"| ai
```

**Key facts in this diagram:**

- **Two App Services**: `app-hha-web-prod` (Next.js) and `app-hha-api-prod` (FastAPI). Both Linux B1 tier.
- **Managed Identity everywhere** — no static secrets. Web and API authenticate to Key Vault and Storage via their App Service identity.
- **The dashed boxes (Event Grid, Container Apps Jobs)** are Phase 2 additions — not yet provisioned.
- **`hha_session` cookie** carries auth between web and API; httpOnly + sameSite=strict.

---

## 3. Deployment topology

Where the Azure resources sit.

```mermaid
flowchart LR
    classDef sub fill:#005bbb,stroke:#003e80,color:#fff
    classDef rg fill:#0078d4,stroke:#005bbb,color:#fff
    classDef resource fill:#50c878,stroke:#3fa860,color:#fff
    classDef external fill:#999,stroke:#8a8a8a,color:#fff

    sub["Azure Subscription<br/>(HHA M365 tenant)"]:::sub

    subgraph rg ["rg-hha-dashboard-prod (centralus)"]
        plan["app-hha-plan-prod<br/>App Service Plan B1"]:::resource
        web["app-hha-web-prod<br/>App Service Linux Node"]:::resource
        api["app-hha-api-prod<br/>App Service Linux Python"]:::resource
        pg["psql-hha-prod<br/>Postgres Flex B1ms"]:::resource
        kv["kv-hha-prod2<br/>Key Vault Standard"]:::resource
        st["sthhaprod<br/>Storage Account LRS"]:::resource
        ai["appi-hha-prod<br/>Application Insights"]:::resource
        law["log-hha-prod<br/>Log Analytics"]:::resource
        acs["acs-hha-prod<br/>Communication Services"]:::resource
    end

    gh["GitHub Actions<br/>(OIDC federated identity)"]:::external
    dns["DNS (custom domain<br/>future: pulse.hhamedicine.com)"]:::external

    sub --> rg

    plan --- web
    plan --- api

    web -.->|"hostname"| dns

    gh -.->|"OIDC token exchange,<br/>az deployment + zip deploy"| rg
```

**Key facts:**

- **One resource group, one region.** No multi-region (deferred to Phase 4).
- **No VNet today** — direct public endpoints with firewall rules. Phase 3 may add VNet.
- **GitHub Actions deploys** via OIDC federated identity — no stored credentials.

---

## 4. Entra ID auth flow

How an executive signs in to the dashboard.

```mermaid
sequenceDiagram
    autonumber
    actor U as User (exec)
    participant W as Web (Next.js)
    participant E as Entra ID
    participant A as API (FastAPI)
    participant K as Key Vault

    U->>W: GET / (no session)
    W->>U: 302 redirect to /signin
    U->>W: GET /signin
    W->>U: Render sign-in page
    U->>E: Click "Sign in with Microsoft"
    E->>U: MFA challenge (per Conditional Access)
    U->>E: Complete MFA
    E->>W: Callback with id_token (signed JWT)
    W->>K: Fetch SESSION_SECRET via Managed Identity
    K->>W: SESSION_SECRET
    W->>W: Validate id_token signature + claims<br/>(iss, aud, exp, groups)
    W->>W: Encrypt session payload with SESSION_SECRET<br/>(user upn, groups, expiry)
    W->>U: Set hha_session cookie (httpOnly, sameSite=strict, 8h)
    W->>U: 302 redirect to /

    Note over U,A: Subsequent API calls
    U->>W: GET /api/operations/summary (with cookie)
    W->>W: Decrypt cookie, extract upn + groups
    W->>A: GET /api/operations/summary<br/>Authorization: Bearer <session token>
    A->>A: Verify token, set audit.upn GUC,<br/>check role membership
    A->>U: 200 OK with summary data
```

**Key facts:**

- The browser **never sees the raw id_token** — it's encrypted into the `hha_session` cookie on the server.
- The cookie is **httpOnly** so JavaScript can't read it (XSS protection).
- The API **re-verifies** the session token on every request — no implicit trust.
- The `audit.upn` GUC is set per-request so audit triggers capture identity.

See [ENTRA_SETUP.md](../03-engineering/ENTRA_SETUP.md) for the one-time Entra app registration steps.

---

## 5. Census portal auth flow

The census portal (Phase 1) uses a **shared kiosk credential**, not individual Entra sign-in. This is by design — site leaders use this on shared workstations.

```mermaid
sequenceDiagram
    autonumber
    actor S as Site leader
    participant P as Portal page (/census)
    participant A as API
    participant DB as Postgres

    S->>P: GET /census
    P->>S: Render login form (email + password)
    S->>P: Submit portal@hhamedicine.com + password
    P->>A: POST /api/v1/census-portal/login
    A->>DB: SELECT FROM portal_credentials WHERE email = ?
    DB->>A: argon2id hash
    A->>A: argon2id verify
    A->>A: Issue portal_session token (role=portal_kiosk, 1h)
    A->>P: 200 OK with token
    P->>S: Set portal_session cookie (httpOnly, 1h, single-session)

    Note over S,DB: Census entry
    S->>P: Fill in site + date + census count
    P->>A: POST /api/v1/census-portal/entry (with cookie)
    A->>A: Verify portal_session, check role=portal_kiosk
    A->>DB: INSERT INTO entries.census_daily<br/>(audit.upn = 'portal-kiosk')
    DB->>DB: Trigger writes to audit.audit_log
    A->>P: 201 Created
```

**Key facts:**

- **Single shared credential** for all site leaders. Not per-user.
- **`role=portal_kiosk`** restricts the session to only the census-entry endpoint — no access to dashboards.
- **`audit.upn = 'portal-kiosk'`** in the audit log so we know it came from the portal even though we don't know which human.
- See [PHASE_1_CENSUS_PORTAL.md](../05-product/PHASE_1_CENSUS_PORTAL.md) and [adr/002-rbac-model.md](adr/002-rbac-model.md) for the threat model.

---

## 6. Ventra ingestion data flow

Phase 2. Ventra pushes daily CSVs via SFTP; we trigger an aggregation job on receipt.

```mermaid
flowchart LR
    classDef vendor fill:#999,stroke:#8a8a8a,color:#fff
    classDef azure fill:#0078d4,stroke:#005bbb,color:#fff
    classDef pg fill:#336791,stroke:#234c69,color:#fff

    ventra["Ventra<br/>nightly cron<br/>(their side)"]:::vendor

    subgraph azureRG ["Azure (HHA tenant)"]
        sftp["Storage Account<br/>SFTP-enabled<br/>container: ventra-incoming"]:::azure
        manifest["/_MANIFEST.csv<br/>(written last)"]:::azure
        eg["Event Grid<br/>BlobCreated filter:<br/>_MANIFEST.csv only"]:::azure
        job["Container Apps Job<br/>cj-hha-ventra-ingest<br/>Python 3.12"]:::azure
        pg["Postgres<br/>facts.collections_daily<br/>facts.ar_snapshot<br/>facts.revenue_by_physician_mo"]:::pg
        quarantine["Storage Account<br/>container: ventra-quarantine<br/>(failed parses)"]:::azure
        audit["Postgres<br/>audit.audit_log<br/>ingest.run_log"]:::pg
    end

    ventra -->|"SSH key auth +<br/>IP allowlist"| sftp
    sftp -->|"writes 10 CSVs<br/>per day"| sftp
    sftp -.->|"BlobCreated event"| eg
    eg -->|"only when _MANIFEST.csv lands"| job

    job -->|"reads all CSVs<br/>for the date"| sftp
    job -->|"STRIPS PHI + aggregates"| pg
    job -->|"logs run status"| audit
    job -.->|"on parse failure"| quarantine

    sftp -.->|"lifecycle: cool@7d,<br/>delete@30d"| sftp
```

**Key facts:**

- **Manifest-triggered** — Event Grid only fires the job when `_MANIFEST.csv` lands, never on individual data files. This prevents picking up half-complete drops.
- **PHI is stripped before any database write** (see diagram 7).
- **Raw files have a 30-day Blob lifecycle** then auto-delete. We never persist raw rows in Postgres.
- **Failed parses go to a quarantine container** for investigation.

Full architecture in [INGESTION_VENTRA.md](../03-engineering/INGESTION_VENTRA.md).

---

## 7. HIPAA firewall flow

The single most important diagram for compliance. Shows what gets stripped where.

```mermaid
flowchart TB
    classDef phi fill:#c1272d,stroke:#8e1c21,color:#fff
    classDef safe fill:#50c878,stroke:#3fa860,color:#fff
    classDef boundary fill:#f7f7f7,stroke:#999,color:#333

    ventra["Ventra CSV<br/>contains:<br/>InvoiceNo, PatFName, PatLName,<br/>PatDOB, SSN, MRN, ICD-10, CPT,<br/>FacilityNo, PayerClass, $ amounts"]:::phi

    blob["Azure Blob<br/>(temporary — 30-day shred)"]:::phi

    parser["Container Job parser<br/>polars + Python"]:::boundary

    allowed["allowed_columns filter<br/>{ FacilityNo, PayerClass,<br/>PostingDate, ChargeAmt,<br/>PaymentAmt, RVU, NPI, ... }"]:::safe

    forbidden["FORBIDDEN columns dropped:<br/>❌ PatFName, PatLName, PatMI<br/>❌ PatDOB, PatSex<br/>❌ SSN, MRN, HospAcctNo, DEPK<br/>❌ ICD9_*, ICD10_*<br/>❌ CPT, Modifiers<br/>❌ All Guarantor fields<br/>❌ Insurance PolicyID, Group"]:::phi

    aggregator["In-memory aggregator<br/>GROUP BY (date, site, payer_class)"]:::boundary

    facts["Postgres facts.* tables<br/>ONLY aggregates:<br/>✅ date, site_id, payer_class<br/>✅ gross_charges, payments,<br/>adjustments, refunds<br/>✅ npi (physician), encounters_count<br/>✅ source_system tag"]:::safe

    ventra -->|"SFTP push"| blob
    blob -->|"read row-by-row"| parser
    parser --> allowed
    parser -.->|"discarded in memory"| forbidden
    allowed --> aggregator
    aggregator -->|"UPSERT aggregate"| facts

    note1["Boundary 1<br/>SFTP — wire encrypted (SSH)"]
    note2["Boundary 2<br/>Blob — encrypted at rest, 30-day TTL"]
    note3["Boundary 3<br/>Parser — strips at row level"]
    note4["Boundary 4<br/>Aggregator — collapses to safe grain"]
    note5["Boundary 5<br/>Postgres — encrypted at rest, audit on every write"]

    style note1 fill:#fff7e6
    style note2 fill:#fff7e6
    style note3 fill:#fff7e6
    style note4 fill:#fff7e6
    style note5 fill:#fff7e6
```

**Key facts:**

- **5 defense-in-depth boundaries.** PHI has to cross all 5 to leak — and one of them (the parser) is enforced by a strict allowlist, not a denylist.
- **Allowlist, not denylist.** If Ventra adds a new column we don't know about, it's automatically excluded.
- **Aggregation collapses identity.** Even if a column slipped through, GROUP BY (date, site, payer_class) loses any per-patient resolution.

Full HIPAA detail in [adr/001-hipaa-data-classification.md](adr/001-hipaa-data-classification.md) and [COMPLIANCE_POSTURE.md](../01-leadership/COMPLIANCE_POSTURE.md).

---

## 8. Audit chain

How "who did what when" gets captured at the database level.

```mermaid
sequenceDiagram
    autonumber
    actor U as User (alice@hha.com)
    participant W as Web
    participant A as API request handler
    participant D as SQLAlchemy session
    participant T as PG Trigger
    participant L as audit.audit_log

    U->>W: POST /api/v1/operations/census<br/>(with hha_session cookie)
    W->>A: Forward request with bearer token
    A->>A: Verify session, extract upn='alice@hha.com'
    A->>D: BEGIN transaction
    A->>D: SET LOCAL audit.upn = 'alice@hha.com'
    A->>D: INSERT INTO entries.census_daily VALUES (...)
    D->>T: Trigger AFTER INSERT
    T->>T: SELECT current_setting('audit.upn')
    T->>L: INSERT INTO audit.audit_log<br/>(actor_upn='alice@hha.com',<br/> table_name='census_daily',<br/> operation='INSERT',<br/> row_id=..., diff=...,<br/> occurred_at=now())
    A->>D: COMMIT
    A->>W: 201 Created
    W->>U: 201 Created
```

**Key facts:**

- **`audit.upn` is a Postgres session GUC** — set inside the transaction, read by the trigger. Survives across raw SQL and async operations within the same session.
- **Triggers fire on every mutation path**: ORM, raw SQL, cron jobs. If you can write a row, the trigger captures it.
- **`audit.audit_log` has no DELETE permission for app users.** Rows are append-only.
- **Daily backups include audit log**, stored in WORM Blob.

ADR-003 covers the technical design: [adr/003-audit-chain.md](adr/003-audit-chain.md).

---

## 9. Schema ERD

Postgres schemas and their relationships. Six logical schemas; physically all in one database.

```mermaid
erDiagram
    sites ||--o{ census_daily : "has many"
    sites ||--o{ monthly_finance_manual : "has many"
    sites ||--o{ headcount_daily : "has many"
    sites ||--o{ open_positions : "has many"
    sites ||--o{ credentials_expiring : "tracks"

    physicians ||--o{ comp_agreements : "has time-variant"
    physicians ||--o{ revenue_by_physician_mo : "monthly"
    physicians ||--o{ rvu_paycheck : "biweekly"
    physicians ||--o{ scorecard_snapshot : "monthly"

    contracts ||--o| sites : "linked"

    sites {
        int id PK
        string site_code "Westside, etc"
        string state "FL or TX"
        boolean is_active
        timestamptz created_at
    }

    physicians {
        int id PK
        string npi UK "10-digit NPI"
        string first_name
        string last_name
        string employment_type "W2 / 1099"
        boolean is_active
    }

    census_daily {
        int id PK
        int site_id FK
        date entry_date
        int census_count
        string source "portal / manual"
        string created_by_upn
        timestamptz created_at
    }

    collections_daily {
        int id PK
        int site_id FK
        date posting_date
        string payer_class
        string source_system "VENTRA_FL_ATHENA / HHA_TX_MANUAL"
        decimal gross_charges
        decimal payments_received
        decimal contractual_adjustments
        decimal write_offs
        decimal payer_refunds
        decimal patient_refunds
        decimal net_revenue
    }

    ar_snapshot {
        int id PK
        int site_id FK
        date snapshot_date
        string aging_bucket "0-30 / 31-60 / ... / 120+ / credit"
        decimal outstanding_amount
        string source_system
    }

    revenue_by_physician_mo {
        int id PK
        date month
        string physician_npi FK
        int facility_no
        int encounters_count
        decimal total_rvu
        decimal total_work_rvu
        decimal revenue_attributed
        string source_system
    }

    audit_log {
        bigint id PK
        string actor_upn
        string actor_role
        string table_name
        string operation
        bigint row_id
        jsonb diff
        timestamptz occurred_at
    }

    alert_subscriptions {
        int id PK
        string email
        string role
        jsonb categories
        string frequency
    }
```

**Key facts about schemas:**

| Schema | Purpose |
|---|---|
| `masters` | Reference data: `sites`, `physicians`, `contracts`, `payer_class_map` |
| `entries` | Manual entry data: `census_daily`, `monthly_finance_manual`, `open_positions` |
| `facts` | Aggregated facts from automated sources: `collections_daily`, `ar_snapshot`, `revenue_by_physician_mo`, `headcount_daily`, `terminations`, `rvu_paycheck` |
| `audit` | Audit log: `audit_log` |
| `alerts` | Alert routing: `alert_subscriptions`, `alert_history` |
| `dims` | Dimension tables (Phase 2+): `payer_class`, `facility_codes` |

Full table-by-table reference in [DATA_MODEL.md](DATA_MODEL.md).

---

## 10. Phase progression timeline

```mermaid
gantt
    title HHA Dashboard — phase progression
    dateFormat YYYY-MM-DD
    axisFormat %Y-%m

    section Phase 0 — Foundation
    Infra, schema, auth, CI/CD          :done, p0, 2026-04-01, 2026-04-26

    section Phase 1 — Manual entry + Ops board
    Build (manual entry, ops board)      :done, p1build, 2026-04-26, 2026-05-04
    Live in production                   :active, p1live, 2026-05-04, 2026-06-15

    section Phase 2 — Ventra finance + Scorecards
    Vendor meeting + spec negotiation    :done, p2neg, 2026-05-05, 2026-05-15
    Build ingestion job + finance board  :p2build, 2026-05-15, 2026-07-01
    Doctor Scorecards                    :p2score, 2026-06-15, 2026-07-15

    section Phase 3 — Polish
    Mobile + custom domain + alerts      :p3, 2026-08-01, 2026-08-31

    section Phase 4 — Future
    Paycom (optional)                    :p4paycom, 2027-01-01, 2027-02-28
    Multi-region (only if needed)        :p4mr, 2027-06-01, 2027-06-30
```

**Critical-path bottleneck:** Ventra spec negotiation. We sent a counter-proposal (Option A pre-aggregated CSVs) on 2026-05-11; awaiting response post-PTO (Gilda back 2026-05-14). Phase 2 build start date depends on this.

---

## How to update these diagrams

1. Edit the Mermaid code blocks in this file
2. Preview locally — VS Code has a Mermaid preview extension, or paste into https://mermaid.live
3. Commit with message `docs(diagrams): update <which diagram> for <what changed>`
4. For SharePoint upload, regenerate PDFs via `scripts/export-to-pdf.sh`

## How to add a new diagram

1. Insert a new top-level `## N. <Title>` section
2. Add the entry to the index at the top of this file
3. Place the Mermaid block, then 2 paragraphs of explanation
4. Cross-link from the most relevant narrative doc

---

**Next read:** [DATA_MODEL.md](DATA_MODEL.md) for the table-by-table reference.
