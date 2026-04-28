#!/usr/bin/env bash
# scripts/azure_discover.sh
#
# Self-service discovery tool for the 13 Azure sponsor inputs required to
# deploy HHA Dashboard (dev + prod) to Azure via GitHub Actions.
#
# Default mode: read-only. Prints found values, prints create commands for
# anything missing. Does NOT modify Azure or GitHub.
#
# --create-helpers  : Print all create commands (even for found resources).
# --write-gh-secrets: Push non-secret values to GitHub repo Variables and
#                     write Entra / API IDs to infra/env/.deploy-overrides.local.env.
#
# Reference: docs/ARCHITECTURE.md and .github/workflows/deploy-{dev,prod}.yml

set -euo pipefail

# ---------------------------------------------------------------------------
# Color helpers (only when connected to a terminal)
# ---------------------------------------------------------------------------
if [[ -t 1 ]]; then
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[1;33m'
  CYAN='\033[0;36m'
  BOLD='\033[1m'
  RESET='\033[0m'
else
  RED='' GREEN='' YELLOW='' CYAN='' BOLD='' RESET=''
fi

ok()      { echo -e "${GREEN}✓${RESET} $*"; }
fail()    { echo -e "${RED}✗${RESET} $*"; }
warn()    { echo -e "${YELLOW}?${RESET} $*"; }
info()    { echo -e "${CYAN}${BOLD}$*${RESET}"; }
die()     { echo -e "${RED}ERROR:${RESET} $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Redaction helper: show first-4 + last-4 chars for sensitive strings.
# Subscription/tenant IDs are not secret so those skip redaction at call sites.
# ---------------------------------------------------------------------------
redact() {
  local v="$1"
  local len=${#v}
  if [[ $len -le 8 ]]; then
    echo "****"
  else
    echo "${v:0:4}...${v: -4}"
  fi
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
MODE_CREATE_HELPERS=false
MODE_WRITE_GH=false
SHOW_HELP=false

for arg in "$@"; do
  case "$arg" in
    --create-helpers)   MODE_CREATE_HELPERS=true ;;
    --write-gh-secrets) MODE_WRITE_GH=true ;;
    --help|-h)          SHOW_HELP=true ;;
    *) die "Unknown argument: $arg. Use --help for usage." ;;
  esac
done

if $SHOW_HELP; then
  cat <<'EOF'
Usage: bash scripts/azure_discover.sh [OPTIONS]

Discover the 13 Azure sponsor inputs needed to deploy HHA Dashboard.

Options:
  (none)              Read-only discovery. Prints found values and create
                      commands for anything missing.
  --create-helpers    Print ALL create commands (even for resources that
                      already exist), for reproducible setup documentation.
  --write-gh-secrets  After discovery, push non-secret values to GitHub repo
                      Variables (AZURE_CLIENT_ID, AZURE_TENANT_ID,
                      AZURE_SUBSCRIPTION_ID, AZURE_TENANT_ID_FOR_KV) and
                      write Entra group IDs + AZURE_API_CLIENT_ID to
                      infra/env/.deploy-overrides.local.env.
                      Requires: gh CLI authenticated (gh auth status).
  --help, -h          Show this help message.

Prerequisites:
  - Azure CLI installed and logged in (az login)
  - jq installed
  - curl installed
  - gh CLI installed and authenticated (only for --write-gh-secrets)

EOF
  exit 0
fi

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
info "=== Preflight checks ==="

check_cmd() {
  local cmd="$1"
  local install_hint="$2"
  if ! command -v "$cmd" &>/dev/null; then
    die "'$cmd' not found. ${install_hint}"
  fi
  ok "$cmd found: $(command -v "$cmd")"
}

check_cmd az   "Install Azure CLI: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
check_cmd jq   "Install jq: https://stedolan.github.io/jq/download/"
check_cmd curl "Install curl via your package manager."

if $MODE_WRITE_GH; then
  check_cmd gh "Install GitHub CLI: https://cli.github.com/"
  if ! gh auth status &>/dev/null; then
    die "'gh' is installed but not authenticated. Run: gh auth login"
  fi
  ok "gh authenticated"
fi

echo ""

# ---------------------------------------------------------------------------
# az account check
# ---------------------------------------------------------------------------
info "=== Checking Azure login ==="

