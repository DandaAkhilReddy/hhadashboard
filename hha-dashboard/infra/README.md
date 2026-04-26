# HHA Dashboard — Bicep infrastructure

This directory holds the Azure Bicep templates that provision the HHA
Dashboard. Layout:

```
infra/
├── main.bicep                # RG-scoped orchestrator
├── modules/
│   ├── postgres.bicep        # Flex Server v16 + database + deployer firewall
│   └── appservice.bicep      # Plan + 2 sites (web + api), Linux runtime
└── env/
    ├── dev.bicepparam
    └── prod.bicepparam
```

## What's IN this scaffold (Session 8)

- One **PostgreSQL Flexible Server v16** + the `hha_dashboard` database
  (TLS 1.2 enforced via server config, storage encrypted, retention 7 d dev /
  35 d prod, geo-redundant + zone-redundant HA in prod)
- One **App Service Plan (Linux)** + one **web** App Service (Next.js,
  `NODE|20-lts`) + one **api** App Service (FastAPI, `PYTHON|3.12`)
- HTTPS-only, `minTlsVersion: 1.2`, FTPS disabled, system-assigned managed
  identity, health-check path wired
- A single Postgres firewall rule for the **deployer's workstation IP**

## What's NOT in this scaffold (deferred — see [the build plan](../../../.claude/plans/so-now-we-are-nested-grove.md))

- VNet integration / private endpoints / private DNS zones
- Key Vault (secrets pass via app settings; KV references replace later)
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
