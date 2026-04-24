# QUICKSTART — run the Phase 0 stack locally

End goal: [http://localhost:3000](http://localhost:3000) shows the 11 seeded sites, fetched live from the FastAPI backend running on :8000, backed by Dockerized Postgres.

---

## ⚠️ Before anything: move the repo out of OneDrive

The scaffold currently lives under OneDrive:

```
c:\Users\akhil\OneDrive - hhamedicine.com\HHA Medicine\HHA_Dashboard_New_Joey\hha-dashboard\
```

**Do not run `uv sync`, `npm install`, or `docker compose up` there.** OneDrive will try to sync `.venv/` and `node_modules/` (thousands of files each) and you'll hit:

- Slow file I/O that makes every test run take 30+ seconds
- Windows file-locking errors on `.pyd` / `.node` files while OneDrive has them open
- Sync conflicts that corrupt installed packages

### One-time move (Windows PowerShell or Git Bash)

```powershell
# Create C:\dev if it doesn't exist
mkdir C:\dev 2>$null

# Copy the scaffold (skips .venv and node_modules if they somehow exist)
robocopy "C:\Users\akhil\OneDrive - hhamedicine.com\HHA Medicine\HHA_Dashboard_New_Joey\hha-dashboard" `
         "C:\dev\hha-dashboard" /E /XD .venv node_modules /XF *.tmp

cd C:\dev\hha-dashboard
```

Planning docs (`DASHBOARD_PLAN.md`, `UI_MOCKUP_v5.html`, `VENTRA_REPLY_DRAFT.md`) stay in OneDrive. Only the **working tree** moves.

Going forward: `git init` + commits happen at `C:\dev\hha-dashboard`. Any future planning updates in OneDrive get copied back over on your own cadence.

---

## Prerequisites

Install once:

- **Docker Desktop** (running) — for Postgres + Mailpit + Adminer
- **Python 3.12+**
- **uv** (Python package manager): `pip install uv` or `winget install astral-sh.uv`
- **Node 20+**
- **(optional) Azure CLI** `az` — not needed for local dev
- **(optional) GitHub CLI** `gh` — when you're ready to push

---

## Step 1 — Local services

```bash
cd C:\dev\hha-dashboard

# Copy env template
cp .env.example .env
# For local dev, the defaults in .env.example work as-is. You only need
# to fill in real Azure/Entra values once you start Phase 2.

# Start Postgres (port 5432), Adminer (8080), Mailpit (8025 UI / 1025 SMTP)
docker compose up -d
docker compose ps
```

You should see 3 containers healthy:

- `hha-postgres` — the database. On first start, it runs [scripts/init-schemas.sql](scripts/init-schemas.sql) to create the 6 schemas + btree_gist extension.
- `hha-adminer` — DB browser at <http://localhost:8080> (system: PostgreSQL, server: `postgres`, user: `hha`, password: `hha`, database: `hha_dashboard`)
- `hha-mailpit` — SMTP catcher at <http://localhost:8025> (you'll use this in Session 3 for email alert testing)

---

## Step 2 — Backend (FastAPI)

```bash
cd C:\dev\hha-dashboard\api

# Install Python deps into .venv (managed by uv)
uv sync

# Apply migrations (creates masters.* tables + GIST exclusion constraint)
uv run alembic upgrade head

# Seed the 11 sites + FL contracts + named MDs from the HTML
uv run python ../scripts/seed_sites.py

# Run tests — should pass, incl. the HIPAA schema classification guard
uv run pytest -v

# Start the API (hot-reload)
uv run uvicorn app.main:app --reload
```

In another terminal:

```bash
# Liveness
curl http://localhost:8000/health
# → {"status":"ok"}

# Readiness (checks DB connectivity)
curl http://localhost:8000/ready
# → {"status":"ready","db":"ok"}

# 11 sites (dev-stub auth: Authorization: Dev admin)
curl -H "Authorization: Dev admin" http://localhost:8000/api/v1/sites
# → JSON array of 7 FL + 4 TX sites
```

OpenAPI UI at <http://localhost:8000/docs>.

---

## Step 3 — Frontend (Next.js 15)

```bash
cd C:\dev\hha-dashboard\web

npm install

# Regenerate typed API client from the running backend (optional — Session 1 ships a hand-typed stub)
# npm run gen-types

npm run dev
```

Open <http://localhost:3000> — you'll see all 11 sites rendered from the live backend, split into FL (7) and TX (4).

---

## Step 4 — Run the tests

```bash
cd C:\dev\hha-dashboard\api

uv run pytest -v
```

All 4 HIPAA schema classification tests should pass:

- `test_no_columns_with_data_class_c` — no Tier C column exists
- `test_every_column_has_data_class` — every column has a `data_class` tag
- `test_no_forbidden_column_names` — no `claim_id`, `patient_*`, `mrn`, etc.
- `test_data_class_values_are_valid` — only A/B/C/D used
- `test_schema_has_expected_tables` — the 6 masters tables are registered

Plus health tests:

- `test_health_ok`
- `test_ready_requires_db`

---

## Common problems

### "docker: permission denied" (WSL / Linux)

On Windows native, Docker Desktop handles this. On WSL, make sure Docker Desktop's WSL integration is enabled for your distro.

### `uv sync` fails with "psycopg requires libpq"

The `psycopg[binary]` dep is supposed to ship libpq bundled. If it fails, try `uv pip install psycopg[binary]` separately, or use `psycopg2-binary` as a swap.

### Alembic can't find the DB

Check `.env` is present at `api/.env` (Alembic reads it via `app.settings`). Also make sure `docker compose ps` shows postgres healthy.

### "relation masters.sites does not exist"

The migration didn't run. `uv run alembic current` — if empty, `uv run alembic upgrade head`.

### Frontend can't reach API

`next.config.ts` proxies `/api/*` → `NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`). If you changed the API port, update `.env`.

### Tests hang

You're probably on Windows and `pytest-asyncio` needs `asyncio_mode = "auto"` — already set in `pyproject.toml`. If it still hangs, run `uv run pytest -v --timeout=30` to force timeouts.

---

## What's next (Session 2)

Once you've verified the stack works end-to-end, come back for Session 2:

- Real Entra ID auth via MSAL (web + api)
- `audit_log` table + SQLAlchemy event listener (before any user mutations)
- Admin pages for sites / contracts / physicians / comp_agreements / credentials
- Entry pages for daily census (Crystal), monthly finance (Sandy / Maribel)

Until then, the dev-stub `Authorization: Dev <role>` header is the only auth — **never use this in prod, never expose the API publicly until MSAL is wired**.
