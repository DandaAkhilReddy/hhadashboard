#!/usr/bin/env bash
# Creates all the missing Azure resources discovered by azure_discover.sh:
#   - 7 Entra security groups (HHA-Dashboard-Admin, Exec, CompViewer, 4× Owner-*)
#   - 2 app registrations (github-deploy-hha-dashboard, hha-dashboard-api-prod)
#   - federated credential on github-deploy for environment:prod
#   - Contributor role assignment on subscription for github-deploy SP
#
# Idempotent: skips groups/apps that already exist, picks up existing IDs.
#
# Usage: bash scripts/azure_create_missing.sh
#
# Outputs the final env block at the end. Copy that into your shell.

set -euo pipefail

GITHUB_REPO="DandaAkhilReddy/hhadashboard"   # change if repo slug differs
SUB_ID="$(az account show --query id -o tsv)"
TENANT_ID="$(az account show --query tenantId -o tsv)"

echo "=== Subscription: $SUB_ID"
echo "=== Tenant:        $TENANT_ID"
echo "=== GitHub repo:   $GITHUB_REPO (used for federated credential subject)"
echo

# ---------------- Helpers ----------------

ensure_group() {
  local display="$1" nickname="$2"
  local existing
  existing=$(az ad group list --display-name "$display" --query "[0].id" -o tsv 2>/dev/null || true)
  if [ -n "$existing" ]; then
    echo "$existing"
  else
    az ad group create --display-name "$display" --mail-nickname "$nickname" --query id -o tsv
  fi
}

ensure_app() {
  local display="$1"
  local existing
  existing=$(az ad app list --display-name "$display" --query "[0].appId" -o tsv 2>/dev/null || true)
  if [ -n "$existing" ]; then
    echo "$existing"
  else
    az ad app create --display-name "$display" --query appId -o tsv
  fi
}

ensure_sp() {
  local app_id="$1"
  local existing tmp_file body_file body_path_win post_resp
  # Avoid pipes between az and jq — `set -euo pipefail` interacts oddly with
  # az.cmd through WSL interop and silently drops the pipeline. Use a tempfile.
  tmp_file="$PWD/.sp-list-tmp.json"
  az ad sp list --all --output json > "$tmp_file" 2>/dev/null || true
  if [ -s "$tmp_file" ]; then
    existing=$(jq -r --arg id "$app_id" '.[] | select(.appId==$id) | .id' "$tmp_file" 2>/dev/null | head -1)
    rm -f "$tmp_file"
    if [ -n "$existing" ] && [ "$existing" != "null" ]; then
      echo "$existing"
      return 0
    fi
  else
    rm -f "$tmp_file"
  fi
  # Create via POST. Body in $PWD (Windows-visible) → wslpath conversion.
  body_file="$PWD/.sp-body-tmp.json"
  printf '{"appId":"%s"}' "$app_id" > "$body_file"
  body_path_win=$(wslpath -w "$body_file" 2>/dev/null || echo "$body_file")
  post_resp="$PWD/.sp-post-tmp.json"
  az rest --method POST \
    --uri "https://graph.microsoft.com/v1.0/servicePrincipals" \
    --body "@$body_path_win" --output json > "$post_resp" 2>/dev/null || true
  rm -f "$body_file"
  if [ -s "$post_resp" ]; then
    existing=$(jq -r '.id // empty' "$post_resp" 2>/dev/null)
    rm -f "$post_resp"
    if [ -n "$existing" ] && [ "$existing" != "null" ]; then
      echo "$existing"
      return 0
    fi
  else
    rm -f "$post_resp"
  fi
  echo "WARN: could not resolve SP for app $app_id (continuing — not required downstream)" >&2
  echo ""
  return 0
}

# ---------------- 7 Entra groups ----------------

echo "=== Creating/checking 7 Entra security groups ==="
ENTRA_GROUP_ADMIN=$(ensure_group "HHA-Dashboard-Admin" "hha-dashboard-admin")
echo "  Admin:           $ENTRA_GROUP_ADMIN"
ENTRA_GROUP_EXEC=$(ensure_group "HHA-Dashboard-Exec" "hha-dashboard-exec")
echo "  Exec:            $ENTRA_GROUP_EXEC"
ENTRA_GROUP_COMP_VIEWER=$(ensure_group "HHA-Dashboard-CompViewer" "hha-dashboard-compviewer")
echo "  CompViewer:      $ENTRA_GROUP_COMP_VIEWER"
ENTRA_GROUP_OWNER_OPS=$(ensure_group "HHA-Dashboard-Owner-Ops" "hha-dashboard-owner-ops")
echo "  Owner-Ops:       $ENTRA_GROUP_OWNER_OPS"
ENTRA_GROUP_OWNER_FINANCE=$(ensure_group "HHA-Dashboard-Owner-Finance" "hha-dashboard-owner-finance")
echo "  Owner-Finance:   $ENTRA_GROUP_OWNER_FINANCE"
ENTRA_GROUP_OWNER_CLINICAL=$(ensure_group "HHA-Dashboard-Owner-Clinical" "hha-dashboard-owner-clinical")
echo "  Owner-Clinical:  $ENTRA_GROUP_OWNER_CLINICAL"
ENTRA_GROUP_OWNER_HR=$(ensure_group "HHA-Dashboard-Owner-HR" "hha-dashboard-owner-hr")
echo "  Owner-HR:        $ENTRA_GROUP_OWNER_HR"
echo

# ---------------- App registrations ----------------