AZ_ACCOUNT_JSON=""
if ! AZ_ACCOUNT_JSON=$(timeout 30 az account show -o json 2>/dev/null); then
  echo ""
  die "Not logged in to Azure CLI, or 'az account show' timed out.
Run: az login
Then re-run this script."
fi

ok "Azure account found"
echo ""

# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

# Run an az command with a 30-second timeout. Returns stdout on success, empty
# string on failure (does NOT exit the script).
az_query() {
  local description="$1"
  shift
  local result
  if result=$(timeout 30 "$@" 2>/dev/null); then
    # Strip whitespace; treat literal "None" / "" as missing
    result=$(echo "$result" | tr -d '[:space:]')
    if [[ -z "$result" || "$result" == "None" || "$result" == "null" ]]; then
      echo ""
    else
      echo "$result"
    fi
  else
    echo ""
  fi
}

# ---------------------------------------------------------------------------
# 1. AZURE_SUBSCRIPTION_ID
# ---------------------------------------------------------------------------
AZURE_SUBSCRIPTION_ID=$(echo "$AZ_ACCOUNT_JSON" | jq -r '.id // empty')
AZURE_SUBSCRIPTION_NAME=$(echo "$AZ_ACCOUNT_JSON" | jq -r '.name // empty')

# ---------------------------------------------------------------------------
# 2. AZURE_TENANT_ID
# ---------------------------------------------------------------------------
AZURE_TENANT_ID=$(echo "$AZ_ACCOUNT_JSON" | jq -r '.tenantId // empty')

# ---------------------------------------------------------------------------
# 3. AZURE_TENANT_ID_FOR_KV  (defaults to tenant)
# ---------------------------------------------------------------------------
AZURE_TENANT_ID_FOR_KV="$AZURE_TENANT_ID"

# ---------------------------------------------------------------------------
# 4. AZURE_CLIENT_ID  (federated app reg for GH Actions OIDC)
# ---------------------------------------------------------------------------
info "=== Discovering AZURE_CLIENT_ID (github-deploy-hha-dashboard) ==="
AZURE_CLIENT_ID=$(az_query "github-deploy-hha-dashboard app" \
  az ad app list \
    --display-name "github-deploy-hha-dashboard" \
    --query '[0].appId' \
    -o tsv)

# ---------------------------------------------------------------------------
# 5. AZURE_API_CLIENT_ID  (API app registration)
# ---------------------------------------------------------------------------
info "=== Discovering AZURE_API_CLIENT_ID (hha-dashboard-api-prod) ==="
AZURE_API_CLIENT_ID=$(az_query "hha-dashboard-api-prod" \
  az ad app list \
    --display-name "hha-dashboard-api-prod" \
    --query '[0].appId' \
    -o tsv)

# Fallback: try -dev suffix
if [[ -z "$AZURE_API_CLIENT_ID" ]]; then
  AZURE_API_CLIENT_ID=$(az_query "hha-dashboard-api-dev" \
    az ad app list \
      --display-name "hha-dashboard-api-dev" \
      --query '[0].appId' \
      -o tsv)
fi

# ---------------------------------------------------------------------------
# 6-12. Entra security groups
# ---------------------------------------------------------------------------
info "=== Discovering Entra security groups ==="

declare -A ENTRA_GROUPS
declare -A ENTRA_GROUP_DISPLAY_NAMES
ENTRA_GROUP_DISPLAY_NAMES["ENTRA_GROUP_ADMIN"]="HHA-Dashboard-Admin"
ENTRA_GROUP_DISPLAY_NAMES["ENTRA_GROUP_EXEC"]="HHA-Dashboard-Exec"
ENTRA_GROUP_DISPLAY_NAMES["ENTRA_GROUP_COMP_VIEWER"]="HHA-Dashboard-CompViewer"
ENTRA_GROUP_DISPLAY_NAMES["ENTRA_GROUP_OWNER_OPS"]="HHA-Dashboard-Owner-Ops"
ENTRA_GROUP_DISPLAY_NAMES["ENTRA_GROUP_OWNER_FINANCE"]="HHA-Dashboard-Owner-Finance"
ENTRA_GROUP_DISPLAY_NAMES["ENTRA_GROUP_OWNER_CLINICAL"]="HHA-Dashboard-Owner-Clinical"
ENTRA_GROUP_DISPLAY_NAMES["ENTRA_GROUP_OWNER_HR"]="HHA-Dashboard-Owner-HR"

