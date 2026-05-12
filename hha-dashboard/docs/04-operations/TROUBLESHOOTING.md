# Troubleshooting

> **For engineers + on-call.** Common dev and prod issues, with fixes. Read [RUNBOOK.md](RUNBOOK.md) for high-level incident playbook structure; this doc is the symptom → fix lookup.
>
> Last updated 2026-05-11.

## How to use this doc

1. Search by symptom (Ctrl+F the error message).
2. Each entry has: symptom, why it happens, how to fix, how to prevent.
3. If your issue isn't here, file a new entry after you fix it.

---

## Local dev

### "ModuleNotFoundError: No module named 'app'" when running api

**Symptom:** `uv run uvicorn app.main:app --reload` fails with import error.

**Why:** Running from the wrong directory, or `.venv` not activated.

**Fix:**

```bash
cd hha-dashboard/api  # MUST be here, not the repo root
uv sync                # creates .venv with all deps
uv run uvicorn app.main:app --reload
```

**Prevent:** `cd api` is the first line of every Python command in the repo.

---

### "psycopg.OperationalError: could not connect to server" — local Postgres

**Symptom:** API starts but every DB query fails.

**Why:** Local Postgres isn't running.

**Fix:**

```bash
docker compose up -d postgres  # or `docker compose up -d` for full stack
docker compose ps              # confirm postgres is "Up"
```

If Postgres won't start: check for port conflict (`netstat -ano | findstr 5432` on Windows). Adjust `docker-compose.yml` port mapping if needed.

---

### "alembic.util.exc.CommandError: Can't locate revision identified by"

**Symptom:** `alembic upgrade head` fails after pulling new migrations.

**Why:** Migration history on your local DB doesn't match the migration files in git.

**Fix:** Wipe and re-apply.

```bash
docker compose down -v   # destroys the local DB volume
docker compose up -d
cd hha-dashboard/api
uv run alembic upgrade head
python ../scripts/seed_sites.py
```

**WARNING:** This destroys local data. Never do this in prod.

---

### Frontend says "Cannot find module '@/lib/api-types'"

**Symptom:** Next.js build fails on missing types.

**Why:** TypeScript types not generated from API's OpenAPI spec.

**Fix:**

```bash
# In one terminal:
cd hha-dashboard/api
uv run uvicorn app.main:app --reload   # API must be running

# In another terminal:
cd hha-dashboard/web
npm run gen-types
```

**Prevent:** `npm run gen-types` is part of `npm run dev` indirectly via predev script (or should be added).

---

### "Type error: 'X' is missing the following properties"

**Symptom:** TypeScript compile errors after pulling API changes.

**Why:** API schema changed but local types are stale.

**Fix:** regenerate types as above.

---

### Docker says "no space left on device"

**Symptom:** Docker compose up fails.

**Why:** Docker volumes accumulated over time.

**Fix:**

```bash
docker system prune -a --volumes
```

This nukes all stopped containers, unused images, networks, and volumes. Then re-run `docker compose up`.

---

### Node says "node_modules permission denied"

**Symptom:** `npm install` fails on Windows.

**Why:** OneDrive sync conflict — file is locked while OneDrive is uploading.

**Fix:**

1. Right-click the project folder → "Always keep on this device" (in OneDrive)
2. If still failing: Pause OneDrive sync via system tray icon
3. Delete `node_modules` and re-`npm install`

**Prevent:** Documented in [QUICKSTART.md](../../QUICKSTART.md). Consider moving the repo out of OneDrive entirely.

---

## Azure / production

### `/ready` returns 500

**Symptom:** API health endpoint fails after deploy.

**Why:** Common causes:

1. DB connection string wrong format (asyncpg vs psycopg URL syntax)
2. DB firewall doesn't allow App Service
3. Migrations not run
4. Sites not seeded

**Diagnose:**

```bash
# Tail logs
az webapp log tail -g rg-hha-dashboard-prod -n app-hha-api-prod | grep -iE "error|except|ready"
```

**Fix by symptom:**

