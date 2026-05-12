# Onboarding — HHA Dashboard

> Audience: a new contributor (engineer or solo Akhil-on-a-fresh-machine) coming to the codebase cold. Goal: clone → green local stack → first PR shipped within a working day. Read this **after** [CLAUDE.md](../../CLAUDE.md) (the contract) and [ARCHITECTURE.md](../02-architecture/ARCHITECTURE.md) (the system).

---

## TL;DR

```bash
git clone https://github.com/DandaAkhilReddy/hhadashboard
cd hhadashboard/hha-dashboard
docker compose up -d                    # Postgres + Mailpit + Adminer
cd api && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload
# in another terminal:
cd web && npm install && npm run dev
# open http://localhost:3000 — dev mode auto-redirects to /
```

If that worked, skip to [Week-1 actions](#week-1) below.
If it didn't, work through [Day-1](#day-1) sequentially.

---

## Day-1

### Prerequisites (one-time install)

| Tool | Version | Why |
|---|---|---|
| **Git** | 2.40+ | obvious |
| **Docker Desktop** | latest | runs the local Postgres + Mailpit + Adminer stack via `docker compose` |
| **Python** | 3.12.x | API runtime |
| **uv** | latest | Python package manager (`pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh \| sh`) |
| **Node** | 20.x LTS | web runtime |
| **npm** | comes with Node 20 | web package manager |
| **Azure CLI** | latest | only needed once you start touching infra |
| **VS Code** | latest | not strictly required but everyone uses it; install the Python, Pylance, Biome, and Tailwind IntelliSense extensions |

Verify each:

```bash
git --version          # 2.40+
docker --version       # 20+
python --version       # 3.12.x
uv --version
node --version         # v20.x
az --version           # only when needed
```

### 1. Clone + scope check

```bash
git clone https://github.com/DandaAkhilReddy/hhadashboard
cd hhadashboard
```

The repo root is `hhadashboard/` (not `hha-dashboard/`). The codebase lives under `hha-dashboard/`. This split is documented in CLAUDE.md — confirm it now so you don't add files in the wrong place later.

Read **before any code changes**:

1. [DASHBOARD_PLAN.md](../../../DASHBOARD_PLAN.md) — § Scope (what's IN, what's OUT — never debate this without sponsor sign-off)
2. [docs/adr/001-hipaa-data-classification.md](../02-architecture/adr/001-hipaa-data-classification.md) — column-level data-class rules. Skipping this means CI rejects your first migration.
3. [docs/adr/002-rbac-model.md](../02-architecture/adr/002-rbac-model.md) — Entra groups → roles, `comp_viewer` additive flag.
4. [ARCHITECTURE.md](../02-architecture/ARCHITECTURE.md) — at least §1 (At a glance) + §6 (Auth + RBAC).

### 2. Bring up the local data stack

```bash
cd hha-dashboard
docker compose up -d
docker compose ps        # postgres, mailpit, adminer all "healthy" / "running"
```

Smoke check Postgres:

```bash
docker exec -it hha-postgres psql -U hha -d hha_dashboard -c '\dn'
# expect: masters, entries, facts, audit, alerts, dims (after first migration)
```

Mailpit web UI: <http://localhost:8025>
Adminer (DB browser): <http://localhost:8080> · server `postgres`, user `hha`, password `hha`, db `hha_dashboard`

### 3. API up

```bash
cd hha-dashboard/api
uv sync                                  # installs deps from uv.lock
uv run alembic upgrade head              # applies all migrations 0001..N to the local DB
uv run uvicorn app.main:app --reload     # default port 8000
```

Smoke:

```bash
curl http://localhost:8000/health        # {"status":"ok"}
curl http://localhost:8000/api/v1/sites \
  -H 'Authorization: Dev admin'           # JSON list
```

### 4. Web up

```bash
cd hha-dashboard/web
npm install
npm run dev                              # default port 3000
```

Open <http://localhost:3000>. In dev mode (no MSAL env vars set), the homepage auto-loads as the Overview board with seeded `fake_data`. Visiting `/auth/sign-in` should bounce straight back to `/`.

### 5. Run every CI gate locally

Before pushing your first PR, every gate that CI runs must pass locally too:

```bash
# api
cd hha-dashboard/api
uv run ruff check .                      # style
uv run mypy app                          # types — strict mode
uv run pytest                            # ~260 tests, ~25s with Postgres up

# web
cd hha-dashboard/web
npm run lint                             # biome
npm run typecheck                        # tsc --noEmit
npm run test                             # vitest

# e2e (optional locally — runs in CI on every PR)
npm run e2e:install                      # one-time browser download (~110 MB)
npm run e2e
```

If any of these fail and you haven't touched the relevant code, your local environment is misconfigured — don't merge a "fix CI" workaround. Get the local gates green first.

### 6. First contribution path

1. Pick a small task — typo fix, docstring tighten, lint nag — and create a feature branch: `git checkout -b chore/<short-name>`.
2. Make the change, run the relevant gates locally (§5).
3. Commit per [commit conventions](../../../CLAUDE.md#commit-conventions): `type(scope): description`, lowercase, imperative.
4. Push: `git push -u origin chore/<short-name>`.
5. `gh pr create` (or the GitHub UI) — fill out the PR template (HIPAA checklist + Test section).
6. Wait for CI green. Self-review the diff. Squash-merge.

You've now shipped end-to-end. The first PR is the hardest because it forces you to prove the local environment matches CI.

---

## Week-1

After Day-1's setup is rock solid, the next 4 days should focus on building enough mental model that you can pick up a substantive ticket without supervision.

### Mon — Read the contracts

- [CLAUDE.md](../../CLAUDE.md) — full read. This is the contract; anything that conflicts with it loses.
- [docs/RUNBOOK.md](../04-operations/RUNBOOK.md) — the 2 a.m. document. Skim now so you know where to look when paged.
- All 5 ADRs in [docs/adr/](../adr). They're short, locked-in decisions — knowing them prevents you from re-litigating.

### Tue — Walk the data flows

- [ARCHITECTURE.md §5 (Data flows)](../02-architecture/ARCHITECTURE.md#5-data-flows) — login, daily census submit, monthly finance entry, alert evaluation, Ventra ingest, Paycom sync.
- For each one: locate the entry-point file (router or job) in `api/app/routers/` or `jobs/`. Trace the call to the DB. Identify which row(s) get written and which audit trigger fires.
- Output: a private 1-page summary diagram for yourself. You'll consult it constantly.

### Wed — Run a write end-to-end

- Bring the stack up (Day-1 §2-§4).
- Visit `/daily-census` (Crystal's form) signed in as dev admin. Enter a value for one site and save.
- Confirm via Adminer:
  - `entries.daily_entries` has a new row.
  - `audit.audit_log` has a matching `INSERT` row with `changed_by_upn = '__dev_admin@hha.com'` (or whatever the dev stub uses).
- Repeat for `/monthly-finance` (Sandy's form) — confirms the Tier-A boundary held: no PHI in the row.

### Thu — Pick a P3 ticket

- `gh issue list --label="good-first-issue"` (or whatever the maintainer label is).
- Anything in [docs/PROJECT_STATE_AUDIT.md](../99-archive/PROJECT_STATE_AUDIT.md) marked Phase 4+ that's not blocked is fair game.
- Spec it lightly in `.planning/<ticket>.md` (REQUIREMENTS → DESIGN → TASKS) and run it past the maintainer in a short Slack/email check before coding.

### Fri — Ship it

- Implement, test (unit + integration if it touches the DB), open PR.
- If the PR is bigger than ~400 lines diff, split it. Stacked PRs are fine; mega-PRs get rubber-stamped or rejected, never reviewed.

---

## Common gotchas

### "My migration test fails locally but passed in CI"

CI's Postgres user is a docker-image superuser (CREATEDB OK). Your local user might not be. Check:

```bash
docker exec -it hha-postgres psql -U hha -c '\du hha'
```

The `hha` role should have `Create DB`. If not: `ALTER USER hha CREATEDB;` as superuser.

### "biome / ruff fight my editor format-on-save"

The repo uses **biome** (web) and **ruff** (api). Disable ESLint, Prettier, and Black in your editor for this workspace — they'll fight the canonical tools and add noise diffs. Pre-commit hooks (`husky` + `lint-staged`) catch it anyway, but local diffs that aren't from your code change waste review time.

### "I added a new column and CI rejected it"

CI runs `tests/test_schema_classification.py` which fails any column without `info={"data_class": "A"|"B"|"C"|"D"}`. Add the classification to the `mapped_column(...)` call before re-running the migration.

### "Docker Compose says port 5432 already in use"

You probably already have a Postgres running locally outside Docker. Either stop it or change the docker-compose port mapping (and update `DATABASE_URL` accordingly). The latter is reversible; the former is usually fine because nobody runs two postgres servers on purpose.

### "Next.js dev server says NEXT_PUBLIC_* env var not picked up"

`NEXT_PUBLIC_*` vars are baked at process start. Restart the dev server after setting one.

### "Playwright tests fail locally but I haven't touched anything"

Most likely something else is on port 3101 (the Playwright Next dev port — see [web/playwright.config.ts](../../web/playwright.config.ts)) or 8123 (the mock-api port). Kill those processes or override via `PLAYWRIGHT_APP_PORT` / `MOCK_API_PORT` env vars.

---

## Where to ask

- **Build / scope questions** → Akhil (sponsor) directly. Don't guess on HIPAA boundaries or what's in/out of scope.
- **HIPAA classification edge cases** → reread [ADR-001](../02-architecture/adr/001-hipaa-data-classification.md) first. Then ask. If still unsure, default to the more restrictive tier (e.g., classify as Tier B not Tier A when uncertain).
- **CI failures** → check the workflow run output first; the failing step name is usually self-explanatory. If not, paste the relevant lines into the PR thread before pinging.

---

_Last updated: 2026-04-27 · audit ticket T10._