# Ordered list of variable names for deterministic output
ENTRA_VAR_ORDER=(
  ENTRA_GROUP_ADMIN
  ENTRA_GROUP_EXEC
  ENTRA_GROUP_COMP_VIEWER
  ENTRA_GROUP_OWNER_OPS
  ENTRA_GROUP_OWNER_FINANCE
  ENTRA_GROUP_OWNER_CLINICAL
  ENTRA_GROUP_OWNER_HR
)

for var_name in "${ENTRA_VAR_ORDER[@]}"; do
  display="${ENTRA_GROUP_DISPLAY_NAMES[$var_name]}"
  group_id=$(az_query "$display" \
    az ad group show \
      --group "$display" \
      --query id \
      -o tsv)
  ENTRA_GROUPS["$var_name"]="$group_id"
done

# ---------------------------------------------------------------------------
# 13. DEPLOYER_WORKSTATION_IP
# ---------------------------------------------------------------------------
info "=== Discovering DEPLOYER_WORKSTATION_IP ==="
DEPLOYER_WORKSTATION_IP=""
if DEPLOYER_WORKSTATION_IP=$(timeout 10 curl -s ifconfig.me 2>/dev/null); then
  DEPLOYER_WORKSTATION_IP=$(echo "$DEPLOYER_WORKSTATION_IP" | tr -d '[:space:]')
fi

# ---------------------------------------------------------------------------
# Interactive prompts: CUSTOM_DOMAIN and SPONSOR_EMAIL
# ---------------------------------------------------------------------------
echo ""
info "=== Interactive inputs ==="

if [[ -t 0 ]]; then
  read -r -p "$(warn "CUSTOM_DOMAIN — please enter [dashboard.hhamedicine.com]: ")" CUSTOM_DOMAIN_INPUT
  CUSTOM_DOMAIN="${CUSTOM_DOMAIN_INPUT:-dashboard.hhamedicine.com}"

  read -r -p "$(warn "SPONSOR_EMAIL — please enter: ")" SPONSOR_EMAIL
  SPONSOR_EMAIL="${SPONSOR_EMAIL:-}"
else
  # Non-interactive (piped): use defaults / empty
  CUSTOM_DOMAIN="dashboard.hhamedicine.com"
  SPONSOR_EMAIL=""
fi

echo ""

# ---------------------------------------------------------------------------
# Print discovery report
# ---------------------------------------------------------------------------
info "=== Azure inputs discovered for HHA Dashboard ==="
echo ""

print_value() {
  local name="$1"
  local value="$2"
  local note="${3:-}"
  if [[ -n "$value" ]]; then
    if [[ -n "$note" ]]; then
      ok "${BOLD}${name}${RESET} = ${value}  ${CYAN}(${note})${RESET}"
    else
      ok "${BOLD}${name}${RESET} = ${value}"
    fi
  else
    if [[ -n "$note" ]]; then
      fail "${BOLD}${name}${RESET} — ${note}"
    else
      fail "${BOLD}${name}${RESET} — not found"
    fi
  fi
}

print_secret_value() {
  local name="$1"
  local value="$2"
  local note="${3:-}"
  if [[ -n "$value" ]]; then
    if [[ -n "$note" ]]; then
      ok "${BOLD}${name}${RESET} = $(redact "$value")  ${CYAN}(${note})${RESET}"
    else
      ok "${BOLD}${name}${RESET} = $(redact "$value")"
    fi
  else
    if [[ -n "$note" ]]; then
      fail "${BOLD}${name}${RESET} — ${note}"
    else
      fail "${BOLD}${name}${RESET} — not found"
    fi
  fi
}

# Subscription and tenant IDs are not secret
print_value "AZURE_SUBSCRIPTION_ID" "$AZURE_SUBSCRIPTION_ID" "subscription: ${AZURE_SUBSCRIPTION_NAME:-unknown}"
print_value "AZURE_TENANT_ID"       "$AZURE_TENANT_ID"
print_secret_value "AZURE_CLIENT_ID" "$AZURE_CLIENT_ID" "app reg: github-deploy-hha-dashboard"
print_value "AZURE_TENANT_ID_FOR_KV" "$AZURE_TENANT_ID_FOR_KV" "= tenant"
print_secret_value "AZURE_API_CLIENT_ID" "$AZURE_API_CLIENT_ID" "app reg: hha-dashboard-api-prod"