| Log message | Fix |
|---|---|
| `TypeError: connect() got an unexpected keyword argument 'sslmode'` | DATABASE_URL has `?sslmode=require` but asyncpg wants `?ssl=require`. Set both env vars correctly (see CLAUDE.md § Prod deploy state). |
| `psycopg.errors.ConnectionTimeout` | Postgres firewall — open AllowAllAzureServices or VNet. |
| `relation "masters.sites" does not exist` | Alembic didn't run. From a runner with DB access: `cd api && uv run alembic upgrade head` (or use `seed-prod.yml` workflow which now runs alembic first). |
| `/ready` returns 503 with `sites: missing` | Run `python scripts/seed_sites.py` (or the `seed-prod.yml` workflow). |

---

### App Service won't start, container exits immediately

**Symptom:** App Service shows "Stopped" or restarts in a loop.

**Why:** Common causes:

1. Missing required env var
2. Startup script error
3. Python deps not installed (Oryx build failed)

**Diagnose:**

```bash
# Inspect startup logs
az webapp log download -g rg-hha-dashboard-prod -n app-hha-api-prod
unzip webapp_logs.zip
cat LogFiles/Application/*.log | tail -100
```

**Fix by symptom:**

| Log message | Fix |
|---|---|
| `RuntimeError: Refusing to start: ENV='prod' requires WEB_ORIGIN` | Set WEB_ORIGIN env var on api app: `az webapp config appsettings set -g rg-hha-dashboard-prod -n app-hha-api-prod --settings 'WEB_ORIGIN=https://app-hha-web-prod.azurewebsites.net'` |
| `ModuleNotFoundError: No module named 'fastapi'` | Oryx build didn't run. Confirm `SCM_DO_BUILD_DURING_DEPLOYMENT=true` and `ENABLE_ORYX_BUILD=true` on the app. Redeploy. |
| `Cannot find module '../server/require-hook'` (web) | Next.js 15 `.bin/next` symlink issue. Change startup command to `node node_modules/next/dist/bin/next start`. |
| `SESSION_SECRET env var is required` (web) | Set a 32-byte base64 secret as `SESSION_SECRET` on `app-hha-web-prod`. See SECURITY_INCIDENT_PLAYBOOK § Rotate session secret for the exact command. |

---

### Key Vault references won't resolve

**Symptom:** App Service env vars show `@Microsoft.KeyVault(...)` literally instead of the resolved secret value.

**Why:** Common causes:

1. App Service Managed Identity not granted KV Secrets User role
2. KV is in private-endpoint mode and App Service isn't in the VNet
3. Role assignment is brand-new and hasn't propagated yet

**Fix:**

```bash
# Verify the App Service has a system-assigned MI
az webapp identity show -g rg-hha-dashboard-prod -n app-hha-api-prod

# Get the MI's principal ID and check KV role assignments
PRINCIPAL_ID=$(az webapp identity show -g rg-hha-dashboard-prod -n app-hha-api-prod --query principalId -o tsv)
az role assignment list --assignee $PRINCIPAL_ID --scope $(az keyvault show -n kv-hha-prod2 --query id -o tsv)

# If missing, grant
az role assignment create --assignee $PRINCIPAL_ID \
  --role "Key Vault Secrets User" \
  --scope $(az keyvault show -n kv-hha-prod2 --query id -o tsv)

# Wait 5 min for propagation, then restart the app
az webapp restart -g rg-hha-dashboard-prod -n app-hha-api-prod
```

**Note from the deploy push (May 2026):** Currently `DATABASE_URL` and `DATABASE_URL_SYNC` on the API are set as **literal** strings (not KV references) because of an earlier debugging detour. To migrate back to KV references, follow the "Re-enable KV references" item in [ROADMAP.md](../01-leadership/ROADMAP.md) § Phase 3.

---

### Postgres connection pool exhausted

**Symptom:** API endpoints time out or return 500; logs show `QueuePool limit of size N overflow N reached`.

**Why:** Too many concurrent requests or leaked connections.

**Fix:**

1. Immediate: `az webapp restart -g rg-hha-dashboard-prod -n app-hha-api-prod`
2. Diagnose: check Application Insights for which endpoints are slow
3. Investigate: any new code that doesn't use `async with session:` properly?
4. Mitigate: bump pool size in `app/db.py` if legit load growth (rare at our scale)

