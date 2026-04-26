# CLAUDE.md — HHA Dashboard

> Every Claude Code session reads this file first. It is the contract. If it conflicts with anything else, this wins.

## What this project is

HHA Medicine Operations Dashboard — an Azure-only, HIPAA-first analytics platform for HHA exec leadership. Single Next.js + FastAPI + PostgreSQL stack. Solo build with Claude Code.

Build plan lives in [DASHBOARD_PLAN.md](../DASHBOARD_PLAN.md) (root of the OneDrive project folder). ADRs live in [docs/adr/](docs/adr/). Operational procedures live in [docs/RUNBOOK.md](docs/RUNBOOK.md). Read all three before any significant work.

**Authoritative ADRs (in priority order):**

- [ADR-001 — HIPAA data classification](docs/adr/001-hipaa-data-classification.md) — column-level `data_class` rules, no-PHI invariant, BAA inventory
- [ADR-002 — RBAC model](docs/adr/002-rbac-model.md) — Entra groups, `comp_viewer` additive flag, separate census portal threat model
- [ADR-003 — Audit chain](docs/adr/003-audit-chain.md) — why PG triggers (not ORM listeners), how `audit.upn` GUC propagates, what's audited
- [ADR-004 — Backup & DR](docs/adr/004-backup-and-disaster-recovery.md) — managed + custom pg_backup, WORM lock, restore drill, RTO/RPO commitments
- [ADR-005 — FL/TX scope split](docs/adr/005-fl-tx-scope-split.md) — Ventra is FL-only, TX is manual-only, `source_system` invariant

**Operational reference:** [docs/RUNBOOK.md](docs/RUNBOOK.md) — first-deploy procedure, incident playbooks, secret rotation, restore drill invocation. The 2 a.m. document.

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

#### API client split (server vs browser)

Per Session 6 (PR #9 merged):

- **Server components** import from `@/lib/api-client` — Node-only module that reads the encrypted `hha_session` cookie via `cookies()` from `next/headers` and forwards it as `Authorization: Bearer`.
- **Client components** (entry forms) import `useApiBrowser` from `@/lib/api-browser` — uses MSAL `acquireTokenSilent` directly. **They never read the cookie** (echoing httpOnly cookies to JS is an XSS exfil primitive).
- Both share the pure fetcher in `@/lib/api-fetch.ts`. Auth header is injected; the fetcher knows nothing about cookies or MSAL.
- Don't import `next/headers` in any `"use client"` file — Next will hard-error at build.

### Bicep / IaC (infra/)

Per Session 8 (PR #13 merged) and Session 9 (PR #15 in flight):

- All Bicep files compile-checked in CI (`.github/workflows/ci.yml` bicep job). Locally: `az bicep build` + `az bicep build-params` + `az bicep lint`.
- **Network posture is parameter-driven**: `enable_vnet` toggle in `main.bicep`. `false` (dev default) keeps Postgres public-with-firewall. `true` (prod default) switches Postgres to VNet injection (no public address).
- **`postgres.bicep` and `appservice.bicep` are backward-compatible** — new VNet/KV parameters default to empty/false. Adding a Bicep module = parameterize, never break the existing dev posture.
- **No `0.0.0.0` AllowAllAzureServices firewall rule** anywhere in the templates. HIPAA auditor flag.
- **Connection strings are composed in `main.bicep`, not output by modules.** Secrets never reach module outputs (which are visible to RG Reader).
- **BCP178 limitation**: Bicep can't drive a resource loop count from a deploy-time output (e.g. App Service `outboundIpAddresses`). Workaround: post-deploy `az` CLI snippet documented in `infra/README.md`.

### SQL / migrations

- Alembic co-located at `api/alembic/`
- Every migration has `downgrade()` that works
- Schema changes run in dev first, then staging, then prod with manual approval
- Migration touching sensitive tables requires ADR update
- **Audit triggers** (PR #7 merged) on every table in `services/audit.py::AUDITED_TABLES` — adding a new audited table requires updating that frozenset AND adding it to the trigger migration

### Repository layout gotcha

The git repo root is `HHA_Dashboard_New_Joey/`, **not** `hha-dashboard/`. Confirmed via `git rev-parse --show-toplevel`. Two `.gitignore` files apply:
- `HHA_Dashboard_New_Joey/.gitignore` — repo-root, broad rules
- `HHA_Dashboard_New_Joey/hha-dashboard/.gitignore` — codebase-scoped rules

When adding new gitignore patterns, decide which level they belong at. The Python `env/` rule that matched `infra/env/` was the canonical example (caught and scoped in the Session 8 PR).

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