for var_name in "${ENTRA_VAR_ORDER[@]}"; do
  display="${ENTRA_GROUP_DISPLAY_NAMES[$var_name]}"
  val="${ENTRA_GROUPS[$var_name]}"
  if [[ -n "$val" ]]; then
    ok "${BOLD}${var_name}${RESET} = $(redact "$val")  ${CYAN}(group: ${display})${RESET}"
  else
    fail "${BOLD}${var_name}${RESET} — group \"${display}\" not found"
  fi
done

if [[ -n "$DEPLOYER_WORKSTATION_IP" ]]; then
  print_value "DEPLOYER_WORKSTATION_IP" "$DEPLOYER_WORKSTATION_IP"
else
  fail "DEPLOYER_WORKSTATION_IP — could not reach ifconfig.me"
fi

if [[ -n "$CUSTOM_DOMAIN" ]]; then
  print_value "CUSTOM_DOMAIN"  "$CUSTOM_DOMAIN"
else
  warn "CUSTOM_DOMAIN — not provided"
fi

if [[ -n "$SPONSOR_EMAIL" ]]; then
  print_secret_value "SPONSOR_EMAIL" "$SPONSOR_EMAIL"
else
  warn "SPONSOR_EMAIL — not provided"
fi

echo ""

# ---------------------------------------------------------------------------
# Collect what's missing
# ---------------------------------------------------------------------------
MISSING_CLIENT_ID=false
MISSING_API_CLIENT_ID=false
MISSING_GROUPS=()

[[ -z "$AZURE_CLIENT_ID" ]]     && MISSING_CLIENT_ID=true
[[ -z "$AZURE_API_CLIENT_ID" ]] && MISSING_API_CLIENT_ID=true

for var_name in "${ENTRA_VAR_ORDER[@]}"; do
  [[ -z "${ENTRA_GROUPS[$var_name]}" ]] && MISSING_GROUPS+=("$var_name")
done

HAS_MISSING=false
$MISSING_CLIENT_ID      && HAS_MISSING=true
$MISSING_API_CLIENT_ID  && HAS_MISSING=true
[[ ${#MISSING_GROUPS[@]} -gt 0 ]] && HAS_MISSING=true

# ---------------------------------------------------------------------------
# Items needing create (shown when missing OR when --create-helpers requested)
# ---------------------------------------------------------------------------
if $HAS_MISSING || $MODE_CREATE_HELPERS; then
  echo ""
  info "=== Items needing create ==="
  echo ""
fi

# --- github-deploy-hha-dashboard federated credential ---
if $MISSING_CLIENT_ID || $MODE_CREATE_HELPERS; then
  if $MISSING_CLIENT_ID; then
    echo "The app registration 'github-deploy-hha-dashboard' was not found."
    echo "Create it with the following 5 commands (run in order):"
  else
    echo "Reproducible create commands for 'github-deploy-hha-dashboard':"
  fi
  echo ""
  cat <<'  EOF'
  # 1. Create the app registration
  az ad app create --display-name "github-deploy-hha-dashboard"

  # 2. Note the appId from the output above, then create the service principal
  # Replace <APP_ID> with the appId from step 1
  APP_ID="<APP_ID>"
  az ad sp create --id "$APP_ID"

  # 3. Assign Contributor role on the subscription
  SUBSCRIPTION_ID=$(az account show --query id -o tsv)
  az role assignment create \
    --assignee "$APP_ID" \
    --role Contributor \
    --scope "/subscriptions/${SUBSCRIPTION_ID}"

  # 4. Create federated credential for the dev environment
  az ad app federated-credential create --id "$APP_ID" --parameters '{
    "name": "github-actions-dev",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:DandaAkhilReddy/hhadashboard:environment:dev",
    "description": "GitHub Actions OIDC for dev deploys",
    "audiences": ["api://AzureADTokenExchange"]
  }'

  # 5. Create federated credential for the prod environment
  az ad app federated-credential create --id "$APP_ID" --parameters '{
    "name": "github-actions-prod",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:DandaAkhilReddy/hhadashboard:environment:prod",
    "description": "GitHub Actions OIDC for prod deploys",
    "audiences": ["api://AzureADTokenExchange"]
  }'
  EOF
  echo ""
fi

# --- hha-dashboard-api-prod app registration ---
if $MISSING_API_CLIENT_ID || $MODE_CREATE_HELPERS; then
  if $MISSING_API_CLIENT_ID; then
    echo "The app registration 'hha-dashboard-api-prod' was not found."
    echo "Create it:"
  else
    echo "Reproducible create command for 'hha-dashboard-api-prod':"
  fi
  echo ""
  cat <<'  EOF'
  az ad app create \
    --display-name "hha-dashboard-api-prod" \
    --identifier-uris "api://hha-dashboard-api-prod" \
    --required-resource-accesses '[{
      "resourceAppId": "00000003-0000-0000-c000-000000000000",
      "resourceAccess": [{
        "id": "e1fe6dd8-ba31-4d61-89e7-88639da4683d",
        "type": "Scope"
      }]
    }]'
  EOF
  echo ""
