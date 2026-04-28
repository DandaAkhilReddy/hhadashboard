# RUNBOOK

This is the document the on-call reads at 2 a.m. Keep it current.

> **First-time reader:** start with [§ A. Quick orientation](#a-quick-orientation), then [§ B. First deploy procedure](#b-first-deploy-procedure-one-time-per-environment).
> **Incident reader:** jump to [§ D. Incident playbooks](#d-incident-playbooks).

---

## A. Quick orientation

### What this system is

A Next.js + FastAPI + PostgreSQL dashboard hosted entirely in **one Azure subscription** under HHA's Microsoft 365 tenant. Two App Services (web, api), one Postgres Flex Server, six cron jobs in Container Apps Jobs, plus Storage / KV / ACS Email / App Insights.

### What it talks to

- **Entra ID** (HHA tenant) — auth for the dashboard.
- **Ventra** (RCM provider, FL only) — monthly finance aggregates, delivery channel TBD.
- **Paycom** (HR/payroll) — workforce data, API access pending.
- **Hospitals (11)** — no direct integration; we mirror their feeds via the providers above.

### What it doesn't talk to

- No public API. No third-party SaaS in the data path. No clinical EHR. **No claim-level data ever lands in our DB** (per [ADR-001](adr/001-hipaa-data-classification.md)).

### Top-level health

- API health: `https://app-hha-api-{env}.azurewebsites.net/health` → `{"status":"ok"}`
- API readiness: `…/ready` → 200 with check breakdown OR 503 with which check failed
- Web health: `https://app-hha-web-{env}.azurewebsites.net/` should render the Overview board

### Where things live in Azure

```
rg-hha-dashboard-{env}/
├── psql-hha-{env}                    Postgres Flex Server
├── plan-hha-{env}                    App Service Plan
├── app-hha-web-{env}                 Web App Service (Next.js)
├── app-hha-api-{env}                 API App Service (FastAPI)
├── kv-hha-{env}                      Key Vault (private endpoint in prod)
├── sthha{env}<unique>                Storage Account (uploads/, backups/)
├── log-hha-{env} + appi-hha-{env}    Log Analytics + App Insights
├── acs-hha-{env}                     Azure Communication Services (email)
├── cae-{env}                         Container Apps Environment
├── job-pg-backup-{env}               Cron: nightly pg_dump
├── job-alert-digest-{env}            Cron: weekday morning digest
├── job-cred-scan-{env}               Cron: daily credential expiry
└── vnet-hha-{env}                    VNet (prod only)
```

---

## B. First deploy procedure (one-time per environment)

Required external dependencies (must be done by humans, not from your laptop):

- [ ] Azure subscription `hha-production` provisioned under HHA's M365 tenant
- [ ] Operator has Owner on the subscription, or scoped Contributor + RBAC admin on the resource group
- [ ] Two Entra app registrations: `hha-dashboard-web-{env}` and `hha-dashboard-api-{env}` ([docs/ENTRA_SETUP.md](ENTRA_SETUP.md))
- [ ] Seven security groups created and populated ([ADR-002](adr/002-rbac-model.md))
- [ ] Ventra and Microsoft BAA confirmations on file

When those are done, deploy in three phases:

### Phase 1 — Provision infrastructure

```bash
ENV=dev   # or prod
RG=rg-hha-dashboard-${ENV}

az login
az account set -s <hha-subscription-id>
az group create -n $RG -l eastus2

az deployment group create \
  -g $RG \
  -f infra/main.bicep \
  -p infra/env/${ENV}.bicepparam \
  -p postgres_admin_password='__placeholder__' \
  -p deployer_workstation_ip=$(curl -s ifconfig.me) \
  -p azure_tenant_id_for_kv=$(az account show --query tenantId -o tsv)
```

Outputs to copy down: `web_url`, `api_url`, `postgres_host`, `storage_account_name`, the two App Service principal IDs.

### Phase 2 — Seed secrets

```bash
ENV=dev bash infra/bootstrap.sh
```

Generates a 24-byte postgres password, writes it to KV as `postgres-admin-password`, plus `database-url` and `database-url-sync` connection-string secrets the App Services reference. Restarts both App Services so KV references resolve.

**Idempotent.** Re-run with the same vault is a no-op.

#### Phase 2.5 — Seed `SESSION_SECRET` (web cookie encryption)

The web App Service AES-GCM-encrypts the `hha_session` cookie with a 32-byte
key. **Without this set, the web process refuses to boot** (per
`web/instrumentation.ts`). Audit ticket T4.

```bash
ENV=dev
KV_NAME=kv-hha-${ENV}
WEB_APP=app-hha-web-${ENV}
RG=rg-hha-dashboard-${ENV}

# Generate + write to KV
az keyvault secret set \
  --vault-name $KV_NAME \
  --name session-secret \
  --value "$(openssl rand -base64 32)" \
  --output none

# Wire it into the web App Service as a KV reference
az webapp config appsettings set \
  -g $RG -n $WEB_APP \
  --settings "SESSION_SECRET=@Microsoft.KeyVault(VaultName=${KV_NAME};SecretName=session-secret)" \
  --output none

# Restart so the new app_setting resolves
az webapp restart -g $RG -n $WEB_APP
```

**Rotating** invalidates every active session (every user re-signs-in next
visit). Treat as a credential — rotate after a known compromise, on a
quarterly schedule otherwise.

#### Phase 2.6 — Build & push cron job container images

Container Apps Jobs created by `containerjobs.bicep` reference images at
`acrhha{env}.azurecr.io/<image>:<tag>`. **First deploy uses the placeholder
default** (Microsoft sample image) — every cron run will be a no-op until
real images are pushed. Audit ticket T5.

```bash
# From a workstation with `gh` authenticated:
gh workflow run build-job-images.yml -f environment=dev
gh run watch  # or refresh GitHub Actions UI

# Verify the 3 images landed:
az acr repository list -n acrhha${ENV}
# Expected: pg-backup, alert-digest, cred-scan
```

The workflow:
- Logs into Azure via the same OIDC federated identity used by
  `deploy-{env}.yml` (federated subject `:environment:${ENV}`).
- Builds `pg_backup`, `alert_digest`, `cred_scan` Dockerfiles with both
  the commit-SHA tag and `:latest`.
- Pushes via `az acr login` (no admin user, no static credentials).
- Verifies each tag landed in ACR before exiting.

After the first successful push, **switch the bicepparam image params off
the placeholder** by adding to `infra/env/${ENV}.bicepparam`:

```bicep
param pg_backup_image    = 'acrhha${ENV}.azurecr.io/pg-backup:latest'
param alert_digest_image = 'acrhha${ENV}.azurecr.io/alert-digest:latest'
param cred_scan_image    = 'acrhha${ENV}.azurecr.io/cred-scan:latest'
```

Then re-run `deploy-${ENV}.yml`. Container Apps Jobs auto-pull `:latest`
on next scheduled run; for an immediate refresh, manually trigger the
job via the Azure portal.

**Image versioning:** for production releases, prefer SHA tags over
`:latest` (reproducible, traceable). The workflow accepts an
`image_tag` input for semver tagging (`v1.2.3`, `2026-04-27` etc.).

### Phase 3 — Seed application data

```bash
# Sites + named MDs + FL contracts (one-time)
cd hha-dashboard/api
uv run python ../scripts/seed_sites.py

# Census portal credential (one-time per env, hand the password to ops)
bash infra/census_seed.sh \
  --email crystal@hhamedicine.com \
  --rotate-random

# Alert subscribers (run once per recipient)
bash infra/seed_alert_subscriptions.sh \
  --role exec --email cfo@hhamedicine.com --frequency daily
# ...repeat for CEO, owner_*, etc.
```

### Phase 4 — Smoke test

```bash
curl -s https://app-hha-api-${ENV}.azurewebsites.net/health   # {"status":"ok"}
curl -s https://app-hha-api-${ENV}.azurewebsites.net/ready    # 200 with checks=ok
```

Then sign in via the dashboard, confirm Operations renders 11 sites, and you're up. **Document every surprise in `docs/FIRST_DEPLOY_NOTES.md`** — those become the next iteration's RUNBOOK additions.

### Phase 5 — Lock the backups WORM policy

After ~3 successful nightlies, follow the procedure in [ADR-004 § Part 3](adr/004-backup-and-disaster-recovery.md#part-3--worm-immutability-lock).

---

## C. Routine operations

### Add or remove a dashboard user

- **Add:** Entra portal → corresponding security group ([ADR-002](adr/002-rbac-model.md)) → add member. Effective on next sign-in.
- **Remove:** same group → remove member. JWTs cached up to 1h; for immediate revocation also restart the api App Service: `az webapp restart -n app-hha-api-${ENV} -g $RG`.
- **Promote to comp_viewer:** add to `HHA-Dashboard-CompViewer`. CEO and CFO only by policy.

### Rotate the census portal credential

```bash
bash infra/census_seed.sh \
  --email <new-or-existing-email> \
  --rotate-random
```

Prints the new password once. Hand it to ops securely (1Password, or in-person). Existing sessions are immediately invalidated by the single-session-token rotation.

### Rotate the postgres admin password

```bash
bash infra/bootstrap.sh   # detects existing secret, leaves it alone
# OR
POSTGRES_PASSWORD='<new-rotated-pw>' bash infra/bootstrap.sh   # forces overwrite
```

bootstrap.sh updates the KV secrets and restarts the App Services; app_settings KV references resolve to the new value on next request.

For the actual Postgres user, also reset the server-side password:

```bash
az postgres flexible-server update \
  -g $RG -n psql-hha-${ENV} \
  --admin-password '<new-rotated-pw>'
```

Order: change in KV first, then change on the server (app reads KV). Reverse order risks the app trying the new password against the old server. Kept tight either way because of `pool_pre_ping=true` (per ADR-002).

### Run the restore drill

```bash
ENV=prod bash scripts/restore_drill.sh
```

Quarterly minimum. Also after every schema migration touching audited tables. See [ADR-004 § Part 4](adr/004-backup-and-disaster-recovery.md#part-4--restore-drill-the-proof).

### Apply a new migration in prod

1. Branch + write migration + add tests + open PR.
2. CI green, peer-review, merge to main.
3. From a workstation with `az` access:

```bash
ENV=prod
RG=rg-hha-dashboard-${ENV}
APP=app-hha-api-${ENV}
DBURL=$(az keyvault secret show --vault-name kv-hha-${ENV} -n database-url-sync --query value -o tsv)

# Run alembic from your machine; the prod App Service has no shell.
cd hha-dashboard/api
DATABASE_URL_SYNC="$DBURL" uv run alembic upgrade head

# Verify
DATABASE_URL_SYNC="$DBURL" uv run alembic current
```

After migration, restart the api App Service so the schema check in `/ready` re-runs:

```bash
az webapp restart -n $APP -g $RG
curl -s https://$APP.azurewebsites.net/ready | jq
```

If `/ready` returns `checks.schema = mismatch`, you forgot to deploy the new code first. Fix forward.

### Trigger a cron job manually

```bash
ENV=prod
JOB=job-pg-backup-${ENV}   # or job-alert-digest-${ENV}, etc.
RG=rg-hha-dashboard-${ENV}

az containerapp job start -n $JOB -g $RG
az containerapp job execution list -n $JOB -g $RG --query '[0]'
az containerapp job logs show -n $JOB -g $RG --container <container-name> --execution <execution-name>
```

---

## D. Incident playbooks

### D.1 "Users can't sign in"

**Symptoms:** sign-in redirect loops, or users land on `/auth/sign-in` repeatedly, or "Not authenticated" errors.

**Triage:**

1. Hit `/health` and `/ready` on the api. If `/ready` is 503, jump to **D.5**.
2. Check Entra: is the user in the right security group?
3. Check `WEB_ORIGIN` env var on the api App Service — if missing, prod startup will have refused to start (per Operation B hardening). `az webapp log tail -n $API -g $RG` shows the lifespan error.
4. Check the `Authorization` header in App Insights: is it arriving? Cookie set? If no header, the cookie isn't being decrypted — `SESSION_SECRET` env may have rotated.
5. JWKS fetch failure: api logs show "Failed to fetch JWKS from {tenant}". Network rule on api App Service? VNet integration broken?

**Fix:**

- If group membership wrong → fix in Entra, wait ≤1h or restart api.
- If env var wrong → fix in App Service Configuration → restart app.
- If JWKS unreachable → `az webapp vnet-integration list -n $API -g $RG` to verify integration; `az network nsg show` on the app subnet for outbound rules.

### D.2 "Census portal login fails"

**Symptoms:** Crystal can't sign into `/census/login` even with the right password.

**Triage:**

1. Did the credential rotate? Check Slack / 1Password.
2. Account locked? Query `auth.census_credentials`:

```sql
SELECT email, failed_attempts, locked_until FROM auth.census_credentials;
```

`locked_until > now()` means lockout in effect (10 fails / 15 min lock per [ADR-002](adr/002-rbac-model.md)).

**Fix:**

- Locked: rotate the password (`bash infra/census_seed.sh --rotate-random`) — that resets `failed_attempts` and `locked_until`.
- Forgot password: same command.
- DB unreachable from api → see **D.3**.

### D.3 "API returns 500s on every request"

**Symptoms:** `/health` is 200, `/ready` is 503, every API call returns 500.

**First step — pin a correlation id.** Per audit ticket T6, every error
response carries `correlation_id` in the JSON body AND `X-Correlation-Id`
in the response header. Grab one from a real failing request, then:

```kusto
// Application Insights — Logs blade
traces
| where customDimensions.request_id == "<the correlation id>"
| order by timestamp asc
```

That one query gives you the full request path: middleware logs, DB
queries (auto-instrumented via SQLAlchemy), the exception, the response.
This is the App Insights workflow Phase 2 unlocked. If `customDimensions`
is empty, the api is running with `APPLICATIONINSIGHTS_CONNECTION_STRING`
unset — fall back to the next step.

**Fallback — App Service stdout:**

```bash
az webapp log tail -n $API -g $RG | head -50
```

Look at structlog output. Every record carries `request_id=<uuid>`
(audit T6); grep that to filter to a single request. Five common causes:

| Symptom in logs | Cause | Fix |
|---|---|---|
| `connection refused` to postgres | Postgres firewall blocks the api outbound IP, or VNet integration broken | Add the api's outbound IPs to Postgres firewall (see infra/README.md `for ip in ... az postgres flexible-server firewall-rule create`). Or fix VNet config. |
| `relation "..." does not exist` | Schema not migrated | `alembic upgrade head` from your workstation against the prod DB |
| `KeyVault reference … did not resolve` | KV access policy or RBAC misconfigured | `az role assignment list --scope $(az keyvault show -n $KV --query id -o tsv)` — ensure App Service MI has `Key Vault Secrets User` |
| `DATABASE_URL_SYNC not configured` (cron) | App settings missing | Re-run bootstrap.sh |
| Random `RuntimeError: Refusing to start` | Missing `WEB_ORIGIN` or `entra_configured == False` in non-dev | Fix env vars, restart |
| `telemetry.disabled` at startup | `APPLICATIONINSIGHTS_CONNECTION_STRING` was not threaded through | Confirm `enable_monitor=true` in bicepparam; redeploy main.bicep; restart api |

### D.4 "Alerts not firing / no email arriving"

**Symptoms:** Variance is real (FL collections below target) but no email arrived.

**Triage:**

1. Was the cron scheduled to run? `az containerapp job execution list -n job-alert-digest-prod -g $RG`. Should have a run for today.
2. If run is `Succeeded`, check `alerts.alert_log` for today's date:

```sql
SELECT * FROM alerts.alert_log
WHERE target_date = current_date - interval '1 day'
ORDER BY sent_at DESC;
```

3. If empty: maybe no subscribers? Check `alerts.alert_subscriptions`. Or the variance engine returned empty (real or threshold misconfigured).
4. If has rows but recipient claims no email: check ACS quota in Azure Portal. Check `acs_message_id` in the log — give it to ACS support.

**Fix:**

- No subscriber rows → run `bash infra/seed_alert_subscriptions.sh ...`.
- Empty variance → check whether actual data was loaded for the target date (look at `entries.monthly_finance_manual`, etc.).
- ACS quota exceeded → request quota increase or wait for next billing cycle.
- Need to "force" a re-send: `DELETE FROM alerts.alert_log WHERE target_date = '...' AND alert_id = '...'` then trigger the cron manually.

### D.5 "/ready returns 503"

The richer `/ready` (per Operation B) returns one of:

```json
{"status":"not_ready","checks":{"db":"error: ConnectionError"}}
{"status":"not_ready","checks":{"db":"ok","schema":"mismatch (got='0008' expected='0010')"}}
{"status":"not_ready","checks":{"db":"ok","schema":"ok","audit_trigger":"missing"}}
{"status":"not_ready","checks":{"db":"ok","schema":"ok","audit_trigger":"ok","sites":"empty"}}
```

| Check | Meaning | Fix |
|---|---|---|
| `db: error` | Postgres unreachable | See **D.3** |
| `schema: mismatch` | Code expects newer migration than DB has | `alembic upgrade head` — see § C |
| `audit_trigger: missing` | Trigger function dropped or migration didn't apply cleanly | Re-run migration 0007 / inspect `\df audit.*` in psql |
| `sites: empty` | DB freshly provisioned but `seed_sites.py` not run | Run the seed script |

### D.6 "Backup didn't run last night"

**Symptoms:** No new blob in `backups/` for the expected date.

**Triage:**

```bash
az containerapp job execution list -n job-pg-backup-prod -g $RG --query '[].{name:name, status:properties.status, start:properties.startTime}'
```

If status is `Failed`:

```bash
az containerapp job logs show -n job-pg-backup-prod -g $RG --container pg-backup --execution <name>
```

Common failures: `pg_dump exited 1: connection refused` (firewall / network), `Authorization failed` (MI doesn't have Storage Blob Data Contributor — fix via rbac.bicep follow-up), `disk full` (bump cpu/memory in containerjobs.bicep).

**Manual run:**

```bash
az containerapp job start -n job-pg-backup-prod -g $RG
```

Watch execution. If it succeeds, you're back to normal — Azure Postgres Flex's managed backups still cover the missed window for restore.

If it keeps failing past 48h, you've lost a day of the off-Azure escrow but the managed backup is intact (per [ADR-004](adr/004-backup-and-disaster-recovery.md)). Treat as P2, not P1.

### D.7 "Audit log has rows with `__system__`"

**Symptoms:**

```sql
SELECT count(*) FROM audit.audit_log
WHERE changed_by_upn = '__system__'
  AND table_schema IN ('masters', 'entries')
  AND changed_at > now() - interval '1 hour';
```

…returns nonzero. Per [ADR-003](adr/003-audit-chain.md), this means a mutation happened without the middleware setting the UPN ContextVar.

**Possible causes:**

- A direct `psql` mutation by an admin (legitimate but worth a paper trail).
- Middleware bypass — investigate as a security event.
- A cron job that forgot to call `set_current_upn()` at startup (look for the timing — cron jobs run at fixed hours).

**Action:** check App Insights traces for that timestamp. If unexplained, rotate KV secrets and admin Postgres password, post-mortem.

---

## E. What's NOT in this runbook (yet)

- Failover to a secondary region — Postgres geo-replication exists in prod; failover never exercised. Add to next quarter's drill.
- Migration to a new Azure subscription — possible but unscripted. Call Azure support if needed.
- "We forgot the DB password and it's not in KV" — Postgres has a password reset on the server; see § C.
- Breach response — covered by HHA's HIPAA incident-response policy, not this doc. Notify the Privacy Officer immediately.
- Cost overrun — App Insights ingestion is the most likely runaway. Cap via Log Analytics daily quota in `monitor.bicep`.

## G. Post-deploy verification (first 24 hours)

> See also: [docs/PHASE_1_CENSUS_PORTAL.md](PHASE_1_CENSUS_PORTAL.md), [scripts/smoke_deploy.sh](../scripts/smoke_deploy.sh).

This is the checklist an operator runs after a fresh prod deploy completes. Work through it top-to-bottom. Each subsection is roughly ordered by "how fast will this blow up if it's wrong."

---

### G.1 Smoke tests

Run the smoke suite against the prod URL immediately after the deploy workflow turns green:

```bash
DEPLOY_URL=https://app-hha-api-prod.azurewebsites.net \
WEB_URL=https://app-hha-web-prod.azurewebsites.net \
  bash scripts/smoke_deploy.sh
```

All green means:

- Exit code 0 from the script
- `/health` → `{"status":"ok"}` (HTTP 200)
- `/ready` → HTTP 200 with `checks.db=ok`, `checks.schema=ok`, `checks.audit_trigger=ok`, `checks.sites=ok`
- Census login round-trip returns HTTP 200 (not 401, not 500)
- At least one row written to `entries.daily_entries` and confirmed readable

If any check fails, the script exits non-zero and prints which step failed. Do not declare the deploy successful until this is clean.

---

### G.2 App Insights — first hour watch

Open **Azure Portal → appi-hha-prod → Logs** and run the queries below. Keep this tab open for the first hour.

**Any ERRORs or CRITICALs?**

```kusto
traces
| where severityLevel >= 3
| order by timestamp desc
| take 50
```

Zero rows is the target. One or two `WARNING` rows (severityLevel 2) at startup (e.g., config resolution) are acceptable if they stop recurring.

**5xx rate above 1%?**

```kusto
requests
| where timestamp > ago(1h)
| summarize
    total = count(),
    errors = countif(resultCode >= 500)
| extend error_pct = round(100.0 * errors / total, 2)
```

`error_pct` must be < 1. If it spikes, pull the correlation IDs from that same window and follow **D.3**.

**Postgres p99 latency and failures:**

```kusto
dependencies
| where timestamp > ago(1h)
| where type == "SQL" or target has "postgres"
| summarize
    p99_ms = percentile(duration, 99),
    failures = countif(success == false),
    calls = count()
| project p99_ms, failures, calls
```

| Threshold | Action |
|---|---|
| `p99_ms` < 300 ms | Normal |
| `p99_ms` 300–800 ms | Investigate (index missing? connection pool exhausted?) |
| `p99_ms` > 800 ms | Page the operator — likely pool saturation or Postgres vCPU throttle |
| `failures` > 0 | Always investigate — Postgres should not error in steady state |

**Census lockout events (should be zero in first hour):**

```kusto
customEvents
| where timestamp > ago(1h)
| where name == "census_portal.locked"
```

Any rows here in the first hour mean someone (or something) is hammering the census login endpoint. Check source IPs in the `requests` table.

---

### G.3 Postgres — sanity SELECTs

Connect to prod:

```bash
DBURL=$(az keyvault secret show \
  --vault-name kv-hha-prod \
  -n database-url-sync \
  --query value -o tsv)

psql "$DBURL"
```

Run each check:

```sql
-- 11 sites seeded (10 if running a pilot subset)
SELECT COUNT(*) FROM masters.sites;
-- expected: 11

-- Exactly one census credential row
SELECT COUNT(*) FROM auth.census_credentials;
-- expected: 1

-- Correct canonical email
SELECT email FROM auth.census_credentials WHERE id = 1;
-- expected: portal@hhamedicine.com

-- Last smoke write landed (timestamp should match H+0 smoke run time)
SELECT MAX(updated_at) FROM entries.daily_entries;

-- Audit triggers fired at least once during the smoke run
SELECT COUNT(*) FROM audit.audit_log
WHERE changed_at > now() - interval '1 hour';
-- expected: >= 1 (at minimum the smoke INSERT)
```

If `masters.sites` returns fewer than 11, re-run `scripts/seed_sites.py`. If `auth.census_credentials` returns 0, re-run `infra/census_seed.sh`.

---

### G.4 Blob storage — pg_backup landed

At H+3 manually trigger the backup job (see § C "Trigger a cron job manually"), then verify:

```bash
ACCT=$(az storage account list -g rg-hha-dashboard-prod \
  --query '[0].name' -o tsv)

az storage blob list \
  --account-name $ACCT \
  --container-name backups \
  --query '[].{name:name,modified:lastModified,size:properties.contentLength}' \
  -o table
```

There must be at least one `.sql.gz` blob dated within the last hour. If the list is empty or shows only blobs older than yesterday, the job failed — see **D.6**.

**WORM immutability policy** — do not verify until H+8 (policy activation has a propagation delay on Azure). After H+8:

```bash
az storage container immutability-policy show \
  --account-name $ACCT \
  --container-name backups
```

`state` must be `Locked`. If still `Unlocked`, follow [ADR-004 § Part 3](adr/004-backup-and-disaster-recovery.md#part-3--worm-immutability-lock) to complete the lock. **Do not run this on a blob that you need to delete** — locked WORM is irreversible.

---

### G.5 ACS Email — sender validation

Verify SPF and DKIM are published for the sender domain (`hhamedicine.com`):

```bash
# SPF
dig TXT hhamedicine.com +short | grep spf

# DKIM (selector depends on your ACS domain config; check ACS portal for the selector name)
dig TXT <selector>._domainkey.hhamedicine.com +short
```

Both must return non-empty records. If either is missing, email will soft-fail or bounce — open the ACS portal → Email → Domains and follow the DNS record instructions.

**Confirm a test email arrived.** The `job-cred-scan` cron run at H+3 sends an email to subscribers if expiry events exist. Check `alerts.alert_log` for a row from today and confirm the recipient received it. If no expiry events exist (healthy system), trigger a manual smoke email via the API or send a test from the ACS portal.

---

### G.6 App Service — config + logs

**Confirm all Key Vault references resolved** (no raw `@Microsoft.KeyVault(...)` literals should appear in the values column):

```bash
az webapp config appsettings list \
  --name app-hha-api-prod \
  -g rg-hha-dashboard-prod \
  -o table
```

| Setting | Expected value |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://…` (resolved, not a KV reference literal) |
| `SESSION_SECRET` | 44-character base64 string (resolved) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | `InstrumentationKey=…` (resolved) |

If any value still shows `@Microsoft.KeyVault(…)`, the managed identity doesn't have `Key Vault Secrets User` on the vault — see the fix in **D.3** (KV reference row).

**Confirm logs are quiet:**

```bash
az webapp log tail \
  --name app-hha-api-prod \
  -g rg-hha-dashboard-prod
```

Startup should emit a few `INFO` structlog lines then go quiet. Repeated `ERROR` or `WARNING` lines mean a background task is failing. Let it run for ~30 seconds; if you see the same error repeating, treat it as an incident.

---

### G.7 Domain + TLS

```bash
DOMAIN=<your-custom-domain>   # e.g., api.hha-dashboard.hhamedicine.com

# 200 + no cert error
curl -fsS -I "https://${DOMAIN}/health"

# Cert details: issuer, expiry, SANs
openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" \
  </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates
```

Expected:

- `curl` returns HTTP 200 (not 301 to a `.azurewebsites.net` domain, not a cert error)
- `issuer` contains `DigiCert` or `Microsoft` (App Service managed cert)
- `notAfter` is at least 6 months out — if < 90 days, open a cert-renewal task now

If the domain isn't bound yet, follow **App Service → Custom domains → Add custom domain** in the portal and re-run `main.bicep` with the `custom_domain` param.

---

### G.8 Cost — first 24h sanity

Pull the current billing period's usage (replace `YYYYMM` with e.g. `202604`):

```bash
az consumption usage list \
  --billing-period-name <YYYYMM> \
  -o table | head -20
```

Postgres Flex Server is typically the largest line item (~60% of monthly cost). If Storage or App Insights is unexpectedly large, check for:

- App Insights ingestion runaway → cap via Log Analytics daily quota in `monitor.bicep`
- Storage bloat → check for unintentional blob retention (smoke test writing large objects?)

**Set a cost alert if not already present:**

```bash
RG_ID=$(az group show -n rg-hha-dashboard-prod --query id -o tsv)

az consumption budget create \
  --budget-name hha-prod-monthly \
  --amount 400 \
  --time-grain Monthly \
  --start-date "$(date -u +%Y-%m-01)" \
  --end-date "2027-01-01" \
  --resource-group-filter $RG_ID \
  --notification \
    enabled=true threshold=80 contact-emails="areddy@hhamedicine.com" \
  --notification \
    enabled=true threshold=100 contact-emails="areddy@hhamedicine.com"
```

Target: < $400/mo for a single-environment prod with 11 sites. Alert at 80% (~$320) and 100% ($400).

---

### G.9 Rollback escape hatch

If the deploy is actively broken and you can't fix forward in < 30 minutes, revert:

**List deployment slots (check if a staging slot exists):**

```bash
az webapp deployment slot list \
  --name app-hha-api-prod \
  -g rg-hha-dashboard-prod \
  -o table
```

**Swap back to the previous slot** (if a staging slot was used for blue/green):

```bash
az webapp deployment slot swap \
  --name app-hha-api-prod \
  -g rg-hha-dashboard-prod \
  --slot staging \
  --target-slot production
```

**Push a prior zip directly** (if no slot swap is available):

```bash
az webapp deployment source config-zip \
  --name app-hha-api-prod \
  -g rg-hha-dashboard-prod \
  --src <path-to-previous-api.zip>
```

**Schema migrations — DO NOT roll back without operator coordination.** `alembic downgrade` is one-way risk: the downgrade script may not exist or may destroy data. If the breakage is schema-related, fix forward with a new migration or hotfix the code to tolerate both schema versions. Coordinate with the technical lead before touching `alembic downgrade` in prod.

---

### G.10 The 24-hour watch list

Check these the morning after deploy (H+24):

- [ ] `bash scripts/smoke_deploy.sh` still exits 0 (consider wiring to a daily GitHub Actions cron)
- [ ] No App Insights alerts fired overnight (`traces | where severityLevel >= 3 | where timestamp > ago(24h)`)
- [ ] Backup blob exists dated 03:00 UTC (`az storage blob list … | grep $(date -u +%Y-%m-%d)`)
- [ ] Census portal lockout event count is still 0 (`customEvents | where name == "census_portal.locked"`)
- [ ] No user-reported auth failures in Slack / email
- [ ] 24h cost trajectory is on track (< $14/day at $400/mo ceiling)

If all boxes are checked: the deploy is stable. Add a note to `docs/FIRST_DEPLOY_NOTES.md` and close the deploy ticket.

---

## F. Where to find more

- **System overview** → [ARCHITECTURE.md](ARCHITECTURE.md)
- **Day-1 environment setup** → [ONBOARDING.md](ONBOARDING.md)
- **Why we made the calls we made** → [docs/adr/](adr/)
- **Build plan + session history** → [SESSION_RECAP_*.md](.) and the build plan in `.claude/plans/`
- **HIPAA classification** → [ADR-001](adr/001-hipaa-data-classification.md)
- **RBAC model** → [ADR-002](adr/002-rbac-model.md)
- **Audit trail** → [ADR-003](adr/003-audit-chain.md)
- **Backup & DR** → [ADR-004](adr/004-backup-and-disaster-recovery.md)
- **FL/TX scope split** → [ADR-005](adr/005-fl-tx-scope-split.md)

---

*Last reviewed: 2026-04-26 (Session 13: docs sprint).*
*Maintainer: technical lead. If anything in this RUNBOOK turns out to be wrong during an incident, fix it as the last step of incident close-out.*