**Prevent:** All DB operations use `async with AsyncSession() as session:` (or the FastAPI Depends pattern). No raw session creation.

---

### Deploy via GitHub Actions fails at "Azure login (OIDC)"

**Symptom:** `deploy-prod-code.yml` workflow fails at the Azure Login step.

**Why:** Federated identity credential mismatch or missing.

**Fix:**

```bash
# Confirm the federated credential exists for environment=prod
APP_ID=$(az ad app list --display-name 'github-deploy-hha-dashboard' --query "[0].appId" -o tsv)
OBJECT_ID=$(az ad app list --display-name 'github-deploy-hha-dashboard' --query "[0].id" -o tsv)
az rest --method GET --uri "https://graph.microsoft.com/v1.0/applications/$OBJECT_ID/federatedIdentityCredentials"

# Expect a credential with subject = "repo:DandaAkhilReddy/hhadashboard:environment:prod"
```

If missing or wrong subject, re-create via `scripts/azure_create_missing.sh` (which now uses `az rest` directly because `az ad app federated-credential create` has bugs on Windows).

---

### `seed-prod.yml` workflow fails

**Symptom:** Workflow ran but seed step failed.

**Common errors:**

| Error | Fix |
|---|---|
| `extension "btree_gist" is not allow-listed` | Allow-list it: `az postgres flexible-server parameter set -g rg-hha-dashboard-prod -s psql-hha-prod -n azure.extensions -v BTREE_GIST` then restart server. |
| `connection to server timed out` | Postgres firewall — confirm runner IP was added by the workflow's "Open Postgres firewall to runner" step. |
| `relation "masters.sites" does not exist` | Alembic migrations weren't run. The workflow now runs `alembic upgrade head` before seed steps (since 2026-05-04). |

---

### Web app shows "dev mode no sign-in required" banner in prod

**Symptom:** Production web app skips Entra sign-in and shows a dev-mode banner.

**Why:** `NEXT_PUBLIC_AUTH_MODE` is not set to `prod` at build time.

**Fix:** Rebuild the web app with the env var set.

```bash
# In deploy-prod-code.yml the env is already set as:
#   NEXT_PUBLIC_API_BASE_URL: https://app-hha-api-prod.azurewebsites.net
# Add this line in the same env block:
#   NEXT_PUBLIC_AUTH_MODE: prod
```

Or set `NEXT_PUBLIC_AUTH_MODE` as a repo Variable and reference it in the workflow.

`NEXT_PUBLIC_*` env vars are baked into the Next.js bundle at build time; they cannot be changed at runtime.

---

## CI / GitHub Actions

### `tests/test_schema_classification.py` fails

**Symptom:** PR check fails with "column X has no data_class" or "column X has data_class=C".

**Why:** A new column was added to a SQLAlchemy model without proper classification.

**Fix:** Add `info={"data_class": "A"}` (or B) to the `mapped_column(...)` call:

```python
my_field: Mapped[int] = mapped_column(
    Integer, nullable=False,
    info={"data_class": "A"}
)
```

Never use `data_class="C"` without a sponsor decision. Never use `data_class="D"` at all.

---

### Pre-commit hook blocks commit with "forbidden column name"

**Symptom:** Local commit fails with a hook message about forbidden column.

**Why:** A migration or model has a column matching `patient_*`, `mrn`, `ssn`, etc.

**Fix:** Rename the column. If you genuinely need that name, the design needs to change — surface to architecture review.

---

### `npm run build` fails with "type errors"

**Symptom:** Web build fails in CI but works locally.

**Why:** Type drift between API and web (regenerated types on one side, not the other).

**Fix:**

```bash
cd hha-dashboard/web
npm run gen-types       # regenerate from running API
npm run lint
npm run build
```

Commit the regenerated `lib/api-types.ts` if it changed.

---

## Bicep / IaC

### `az deployment group create` fails with "SKU not supported"

**Symptom:** Deploy errors out at App Service Plan or Postgres provision.

