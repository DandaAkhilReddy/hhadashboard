#!/usr/bin/env bash
#
# bootstrap.sh — one-time / idempotent secret seeding for the HHA Dashboard
#                Key Vault. Run AFTER `az deployment group create` lands the
#                infrastructure (vault exists) and BEFORE the App Services
#                expect KV references to resolve.
#
# What this script does:
#   1. Confirms `az` is logged in and pointed at the right subscription
#   2. Generates a postgres admin password (24 bytes base64) if not provided
#   3. Writes secrets to KV: `database-url`, `database-url-sync`, and the
#      raw `postgres-admin-password` (kept around for migration / debugging)
#   4. Restarts the App Service web + api so the new app_settings KV
#      references resolve immediately
#   5. Prints the OIDC federated credential setup command (commented out
#      because Session 11 ships the actual GitHub Actions wiring)
#
# What this script does NOT do:
#   - Run `az deployment group create` — that's the operator's call
#   - Create Entra app registrations or security groups — see docs/ENTRA_SETUP.md
#   - Set up the federated identity credential — Session 11
#
# Usage:
#   ENV=dev   bash bootstrap.sh                              # generates password
#   ENV=prod  POSTGRES_PASSWORD='...' bash bootstrap.sh      # caller-supplied
#
# Idempotency: re-running with the same ENV is a no-op. Existing secrets are
# left in place; existing role assignments aren't touched (Bicep handles
# those).

set -euo pipefail

# ----------------------------------------------------------------------------
# Inputs
# ----------------------------------------------------------------------------

ENV="${ENV:?Set ENV=dev or ENV=prod before invoking this script}"
RG="${RG:-rg-hha-dashboard-${ENV}}"
VAULT="${VAULT:-kv-hha-${ENV}}"
PG_HOST="${PG_HOST:-psql-hha-${ENV}.postgres.database.azure.com}"
PG_USER="${PG_USER:-hhaadmin}"
PG_DB="${PG_DB:-hha_dashboard}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"

# ----------------------------------------------------------------------------
# Pre-flight
# ----------------------------------------------------------------------------

if ! command -v az >/dev/null 2>&1; then
  echo "ERROR: az CLI not found. Install from https://aka.ms/install-azure-cli" >&2
  exit 1
fi

if ! az account show >/dev/null 2>&1; then
  echo "ERROR: not signed in to Azure. Run \`az login\` first." >&2
  exit 1
fi

CURRENT_SUB=$(az account show --query id -o tsv)
echo "[info] subscription: $CURRENT_SUB"
echo "[info] resource group: $RG"
echo "[info] vault: $VAULT"
echo "[info] postgres host: $PG_HOST"
echo

if ! az group show -n "$RG" >/dev/null 2>&1; then
  echo "ERROR: resource group $RG not found. Run az deployment first." >&2
  exit 1
fi

if ! az keyvault show -n "$VAULT" >/dev/null 2>&1; then
  echo "ERROR: Key Vault $VAULT not found in $RG. Did you deploy with enable_keyvault=true?" >&2
  exit 1
fi

# ----------------------------------------------------------------------------
# Postgres admin password
# ----------------------------------------------------------------------------

if [ -z "$POSTGRES_PASSWORD" ]; then
  if az keyvault secret show --vault-name "$VAULT" -n postgres-admin-password >/dev/null 2>&1; then
    echo "[info] postgres-admin-password already in $VAULT — leaving it alone."
    POSTGRES_PASSWORD=$(az keyvault secret show --vault-name "$VAULT" -n postgres-admin-password --query value -o tsv)
  else
    echo "[info] generating new 24-byte postgres password"
    POSTGRES_PASSWORD=$(openssl rand -base64 24)
    az keyvault secret set --vault-name "$VAULT" -n postgres-admin-password --value "$POSTGRES_PASSWORD" >/dev/null
    echo "[ok] wrote postgres-admin-password"
  fi
else
  echo "[info] using caller-supplied POSTGRES_PASSWORD"
  az keyvault secret set --vault-name "$VAULT" -n postgres-admin-password --value "$POSTGRES_PASSWORD" >/dev/null
  echo "[ok] wrote postgres-admin-password (overwrote any existing)"
fi

