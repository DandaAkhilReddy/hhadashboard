# HHA Dashboard — Bicep infrastructure

This directory holds the Azure Bicep templates that provision the HHA
Dashboard. Layout:

```
infra/
├── main.bicep                # RG-scoped orchestrator
├── modules/
│   ├── postgres.bicep        # Flex Server v16 + database + deployer firewall
│   ├── appservice.bicep      # Plan + 2 sites (web + api), Linux runtime
│   ├── vnet.bicep            # 10.20.0.0/16 + 3 subnets + 2 private DNS zones
│   ├── keyvault.bicep        # KV with RBAC, soft-delete, optional private endpoint
│   ├── storage.bicep         # Storage Account + uploads + backups containers
│   └── monitor.bicep         # Log Analytics workspace + App Insights
├── env/
│   ├── dev.bicepparam        # enable_vnet=false, enable_keyvault=false, enable_storage=false
│   └── prod.bicepparam       # enable_vnet=true,  enable_keyvault=true,  enable_storage=true
└── bootstrap.sh              # idempotent KV secret seeding (Phase 2 of deploy)
```

## Backups container immutability lock (operator step)

The `backups` container is created as a regular soft-delete-enabled
container. Once the first nightly `pg_backup` cron job writes a few
test backups, the operator runs this **once per environment** to lock
the WORM policy in place. Locking is **irreversible** — by design —
so it isn't done automatically.

```bash
# After verifying a few backups have written successfully:
az storage container immutability-policy create \
  --account-name <storage_account_name from main.bicep output> \
  --container-name backups \
  --period 90 \
  --allow-protected-append-writes true

# Then lock the policy (cannot be unlocked, only extended):
az storage container immutability-policy lock \
  --account-name <storage_account_name> \
  --container-name backups \
  --if-match <etag from previous response>
```

## Two networking postures (parameter-driven)

| Toggle | Dev (default) | Prod (default) |
|---|---|---|
| `enable_vnet` | `false` | `true` |
| `enable_keyvault` | `false` | `true` |
| Postgres reachable from | Public + workstation firewall rule | VNet only (private NIC in delegated subnet) |
| Key Vault reachable from | (not deployed) | VNet only via private endpoint |
| App Service → Postgres | Public over the firewall allowlist | Regional VNet integration (App Service in `app` subnet, Postgres in `postgres` subnet) |
| App Service → Key Vault | Literal connection strings in app_settings | `@Microsoft.KeyVault(...)` references resolved by managed identity |
| Approx monthly cost overhead | $0 | ~$30 (VNet + 2 PEs + 2 DNS zones in eastus2) |

## Deploy procedure

The deploy is two phases: provision (Bicep) then seed-secrets (bootstrap.sh).

### Phase 1 — Provision

```bash
# from repo root, with az logged in to the right subscription
ENV=prod
RG=rg-hha-dashboard-${ENV}

az group create -n $RG -l eastus2

az deployment group create \
  -g $RG \
  -f infra/main.bicep \
  -p infra/env/${ENV}.bicepparam \
  -p postgres_admin_password='__placeholder__' \
  -p deployer_workstation_ip=$(curl -s ifconfig.me) \
  -p azure_tenant_id_for_kv=$(az account show --query tenantId -o tsv)
```

The placeholder `postgres_admin_password` is fine — Phase 2 overwrites it.
The deployment lands the VNet, KV (empty), Postgres, App Services with
VNet integration, plus the two RBAC role assignments. App settings
contain `@Microsoft.KeyVault(...)` references that won't resolve yet.

### Phase 2 — Seed secrets

```bash
ENV=prod bash infra/bootstrap.sh
```

This script generates a 24-byte postgres password, writes the three
secrets KV references expect (`postgres-admin-password`, `database-url`,
`database-url-sync`), and restarts the App Services so they pick up
the resolved values. Idempotent — re-running with an already-seeded
vault is a no-op.

After Phase 2:

```bash
curl -s https://app-hha-api-${ENV}.azurewebsites.net/health   # → {"status":"ok"}
curl -s https://app-hha-api-${ENV}.azurewebsites.net/ready    # → 200 with DB connected
```

## What's IN this scaffold (Sessions 8 + 9)

- **PostgreSQL Flexible Server v16** + the `hha_dashboard` database
  (TLS 1.2 enforced via server config, storage encrypted, retention 7 d dev /
  35 d prod, geo-redundant + zone-redundant HA in prod, **VNet injection in
  prod** when `enable_vnet=true`)
- **App Service Plan (Linux)** + **web** App Service (Next.js,
  `NODE|20-lts`) + **api** App Service (FastAPI, `PYTHON|3.12`) — HTTPS-only,
  `minTlsVersion: 1.2`, FTPS disabled, system-assigned managed identity,
  health-check path wired
- **VNet** (`enable_vnet=true`): 10.20.0.0/16, three subnets — `app` (delegated
  to `Microsoft.Web/serverFarms`), `postgres` (delegated to
  `Microsoft.DBforPostgreSQL/flexibleServers` for VNet injection),
  `private-endpoints` (no delegation, ready for KV + future PEs). Two private
  DNS zones (`privatelink.postgres.database.azure.com`,
  `privatelink.vaultcore.azure.net`) with VNet links so callers inside the
  VNet resolve the privatelink names automatically.
- **Key Vault** (`enable_keyvault=true`): RBAC auth (no access policies),
  90-day soft-delete + purge protection, `networkAcls.defaultAction: Deny`.
  When `enable_vnet=true`, KV gets a private endpoint in the PE subnet and
  `publicNetworkAccess: Disabled`. When `enable_vnet=false` (dev), KV stays
  public with the deployer-workstation IP allowlist. The vault is created
  **empty** — `bootstrap.sh` (Session 10) seeds the postgres admin password
  and other secrets out of band.