**Why:** Subscription is offer-restricted and doesn't support the requested SKU (we hit this on the initial deploy with GP_Standard Postgres).

**Fix:** Downgrade to supported SKUs in `infra/env/prod.bicepparam`:

- Postgres: `Burstable_B1ms` instead of `GP_Standard_D2ds_v5`
- App Service Plan: `B1` instead of `P1v3`
- ACR: `Basic` instead of `Standard`

Document the downgrade as a known limitation; revisit when subscription gets upgraded.

---

### `Key Vault soft-delete reservation`

**Symptom:** Bicep deploy fails with "vault name already reserved (soft-deleted)".

**Why:** A previously-deleted vault with the same name is in soft-delete state (90-day reservation).

**Fix:**

1. List soft-deleted vaults: `az keyvault list-deleted`
2. If you want to recover: `az keyvault recover --name <name>`
3. If you want to actually delete: `az keyvault purge --name <name>` (requires purge protection to be OFF)
4. If neither: change the vault name (we did this — `kv-hha-prod` → `kv-hha-prod2`)

`enable_kv_purge_protection=false` in `infra/env/prod.bicepparam` is the current state to avoid this trap; re-enable after Phase 3 stabilizes.

---

## Application Insights / observability

### "I see latency spikes but no obvious cause"

**Fix process:**

1. Open Application Insights → Performance
2. Filter to the slow endpoint
3. Look at the "Dependencies" tab — is the slow time in Postgres, Key Vault, or our code?
4. If Postgres: check the operation type — slow SELECT? slow INSERT? Lock contention?
5. If Key Vault: an MI propagation delay or KV throttling
6. If our code: open the trace, drill into the slowest span

### "Logs aren't showing up"

**Why:** Three common causes:

1. App Insights connection string not set on the App Service
2. OpenTelemetry exporter misconfigured
3. Log Analytics workspace retention exceeded free tier

**Fix:**

```bash
# Verify connection string
az webapp config appsettings list -g rg-hha-dashboard-prod -n app-hha-api-prod --query "[?name=='APPLICATIONINSIGHTS_CONNECTION_STRING']"
```

If empty, set it from the App Insights resource:

```bash
APP_INSIGHTS_CONN=$(az monitor app-insights component show -g rg-hha-dashboard-prod -a appi-hha-prod --query connectionString -o tsv)
az webapp config appsettings set -g rg-hha-dashboard-prod -n app-hha-api-prod \
  --settings "APPLICATIONINSIGHTS_CONNECTION_STRING=$APP_INSIGHTS_CONN"
```

---

## Common WSL/Windows gotchas (Akhil's environment)

### `az` from WSL bash doesn't return JSON properly

**Why:** `az.cmd` (Windows binary) called from WSL bash sometimes has stdout buffering and JMESPath quoting issues.

**Fix:**

1. Use tempfiles instead of pipes: `az ... -o json > /tmp/result.json && jq ... /tmp/result.json`
2. For JSON request bodies, write to a file in `$PWD` (Windows-visible) and pass with `wslpath -w`

### `gh` CLI works in cmd but not WSL bash

**Why:** Two different installs; PATH disagreement.

**Fix:** Use `gh` from PowerShell or cmd for repo operations; use `az` from WSL bash or PowerShell.

### CRLF line ending drift

**Symptom:** Diffs show all-lines-changed even though only one was edited.

**Why:** Git's `core.autocrlf` is misconfigured on Windows.

**Fix:**

```bash
git config --global core.autocrlf input  # checkout LF, commit LF
git config --global core.eol lf
```

For existing CRLF-corrupted files: `dos2unix <file>` then re-stage.

---

## Recovery / disaster

For full disaster scenarios (data loss, regional outage, suspected breach), see [SECURITY_INCIDENT_PLAYBOOK.md](SECURITY_INCIDENT_PLAYBOOK.md) and [RUNBOOK.md](RUNBOOK.md) § Backup & restore.

---

**Next read:** [SECURITY_INCIDENT_PLAYBOOK.md](SECURITY_INCIDENT_PLAYBOOK.md) — when an issue is more serious than "something broke."