echo "=== Creating/checking github-deploy app reg ==="
AZURE_CLIENT_ID=$(ensure_app "github-deploy-hha-dashboard")
echo "  AZURE_CLIENT_ID: $AZURE_CLIENT_ID"
DEPLOY_SP_ID=$(ensure_sp "$AZURE_CLIENT_ID")
echo "  Service Principal: $DEPLOY_SP_ID"
echo

echo "=== Creating/checking api app reg ==="
AZURE_API_CLIENT_ID=$(ensure_app "hha-dashboard-api-prod")
echo "  AZURE_API_CLIENT_ID: $AZURE_API_CLIENT_ID"
echo

# ---------------- Federated credential ----------------

echo "=== Adding federated credential for environment:prod ==="
# Tempfile-based lookup — verified working pattern from manual debug.
# `az ad app list --all` writes JSON to disk, jq filters from file. No
# pipes between az.cmd (Windows) and jq (WSL) → no interop weirdness.
TMP_APPS="$PWD/.apps-list-tmp.json"
az ad app list --all --output json > "$TMP_APPS" 2>/dev/null || true
if [ ! -s "$TMP_APPS" ]; then
  echo "ERROR: az ad app list --all returned no output" >&2
  rm -f "$TMP_APPS"
  exit 1
fi
APP_OBJECT_ID=$(jq -r --arg id "$AZURE_CLIENT_ID" '.[] | select(.appId==$id) | .id' "$TMP_APPS" | head -1)
rm -f "$TMP_APPS"
if [ -z "$APP_OBJECT_ID" ] || [ "$APP_OBJECT_ID" = "null" ]; then
  echo "ERROR: could not resolve object id for app $AZURE_CLIENT_ID" >&2
  exit 1
fi
echo "  app object id: $APP_OBJECT_ID"

# Same tempfile pattern for fed-cred existence check.
TMP_FEDS="$PWD/.feds-list-tmp.json"
az rest --method GET \
  --uri "https://graph.microsoft.com/v1.0/applications/$APP_OBJECT_ID/federatedIdentityCredentials" \
  --output json > "$TMP_FEDS" 2>/dev/null || true
EXISTING_FED=""
if [ -s "$TMP_FEDS" ]; then
  EXISTING_FED=$(jq -r '.value[] | select(.name=="github-prod") | .id' "$TMP_FEDS" 2>/dev/null | head -1)
fi
rm -f "$TMP_FEDS"
if [ -n "$EXISTING_FED" ] && [ "$EXISTING_FED" != "null" ]; then
  echo "  ✓ federated credential 'github-prod' already exists"
else
  # Tempfile in $PWD (Windows-visible); az.cmd cannot read /tmp from WSL.
  FED_FILE="$PWD/.fed-cred-tmp.json"
  cat > "$FED_FILE" <<EOF
{
  "name": "github-prod",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:${GITHUB_REPO}:environment:prod",
  "audiences": ["api://AzureADTokenExchange"]
}
EOF
  FED_FILE_WIN=$(wslpath -w "$FED_FILE" 2>/dev/null || echo "$FED_FILE")
  az rest --method POST \
    --uri "https://graph.microsoft.com/v1.0/applications/$APP_OBJECT_ID/federatedIdentityCredentials" \
    --body "@$FED_FILE_WIN" >/dev/null
  rm -f "$FED_FILE"
  echo "  ✓ created"
fi
echo

# ---------------- Role assignment ----------------

echo "=== Granting Contributor on subscription to github-deploy SP ==="
EXISTING_ROLE=$(az role assignment list --assignee "$AZURE_CLIENT_ID" --scope "/subscriptions/$SUB_ID" --role Contributor --query "[0].id" -o tsv 2>/dev/null || true)
if [ -n "$EXISTING_ROLE" ]; then
  echo "  ✓ Contributor role already assigned"
else
  # Sleep briefly because new SPs need a moment for AAD propagation
  sleep 10
  az role assignment create --assignee "$AZURE_CLIENT_ID" --role Contributor --scope "/subscriptions/$SUB_ID" >/dev/null
  echo "  ✓ assigned"
fi
echo

# ---------------- Final env block ----------------

echo "==============================================="
echo "=== Final env block (copy into your shell)   ==="
echo "==============================================="
cat <<EOF

  AZURE_SUBSCRIPTION_ID=$SUB_ID
  AZURE_TENANT_ID=$TENANT_ID
  AZURE_CLIENT_ID=$AZURE_CLIENT_ID
  AZURE_TENANT_ID_FOR_KV=$TENANT_ID
  AZURE_API_CLIENT_ID=$AZURE_API_CLIENT_ID
  ENTRA_GROUP_ADMIN=$ENTRA_GROUP_ADMIN
  ENTRA_GROUP_EXEC=$ENTRA_GROUP_EXEC
  ENTRA_GROUP_COMP_VIEWER=$ENTRA_GROUP_COMP_VIEWER
  ENTRA_GROUP_OWNER_OPS=$ENTRA_GROUP_OWNER_OPS
  ENTRA_GROUP_OWNER_FINANCE=$ENTRA_GROUP_OWNER_FINANCE
  ENTRA_GROUP_OWNER_CLINICAL=$ENTRA_GROUP_OWNER_CLINICAL
  ENTRA_GROUP_OWNER_HR=$ENTRA_GROUP_OWNER_HR

EOF

echo "Next: re-run 'bash scripts/azure_discover.sh --write-gh-secrets' to push these to GitHub repo Variables."