fi

# --- Entra security groups ---
if [[ ${#MISSING_GROUPS[@]} -gt 0 ]] || $MODE_CREATE_HELPERS; then
  if [[ ${#MISSING_GROUPS[@]} -gt 0 ]]; then
    echo "To create the missing Entra security groups:"
  else
    echo "Reproducible create commands for all 7 Entra security groups:"
  fi
  echo ""

  declare -A GROUP_NICKNAMES
  GROUP_NICKNAMES["HHA-Dashboard-Admin"]="hha-dashboard-admin"
  GROUP_NICKNAMES["HHA-Dashboard-Exec"]="hha-dashboard-exec"
  GROUP_NICKNAMES["HHA-Dashboard-CompViewer"]="hha-dashboard-compviewer"
  GROUP_NICKNAMES["HHA-Dashboard-Owner-Ops"]="hha-dashboard-owner-ops"
  GROUP_NICKNAMES["HHA-Dashboard-Owner-Finance"]="hha-dashboard-owner-finance"
  GROUP_NICKNAMES["HHA-Dashboard-Owner-Clinical"]="hha-dashboard-owner-clinical"
  GROUP_NICKNAMES["HHA-Dashboard-Owner-HR"]="hha-dashboard-owner-hr"

  for var_name in "${ENTRA_VAR_ORDER[@]}"; do
    display="${ENTRA_GROUP_DISPLAY_NAMES[$var_name]}"
    val="${ENTRA_GROUPS[$var_name]}"
    nickname="${GROUP_NICKNAMES[$display]}"
    if [[ -z "$val" ]] || $MODE_CREATE_HELPERS; then
      echo "  az ad group create --display-name \"${display}\" --mail-nickname \"${nickname}\""
    fi
  done

  if [[ ${#MISSING_GROUPS[@]} -gt 0 ]]; then
    echo ""
    echo "After creating the groups, re-run this script to pick up the new IDs."
  fi
  echo ""
fi

# ---------------------------------------------------------------------------
# Final env block
# ---------------------------------------------------------------------------
echo ""
info "=== Final env block ==="
echo ""

emit_env_value() {
  local name="$1"
  local value="$2"
  if [[ -n "$value" ]]; then
    echo "  ${name}=${value}"
  else
    echo "  ${name}=<MISSING>"
  fi
}

emit_env_value "AZURE_SUBSCRIPTION_ID"   "$AZURE_SUBSCRIPTION_ID"
emit_env_value "AZURE_TENANT_ID"         "$AZURE_TENANT_ID"
emit_env_value "AZURE_CLIENT_ID"         "$AZURE_CLIENT_ID"
emit_env_value "AZURE_TENANT_ID_FOR_KV"  "$AZURE_TENANT_ID_FOR_KV"
emit_env_value "AZURE_API_CLIENT_ID"     "$AZURE_API_CLIENT_ID"

for var_name in "${ENTRA_VAR_ORDER[@]}"; do
  emit_env_value "$var_name" "${ENTRA_GROUPS[$var_name]}"
done

emit_env_value "DEPLOYER_WORKSTATION_IP" "$DEPLOYER_WORKSTATION_IP"
emit_env_value "CUSTOM_DOMAIN"           "$CUSTOM_DOMAIN"
emit_env_value "SPONSOR_EMAIL"           "$SPONSOR_EMAIL"

echo ""

if ! $MODE_WRITE_GH; then
  echo "If you'd like to push these to GitHub repo Variables/Secrets:"
  echo "  bash scripts/azure_discover.sh --write-gh-secrets"
  echo ""
fi

# ---------------------------------------------------------------------------
# --write-gh-secrets mode
# ---------------------------------------------------------------------------
if $MODE_WRITE_GH; then
  echo ""
  info "=== GitHub Variables + local overrides file ==="
  echo ""

  # GitHub repo variables (4 values — non-secret, viewable in workflow logs)
  GH_VARS=(
    "AZURE_CLIENT_ID:${AZURE_CLIENT_ID}"
    "AZURE_TENANT_ID:${AZURE_TENANT_ID}"
    "AZURE_SUBSCRIPTION_ID:${AZURE_SUBSCRIPTION_ID}"
    "AZURE_TENANT_ID_FOR_KV:${AZURE_TENANT_ID_FOR_KV}"
  )

  echo "The following GitHub repo Variables will be set:"
  for pair in "${GH_VARS[@]}"; do
    name="${pair%%:*}"
    value="${pair#*:}"
    if [[ -n "$value" ]]; then
      echo "  gh variable set ${name} --body \"$(redact "$value")\""
    else
      echo "  ${name} — SKIPPED (no value)"
    fi
  done

  echo ""

  OVERRIDES_FILE="infra/env/.deploy-overrides.local.env"
  echo "The following values will be written to ${OVERRIDES_FILE}:"
  echo "  AZURE_API_CLIENT_ID"
  for var_name in "${ENTRA_VAR_ORDER[@]}"; do
    echo "  ${var_name}"
  done
  echo ""

  # Confirmation prompt
  if [[ -t 0 ]]; then
    read -r -p "Proceed? [y/N] " CONFIRM
    if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
      echo "Aborted."
      exit 0
    fi
  else
    die "--write-gh-secrets requires an interactive terminal for confirmation."
  fi

  echo ""

  # Set GitHub repo variables
  GH_REPO="DandaAkhilReddy/hhadashboard"
  for pair in "${GH_VARS[@]}"; do
    name="${pair%%:*}"
    value="${pair#*:}"
    if [[ -n "$value" ]]; then
      if gh variable set "$name" --body "$value" --repo "$GH_REPO" 2>/dev/null; then
        ok "gh variable set ${name}"
      else
        fail "gh variable set ${name} — command failed"
      fi
    else
      warn "Skipping ${name} — no value discovered"
    fi
  done

  echo ""

  # Write local overrides file (Entra group IDs + API client ID)
  # Ensure the directory exists
  mkdir -p infra/env

  {
    echo "# Generated by scripts/azure_discover.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "# Source this file before running az deployment group create."
    echo "# DO NOT COMMIT — already in .gitignore."
    echo ""
    if [[ -n "$AZURE_API_CLIENT_ID" ]]; then
      echo "AZURE_API_CLIENT_ID=${AZURE_API_CLIENT_ID}"
    else
      echo "# AZURE_API_CLIENT_ID=<MISSING>"
    fi
    for var_name in "${ENTRA_VAR_ORDER[@]}"; do
      val="${ENTRA_GROUPS[$var_name]}"
      if [[ -n "$val" ]]; then
        echo "${var_name}=${val}"
      else
        echo "# ${var_name}=<MISSING>"
      fi
    done
  } > "$OVERRIDES_FILE"

  ok "Wrote ${OVERRIDES_FILE}"
  echo ""

  info "=== Write complete ==="
  echo ""
  echo "Next steps:"
  echo "  1. If any values were MISSING above, create the resources and re-run."
  echo "  2. Source the overrides file before deploying:"
  echo "       source ${OVERRIDES_FILE}"
  echo "  3. Trigger the deploy workflow:"
  echo "       gh workflow run deploy-dev.yml  --ref feat/azure-deploy-push"
  echo "       gh workflow run deploy-prod.yml --ref main"
  echo ""
fi
