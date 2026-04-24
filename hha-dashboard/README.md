# HHA Medicine — Operations Dashboard

Azure-only, HIPAA-first analytics platform for HHA exec leadership. Single Next.js + FastAPI + PostgreSQL stack. Solo build with Claude Code.

**Status:** Phase 0 — Foundation (Week 1–2)

---

## What this is

Dashboard for HHA Medicine executive leadership (CEO, CFO, COO, CMO) covering 4 operational boards across 11 hospital sites (7 FL + 4 TX):

- **Operations** — daily census, coverage, contracts, MD status per site
- **Finance** — HHA top-line only (collections, AR aging 5-bucket, days in A/R, NCR). Denials are Ventra's scope — out
- **Clinical Quality** — H&P / DC timeliness, LOS by state, credential expiry
- **People & Pipeline** — headcount (W-2 vs 1099), turnover, open positions, below-FMV
- **Doctor Scorecards** (exec-only) — per-MD rank, RVU, productivity, documentation, chart turnaround

## Read these first

1. [**`CLAUDE.md`**](./CLAUDE.md) — the contract every Claude Code session follows
2. [**`docs/adr/001-hipaa-data-classification.md`**](./docs/adr/001-hipaa-data-classification.md) — the PHI firewall
3. [**`../DASHBOARD_PLAN.md`**](../DASHBOARD_PLAN.md) (OneDrive project folder) — the full build plan v5

## Stack

| | |
|---|---|
| Frontend | Next.js 15 App Router + Tailwind + shadcn/ui + Tremor + Recharts |
| Backend | FastAPI (Python 3.12) + SQLAlchemy 2.0 async + Alembic |
| Database | Azure Database for PostgreSQL Flexible Server 16 |
| Auth | Entra ID via MSAL |
| Hosting | Azure App Service Linux |
| Jobs | Azure Container Apps Jobs |
| Email | Azure Communication Services |
| Logs | Application Insights + Log Analytics |
| Secrets | Azure Key Vault + Managed Identity |
| Backups | Azure Blob (WORM immutable) |
| IaC | Bicep |
| CI/CD | GitHub Actions + OIDC federated identity |
| Local dev | docker-compose (Postgres + Mailpit + Adminer) |

Every vendor has a signed BAA (Microsoft's default for Azure + M365; Ventra confirmed before P2).

## Repository layout

```
hha-dashboard/
├── CLAUDE.md                  # contract for every Claude Code session
├── README.md                  # you are here
├── docker-compose.yml         # local dev (Postgres + Mailpit + Adminer)
├── .env.example
├── .gitignore
├── .github/workflows/         # CI + deploy via OIDC
├── infra/                     # Bicep IaC for Azure env
├── api/                       # FastAPI backend
├── web/                       # Next.js 15 frontend
├── jobs/                      # Container Apps Jobs (Python): sync, alerts, backup
├── scripts/                   # bootstrap, seed, restore drill
└── docs/
    ├── adr/                   # architecture decision records
    ├── ARCHITECTURE.md
    ├── METRICS.md
    ├── RUNBOOK.md
    └── ONBOARDING.md
```

## Quick start (local dev)

Prerequisites:

- Docker Desktop
- Python 3.12 + [uv](https://github.com/astral-sh/uv)
- Node 20+
- Azure CLI (`az`)
- GitHub CLI (`gh`)

```bash
# 1. Clone and copy env
git clone https://github.com/DandaAkhilReddy/hhadashboard.git hha-dashboard
cd hha-dashboard
cp .env.example .env
# edit .env — see comments

# 2. Start local services
docker compose up -d
# → Postgres on :5432, Mailpit on :8025 (UI), Adminer on :8080

# 3. Backend
cd api
uv sync
uv run alembic upgrade head
uv run python ../scripts/seed-sites.py     # load the 11 sites
uv run uvicorn app.main:app --reload       # → http://localhost:8000

# 4. Frontend (new terminal)
cd web
npm install
npm run gen-types                          # pull OpenAPI → lib/api-types.ts
npm run dev                                # → http://localhost:3000
```

Sign in via Entra ID with your HHA account. Must be a member of one of the app's security groups.

## Testing

```bash
# api
cd api && uv run pytest                    # includes schema classification + RBAC + audit tests
cd api && uv run ruff check . && uv run mypy app/

# web
cd web && npm run test                     # vitest
cd web && npm run test:e2e                 # playwright
cd web && npm run lint
```

## Deploy

Deploy is via GitHub Actions with OIDC federated identity to Azure — no stored secrets. Merging to `main` triggers dev; prod requires manual approval.

```bash
# local dry-run of Bicep
cd infra
az deployment group what-if -g rg-hha-dashboard-dev -f main.bicep -p env/dev.bicepparam

# manual apply (only if workflow fails)
az deployment group create -g rg-hha-dashboard-dev -f main.bicep -p env/dev.bicepparam
```

## HIPAA non-negotiables (read before any code change)

1. **Never add a column with `data_class: C`** — see ADR-001
2. **`claim_id`, `encounter_id`, `patient_*`, `mrn` — forbidden column names**
3. **Every new column gets `info={"data_class": ...}`** — no exceptions
4. **Ventra ingestion pre-aggregates at the edge** — raw claim records never persisted
5. **No PHI in logs** — `structlog` scrubs; telemetry PII-stripped in App Insights

Full matrix: [`docs/adr/001-hipaa-data-classification.md`](./docs/adr/001-hipaa-data-classification.md).

## Out of scope (will be declined)

- Any denial analytics (Ventra owns RCM)
- Claim-level browsing, patient PHI
- Charge lag, timely filing, clean claim rate, denial overturn, appeals
- Patient satisfaction, portal adoption, payment plans, self-pay
- Cost-side P&L

Scope changes require both co-sponsor (CEO + CFO) sign-off and a new phase in DASHBOARD_PLAN.md.

## License

Private. All rights reserved. HHA Medicine.

---

Built solo with [Claude Code](https://claude.ai/code). Technical lead: Danda Akhil Reddy.
