#!/usr/bin/env bash
#
# census_seed.sh — seed (or rotate) the single census-portal credential.
#
# Why a separate script:
#   The portal credential is NOT in Key Vault — it's an app-managed row in
#   `auth.census_credentials` because the value is consumed by the API's
#   Python code (argon2 verify), not by App Service KV references.
#
# Usage:
#   bash infra/census_seed.sh --email crystal@hhamedicine.com --password '...'
#   bash infra/census_seed.sh --email crystal@hhamedicine.com --rotate-random
#
# Idempotency:
#   - First run: inserts the row.
#   - Re-run with same email + same password: no-op.
#   - Re-run with same email but different password: NO-OP unless --rotate.
#   - Re-run with different email: errors unless --rotate.
#
# This script wraps `scripts/seed_census_credential.py` — the actual logic
# (argon2 hashing + DB write) lives there because the api package owns the
# CensusCredential model. The bash wrapper just handles arg parsing,
# password generation, and uv invocation.

set -euo pipefail

EMAIL=""
PASSWORD=""
ROTATE=""
RANDOM_PASSWORD=""

while [ $# -gt 0 ]; do
  case "$1" in
    --email) EMAIL="$2"; shift 2 ;;
    --password) PASSWORD="$2"; shift 2 ;;
    --rotate) ROTATE="--rotate"; shift ;;
    --rotate-random) ROTATE="--rotate"; RANDOM_PASSWORD="1"; shift ;;
    -h|--help)
      grep '^#' "$0" | grep -v '^#!' | sed 's/^# //; s/^#//'
      exit 0 ;;
    *)
      echo "unknown arg: $1" >&2
      exit 2 ;;
  esac
done

if [ -z "$EMAIL" ]; then
  echo "ERROR: --email is required" >&2
  exit 2
fi

if [ -n "$RANDOM_PASSWORD" ]; then
  PASSWORD=$(openssl rand -base64 18)
  echo "[info] generated random password (will be printed once below)"
fi

if [ -z "$PASSWORD" ]; then
  echo "ERROR: --password is required (or use --rotate-random)" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$REPO_ROOT/api"
uv run python ../scripts/seed_census_credential.py \
  --email "$EMAIL" \
  --password "$PASSWORD" \
  ${ROTATE}

if [ -n "$RANDOM_PASSWORD" ]; then
  echo
  echo "[info] generated password (give this to ops, then forget it):"
  echo "       $PASSWORD"
fi
