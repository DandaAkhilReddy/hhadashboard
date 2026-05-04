#!/usr/bin/env bash
# Push Azure-* values to GitHub repo Variables and generate the prod Postgres
# admin password as a Secret. Run after `azure_create_missing.sh`.
#
# Usage: bash scripts/push_gh_vars.sh

set -euo pipefail

REPO="DandaAkhilReddy/hhadashboard"

echo "=== Setting GitHub repo Variables (visible, not secret) ==="
gh variable set AZURE_CLIENT_ID --body "d559c862-14b9-4ded-8440-14cbc9e5aaeb" --repo "$REPO"
echo "  ✓ AZURE_CLIENT_ID"
gh variable set AZURE_TENANT_ID --body "76596b76-3c41-40ee-a8a3-bf6930301838" --repo "$REPO"
echo "  ✓ AZURE_TENANT_ID"
gh variable set AZURE_SUBSCRIPTION_ID --body "5801224b-ab00-4482-ac95-4ad2ce6bc61e" --repo "$REPO"
echo "  ✓ AZURE_SUBSCRIPTION_ID"

echo ""
echo "=== Generating Postgres admin password (32 chars, random) ==="
PG_PW=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)
echo ""
echo "  Postgres admin password: $PG_PW"
echo ""
echo "  ⚠ SAVE THIS NOW (1Password / Bitwarden) — printed once, never again."
echo "  Also stored as repo secret POSTGRES_ADMIN_PASSWORD_PROD and will be"
echo "  written to Key Vault by infra/bootstrap.sh after Bicep apply."
echo ""

echo "=== Pushing as repo Secret POSTGRES_ADMIN_PASSWORD_PROD ==="
echo -n "$PG_PW" | gh secret set POSTGRES_ADMIN_PASSWORD_PROD --repo "$REPO"
echo "  ✓ secret set"

echo ""
echo "=== Verifying ==="
echo "Variables on $REPO:"
gh variable list --repo "$REPO"
echo ""
echo "Secrets on $REPO (names only — values are write-only):"
gh secret list --repo "$REPO"

echo ""
echo "Done. Ready to trigger deploy-prod.yml."