## What's NOT in this scaffold (deferred — see [the build plan](../../../.claude/plans/so-now-we-are-nested-grove.md))

- App Service VNet integration (`Microsoft.Web/sites/networkConfig`) → Session 10
- KV → App Service RBAC role assignments (`Key Vault Secrets User`) → Session 10
- KV references in `app_settings` (`@Microsoft.KeyVault(...)` syntax) — **gap**: the
  postgres password still flows through as a literal in `app_settings` until
  Session 10 wires it via KV reference
- `bootstrap.sh` that seeds initial KV secrets and creates the federated
  identity credential for OIDC → Session 10
- Blob Storage (uploads container, immutable backups container)
- Container Apps Jobs (cron: `paycom_sync`, `ventra_ingest`, `alert_digest`,
  `cred_scan`, `pg_backup`)
- Application Insights, Log Analytics, diagnostic settings
- Azure Communication Services (Email)
- RBAC role assignments (none yet — no managed identity consumes anything)
- GitHub Actions OIDC workflows (`deploy-dev.yml`, `deploy-prod.yml`)
- Custom domain + managed certificate
- App Service auto-scale rules
- CORS configuration on the api App Service

## Prerequisites

```bash
az --version          # need ≥ 2.62
az bicep version      # need ≥ 0.30 (this scaffold is verified with 0.37.4)
```

If you don't have Bicep yet, `az bicep install`.

## Compile-only verification (this session's gate)

```bash
# from repo root
az bicep build       --file infra/main.bicep                  --outfile /tmp/main.json
az bicep build       --file infra/modules/postgres.bicep      --outfile /tmp/postgres.json
az bicep build       --file infra/modules/appservice.bicep    --outfile /tmp/appservice.json
az bicep build-params --file infra/env/dev.bicepparam         --outfile /tmp/dev.params.json
az bicep build-params --file infra/env/prod.bicepparam        --outfile /tmp/prod.params.json
az bicep lint        --file infra/main.bicep
az bicep lint        --file infra/modules/postgres.bicep
az bicep lint        --file infra/modules/appservice.bicep
```

All seven commands exit 0 with no diagnostics.

## Deploy (a future session — not run in #13)

```bash
# One-time: login + pick subscription
az login
az account set -s <hha-subscription-id>

# Resource group (one-time, per env)
az group create -n rg-hha-dashboard-dev -l eastus2

# What-if (preview)
az deployment group what-if \
  -g rg-hha-dashboard-dev \
  -f infra/main.bicep \
  -p infra/env/dev.bicepparam \
  -p postgres_admin_password=$(openssl rand -base64 24) \
  -p deployer_workstation_ip=$(curl -s ifconfig.me)

# Real deploy
az deployment group create \
  -g rg-hha-dashboard-dev \
  -f infra/main.bicep \
  -p infra/env/dev.bicepparam \
  -p postgres_admin_password=$(openssl rand -base64 24) \
  -p deployer_workstation_ip=$(curl -s ifconfig.me)
```

Outputs include `web_url`, `api_url`, `postgres_host`, and the two managed
identity principal IDs.

## Post-deploy: API outbound IPs → Postgres firewall

Bicep can't drive a resource loop from an App Service's `outboundIpAddresses`
(BCP178 — deploy-time-only value). Run this after the initial `az deployment`
completes:

```bash
ENV=dev   # or prod
RG=rg-hha-dashboard-${ENV}
PSQL=psql-hha-${ENV}
APP=app-hha-api-${ENV}

for ip in $(az webapp show -n $APP -g $RG --query outboundIpAddresses -o tsv | tr ',' ' '); do
  az postgres flexible-server firewall-rule create \
    -g $RG -n $PSQL \
    --rule-name "api-outbound-${ip//./-}" \
    --start-ip-address "$ip" --end-ip-address "$ip"
done
```

When `vnet.bicep` lands (Session 9), this loop goes away — VNet integration
replaces public access + firewall with a private endpoint.

## Naming conventions

All resources use the `{kind}-hha-{env}` shape:

| Resource | Name pattern |
|---|---|
| Resource group | `rg-hha-dashboard-{env}` |
| Postgres server | `psql-hha-{env}` |
| App Service Plan | `plan-hha-{env}` |
| Web App Service | `app-hha-web-{env}` |
| API App Service | `app-hha-api-{env}` |

Tags applied to every resource: `project`, `environment`, `managed_by`,
`classification` (`phi-tier-b`), `cost_center`.

## HIPAA notes

- The dashboard data is classified Tier B per
  [docs/adr/001-hipaa-data-classification.md](../docs/adr/001-hipaa-data-classification.md).
  Postgres handles the encryption-at-rest by default (Microsoft-managed key);
  CMK + Key Vault key rotation comes with `keyvault.bicep`.
- `publicNetworkAccess: Enabled` on Postgres is **temporary** for v0. The
  firewall is tight (deployer IP + a small App Service outbound set), and
  there is **no** `0.0.0.0` / "Allow all Azure services" rule. VNet
  integration in Session 9 closes public access entirely.
- App Services use system-assigned managed identity — they have no
  identity-bearing secrets in app settings. Database password is the only
  secret in app settings today; that goes away when KV references replace
  it (Session 9).
- Diagnostic Settings → Log Analytics is **not** wired here. Required for
  HIPAA audit trail; lands with `monitor.bicep` in Session 11.