# ----------------------------------------------------------------------------
# Connection-string secrets
#
# App Service `@Microsoft.KeyVault(...)` references resolve to the WHOLE
# secret value, so we store the full connection strings here (matching what
# main.bicep's database_url / database_url_sync expect when enable_keyvault
# is true).
# ----------------------------------------------------------------------------

DATABASE_URL="postgresql+asyncpg://${PG_USER}:${POSTGRES_PASSWORD}@${PG_HOST}:5432/${PG_DB}?ssl=require"
DATABASE_URL_SYNC="postgresql+psycopg://${PG_USER}:${POSTGRES_PASSWORD}@${PG_HOST}:5432/${PG_DB}?sslmode=require"

az keyvault secret set --vault-name "$VAULT" -n database-url      --value "$DATABASE_URL"      >/dev/null
az keyvault secret set --vault-name "$VAULT" -n database-url-sync --value "$DATABASE_URL_SYNC" >/dev/null
echo "[ok] wrote database-url + database-url-sync"

# ----------------------------------------------------------------------------
# Restart App Services so the new KV references resolve immediately
# ----------------------------------------------------------------------------

WEB_APP="app-hha-web-${ENV}"
API_APP="app-hha-api-${ENV}"

if az webapp show -n "$API_APP" -g "$RG" >/dev/null 2>&1; then
  echo "[info] restarting $API_APP to pick up new KV references"
  az webapp restart -n "$API_APP" -g "$RG" >/dev/null
fi

if az webapp show -n "$WEB_APP" -g "$RG" >/dev/null 2>&1; then
  echo "[info] restarting $WEB_APP to pick up new KV references"
  az webapp restart -n "$WEB_APP" -g "$RG" >/dev/null
fi

# ----------------------------------------------------------------------------
# Next steps (printed, not run)
# ----------------------------------------------------------------------------

cat <<EOF

[done] Bootstrap complete for $ENV.

Verify the api can reach Postgres:
  curl -s https://${API_APP}.azurewebsites.net/health
  curl -s https://${API_APP}.azurewebsites.net/ready

If /ready returns 503, check the App Service log stream for the api:
  az webapp log tail -n $API_APP -g $RG

Common first-time issue: KV reference shows up unresolved in the
'Configuration' blade of $API_APP. Causes:
  - role assignment hasn't propagated yet (wait 60-120 s)
  - vault network rules blocking the App Service VNet (check enable_vnet
    matches the deployed posture)

.github/workflows/deploy-${ENV}.yml runs az deployment via OIDC federated
identity. One-time setup (run AS A TENANT/SUBSCRIPTION ADMIN, NOT this
script):

  # 1. Create an Entra app for GitHub Actions to authenticate as
  GITHUB_APP=\$(az ad app create --display-name 'github-actions-hha-dashboard' --query appId -o tsv)
  az ad sp create --id \$GITHUB_APP

  # 2. Grant Contributor on the resource group (limit-scope)
  az role assignment create \\
    --role Contributor \\
    --scope \$(az group show -n $RG --query id -o tsv) \\
    --assignee \$GITHUB_APP

  # 3. Grant Key Vault Secrets Officer on the vault so deploys can seed
  #    secrets via this script invoked from the runner
  az role assignment create \\
    --role 'Key Vault Secrets Officer' \\
    --scope \$(az keyvault show -n $VAULT --query id -o tsv) \\
    --assignee \$GITHUB_APP

  # 4. Federated credential — branch ref binding
  az ad app federated-credential create \\
    --id \$GITHUB_APP \\
    --parameters '{
      "name": "github-deploy-${ENV}",
      "issuer": "https://token.actions.githubusercontent.com",
      "subject": "repo:DandaAkhilReddy/hhadashboard:ref:refs/heads/main",
      "audiences": ["api://AzureADTokenExchange"]
    }'

  # 5. Set GitHub repository variables (Settings → Secrets and variables → Actions → Variables)
  #    AZURE_CLIENT_ID       \$GITHUB_APP
  #    AZURE_TENANT_ID       \$(az account show --query tenantId -o tsv)
  #    AZURE_SUBSCRIPTION_ID $CURRENT_SUB

After step 5, you can trigger deploys via:
  gh workflow run deploy-${ENV}.yml --ref main -f dry_run=false

EOF
