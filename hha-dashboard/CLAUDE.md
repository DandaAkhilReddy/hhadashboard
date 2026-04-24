# CLAUDE.md — HHA Dashboard

> Every Claude Code session reads this file first. It is the contract. If it conflicts with anything else, this wins.

## What this project is

HHA Medicine Operations Dashboard — an Azure-only, HIPAA-first analytics platform for HHA exec leadership. Single Next.js + FastAPI + PostgreSQL stack. Solo build with Claude Code.

Build plan lives in [DASHBOARD_PLAN.md](../DASHBOARD_PLAN.md) (root of the OneDrive project folder). ADRs live in [docs/adr/](docs/adr/). Read both before any significant work.

## Who uses it

Exec leadership only (CEO, CFO, CMO, COO). Plus named department owners (Crystal, Sandy, Maribel, Dr. Aneja, Dr. Reddy, Andrea) for manual data entry. 5–10 users total. No doctor logins. No public access.

## What's in scope

4 team boards (Operations, Finance, Clinical, People) + exec-only Doctor Scorecards. See DASHBOARD_PLAN.md § Scope.

## What's out of scope (never add)

- Any denial analytics (Ventra owns RCM entirely)
- Patient PHI in any view or schema (ADR-001)
- Claim-level browser, patient name/DOB/MRN, 835 denial lines
- Charge lag, timely filing, clean claim rate, denial overturn, appeals
- Patient satisfaction, portal adoption, payment plans, self-pay
- Cost-side P&L
- **Any Texas RCM integration.** Per 2026-04-23 scope decision, TX is manual-entry only. Ventra handles Florida only. Don't build TX ingestion jobs, TX API clients, or TX-specific automation.

When asked to add any of these, respond: *"That's in the OUT-of-scope list per DASHBOARD_PLAN.md. It needs a new phase and both co-sponsor (CEO + CFO) sign-off."*

## FL vs TX data sources (important)

HHA's book has two states with different automation levels:

| State | Automation | Source |
|---|---|---|
| **Florida** | Automated (Phase 2) | Ventra → Athena → pre-aggregated ingestion |
| **Texas** | **Manual only** | Sandy/Maribel enter monthly numbers via `/entry/monthly-finance` form |

Consequences in code:

- `monthly_finance_manual` and `fact_collections_daily` **must have a `source_system` column** with values like `VENTRA_FL_ATHENA` or `HHA_TX_MANUAL`. Never mix the two books in the same row.
- Finance board UI labels every tile with its source (e.g. "FL · Ventra" / "TX · manual").
- Ingestion jobs for Ventra **only** fetch FL data. A bug that ingests TX from Ventra = incident.
- Ops / Clinical / People / Scorecards boards cover all 11 sites (FL + TX) equally — Paycom serves both states. Only Finance has the split.

## The stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 15 App Router + Tailwind + shadcn/ui + Tremor + Recharts |
| Backend | FastAPI (Python 3.12) + SQLAlchemy 2.0 async + Alembic |
| Database | Azure Database for PostgreSQL Flexible Server 16 |
| Auth | Entra ID via MSAL (browser + server) |
| Hosting | Azure App Service Linux (web + api) |
| Scheduled jobs | Azure Container Apps Jobs |
| Email | Azure Communication Services |
| Observability | Application Insights + Log Analytics |
| Secrets | Azure Key Vault + Managed Identity |
| Backups | Azure Blob with immutability (WORM) |
| IaC | Bicep |
| CI/CD | GitHub Actions with OIDC federated identity |
| Local dev | docker-compose (Postgres + Mailpit + Adminer) |

## HIPAA non-negotiables

Read [docs/adr/001-hipaa-data-classification.md](docs/adr/001-hipaa-data-classification.md) before any data-model or ingestion work.

Absolute rules:

1. **Never add a column with `data_class: C`** to any SQLAlchemy model. CI test `tests/test_schema_classification.py` enforces. If a migration adds one, CI fails.
2. **`claim_id`, `encounter_id`, `dos_per_line`, `cpt_per_line`, `patient_*`, `mrn`, `member_id`, `subscriber_*`, `guarantor_*` — forbidden column names.** Pre-commit hook blocks.
3. **Every column gets `info={"data_class": "A"|"B"|"C"|"D"}`** — no exceptions. New column without classification = PR blocked.
4. **Ventra ingestion pre-aggregates at the edge.** Raw claim records are read, rolled up in memory, discarded. Raw CSV drops land in Blob with 30-day lifecycle then auto-shred.
5. **No patient names, DOBs, MRNs, or any 18-HIPAA-identifier in logs.** `structlog` processor scrubs. Telemetry PII-scrubbed in App Insights config.

## Coding conventions

### Python (api/, jobs/)

- Python 3.12, `uv` for package management, `pyproject.toml` is source of truth
- Type annotations on every parameter, return, and non-obvious variable
- Async everywhere — `async def` + `AsyncSession` + `httpx.AsyncClient`. No sync I/O in request paths
- Pydantic v2 for all request/response models
- SQLAlchemy 2.0 declarative with typed columns: `Mapped[str]` + `mapped_column(...)`
- Every table in schema `masters` / `entries` / `facts` / `audit` / `alerts` / `dims`
- Custom exceptions in `app/exceptions.py`, never bare `except:`
- `structlog` for logging, never `print`, never `logging.debug`
- `ruff` for lint, `mypy --strict` for types, `pytest` for tests
- 80% coverage minimum on `services/`, 90%+ on `services/comp.py`, `services/scorecard.py`, `services/audit.py`

### TypeScript (web/)

- `strict: true` in `tsconfig.json`, no `any` without justification in comment
- Server components by default; client only when hooks/state needed
- `openapi-typescript` generates `lib/api-types.ts` — **never edit manually**, regenerate from `http://localhost:8000/openapi.json`
- `biome` for lint+format (single tool)
- `vitest` for unit, Playwright for critical user paths (sign-in, role-gated routes, entry forms)
- Tailwind only; never inline styles; shadcn/Tremor components over hand-rolled

### SQL / migrations

- Alembic co-located at `api/alembic/`
- Every migration has `downgrade()` that works
- Schema changes run in dev first, then staging, then prod with manual approval
- Migration touching sensitive tables requires ADR update

## Commit conventions

Format: `type(scope): description` — lowercase, imperative, no period. Types: `feat, fix, refactor, test, docs, chore, perf, ci`. One logical change per commit.

**Cadence: commit aggressively and granularly.** The goal is a dense, readable history. Guidelines:

- Every logical change is its own commit — *not* batched
- Adding a file → commit. Adding a function to an existing file → commit. Fixing a typo → commit. Renaming a variable → commit. Adjusting a Tailwind class → commit.
- During active coding, a commit every 5–20 minutes is normal. Sessions typically produce **20–80 commits**.
- Never end a session with one big "today's work" commit. Split as you go.
- Each commit message still follows the `type(scope): description` format. No "wip" or "fix stuff" — they still have to be meaningful.
- Atomic + revertable still holds: any single commit should be safe to `git revert` without breaking unrelated things.

Examples (good granularity):

- `feat(scorecards): add Overall Rank composite service`
- `feat(scorecards): wire rank into list endpoint response`
- `test(scorecards): assert rank ordering for 3-physician fixture`
- `fix(audit): capture diff on UPDATE of comp_agreements`
- `docs(adr): extend §5 to cover comp_agreement column classification`
- `chore(infra): enable immutability policy on backups container`
- `refactor(uploads): extract filename-inference helper into lib/infer.ts`
- `style(uploads): align staged-file row spacing with mockup`

**What not to do:** never pad with empty commits, never split a single diff into nonsensical fragments just to raise the count, never add "no-op" or "bump" commits. If the change wouldn't pass review on its own, don't commit it.

Never commit to `main` directly. Always feature branch: `feat/<name>`, `fix/<name>`, `chore/<name>`.

Never add `Co-Authored-By` trailers.

Author: `Danda Akhil Reddy <akhilreddydanda3@gmail.com>`

Remote: `https://github.com/DandaAkhilReddy/hhadashboard` (private).

## PR template

```
## What
<one-sentence summary>

## Why
<the need this addresses — link ADR or ticket>

## HIPAA classification checklist
- [ ] No column added with data_class: C
- [ ] No forbidden column names (claim_id, patient_*, etc.)
- [ ] All new columns have data_class info={}
- [ ] If touching ingestion: pre-aggregate rule preserved

## Test
- [ ] Unit tests added
- [ ] Integration test for RBAC (if endpoint)
- [ ] Audit log test (if sensitive-table mutation)

## Screenshots (if UI)
```

## Forbidden operations (will fail CI / be rejected in review)

1. Adding any column with `data_class: C`
2. Adding a migration that drops `audit_log` rows
3. Bypassing `require_role` or `require_comp_viewer` decorators
4. Logging anything that looks like PHI (names, DOBs, MRNs, insurance IDs)
5. Committing a `.env` file
6. Using `git commit --no-verify` to skip hooks
7. Adding a non-BAA-covered vendor to the data path (Railway, Clerk, Resend, Sentry, Cloudflare, etc.)
8. Writing raw SQL with f-strings or `.format()` — parameterized queries only
9. Introducing a new Python or npm dependency without an ADR entry
10. Amending or force-pushing to `main`

## Common commands

```bash
# local dev stack
docker compose up -d                    # postgres + mailpit + adminer

# api
cd api && uv sync && uv run uvicorn app.main:app --reload
cd api && uv run alembic upgrade head
cd api && uv run pytest
cd api && uv run ruff check . && uv run mypy app/

# web
cd web && npm install && npm run dev
cd web && npm run gen-types             # regenerate lib/api-types.ts
cd web && npm run lint && npm run test

# infra (Azure)
az login
az account set -s hha-production
cd infra && az deployment group what-if -g rg-hha-dashboard-dev -f main.bicep -p env/dev.bicepparam
cd infra && az deployment group create  -g rg-hha-dashboard-dev -f main.bicep -p env/dev.bicepparam

# backup / restore drill
python scripts/restore-drill.sh
```

## Before every significant change

1. Read DASHBOARD_PLAN.md § Scope to confirm it's IN
2. Read ADR-001 if touching any data or ingestion
3. Check `tests/test_schema_classification.py` still passes after model changes
4. Update ADRs if you're making a new architectural decision

## When in doubt

Ask Akhil. Don't guess on HIPAA boundaries. Don't guess on comp visibility rules. Don't guess on whether a metric is HHA's or Ventra's (if you can't tell, it's Ventra's).

_Last updated: 2026-04-23 · v5 plan locked, Week 0 starting_
