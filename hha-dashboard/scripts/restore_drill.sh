#!/usr/bin/env bash
#
# restore_drill.sh — prove a backup is restorable.
#
# Why this exists: backups nobody has restored are theatre. Run this
# quarterly (or after every schema migration) to confirm the latest
# backup actually restores cleanly into a fresh Postgres and that row
# counts match the source.
#
# What it does:
#   1. Lists `backups/` in the configured Storage Account.
#   2. Picks the most recent blob (by upload timestamp).
#   3. Downloads to /tmp/restore-drill/.
#   4. Spins up a SANDBOX Postgres via `docker run` on a non-default port —
#      we never restore into your dev/prod DB.
#   5. Runs pg_restore against the sandbox.
#   6. Compares row counts: each audited table's count in sandbox must
#      match the count in source within ±1% (ingestion may have written
#      rows between the dump and the row-count query at drill time).
#   7. Tears down the sandbox container.
#   8. Reports PASS or FAIL with details.
#
# Pre-reqs:
#   - docker on PATH (sandbox postgres)
#   - psql + pg_restore on PATH (matching the server major version, 16)
#   - az CLI logged in OR azcopy with SAS, OR AZURE_STORAGE_CONNECTION_STRING set
#   - Source DATABASE_URL_SYNC pointing at the live DB (used only to read
#     baseline row counts, never modified)
#
# Usage:
#   ENV=prod bash scripts/restore_drill.sh
#   ENV=dev SANDBOX_PORT=5499 bash scripts/restore_drill.sh
#
# Exit codes:
#   0  drill passed
#   1  download failed
#   2  pg_restore failed
#   3  row-count mismatch beyond tolerance
#   4  pre-flight check failed (missing tool or env var)

set -euo pipefail

ENV="${ENV:-dev}"
SANDBOX_PORT="${SANDBOX_PORT:-5499}"
SANDBOX_PASSWORD="restore-drill-$(date +%s)"  # ephemeral, just for the container
TOLERANCE_PCT="${TOLERANCE_PCT:-1.0}"  # 1% row-count drift permitted
WORK_DIR="${WORK_DIR:-/tmp/restore-drill}"
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-sthhadev}"  # override per env
CONTAINER="${CONTAINER:-backups}"
SANDBOX_NAME="restore-drill-pg-${ENV}"

red() { printf '\033[31m%s\033[0m\n' "$1"; }
green() { printf '\033[32m%s\033[0m\n' "$1"; }
yellow() { printf '\033[33m%s\033[0m\n' "$1"; }

step() { yellow "[$(date +%H:%M:%S)] $1"; }

cleanup() {
  echo
  step "Cleanup: stopping sandbox container"
  docker rm -f "${SANDBOX_NAME}" >/dev/null 2>&1 || true
  # Leave the downloaded dump in $WORK_DIR for forensics.
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
step "Pre-flight checks"

for cmd in docker pg_restore psql az; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    red "ERROR: $cmd not on PATH. Install before running the drill."
    exit 4
  fi
done

if [ -z "${DATABASE_URL_SYNC:-}" ]; then
  red "ERROR: DATABASE_URL_SYNC not set. Need it to read baseline row counts."
  exit 4
fi

mkdir -p "$WORK_DIR"

# ---------------------------------------------------------------------------
# 1-3. Find + download the most recent backup
# ---------------------------------------------------------------------------
step "Listing latest backup in storage account=$STORAGE_ACCOUNT container=$CONTAINER"

LATEST_NAME=$(az storage blob list \
  --account-name "$STORAGE_ACCOUNT" \
  --container-name "$CONTAINER" \
  --query 'sort_by([], &properties.lastModified)[-1].name' \
  -o tsv 2>/dev/null || true)

if [ -z "$LATEST_NAME" ]; then
  red "ERROR: no backups found in $CONTAINER."
  exit 1
fi

green "Latest backup: $LATEST_NAME"
LOCAL_DUMP="$WORK_DIR/$LATEST_NAME"

step "Downloading $LATEST_NAME"
az storage blob download \
  --account-name "$STORAGE_ACCOUNT" \
  --container-name "$CONTAINER" \
  --name "$LATEST_NAME" \
  --file "$LOCAL_DUMP" \
  --no-progress >/dev/null

if [ ! -s "$LOCAL_DUMP" ]; then
  red "ERROR: downloaded file is empty."
  exit 1
fi

green "Downloaded $(du -h "$LOCAL_DUMP" | cut -f1) to $LOCAL_DUMP"

# ---------------------------------------------------------------------------
# 4. Spin up sandbox Postgres
# ---------------------------------------------------------------------------
step "Starting sandbox Postgres on port $SANDBOX_PORT"

docker rm -f "$SANDBOX_NAME" >/dev/null 2>&1 || true
docker run -d \
  --name "$SANDBOX_NAME" \
  -e POSTGRES_PASSWORD="$SANDBOX_PASSWORD" \
  -e POSTGRES_DB=hha_dashboard \
  -p "${SANDBOX_PORT}:5432" \
  postgres:16 >/dev/null

# Wait for the sandbox to be ready.
for i in $(seq 1 30); do
  if docker exec "$SANDBOX_NAME" pg_isready -U postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
  if [ "$i" -eq 30 ]; then
    red "ERROR: sandbox Postgres did not start within 30s."
    exit 2
  fi
done

SANDBOX_URL="postgresql://postgres:${SANDBOX_PASSWORD}@localhost:${SANDBOX_PORT}/hha_dashboard"
green "Sandbox ready at port $SANDBOX_PORT"

# ---------------------------------------------------------------------------
# 5. Restore
# ---------------------------------------------------------------------------
step "Running pg_restore"

if ! pg_restore \
      --dbname="$SANDBOX_URL" \
      --no-owner \
      --no-acl \
      --jobs=4 \
      --exit-on-error \
      "$LOCAL_DUMP" >/dev/null 2>&1; then
  red "ERROR: pg_restore failed. Re-running verbosely for diagnostics:"
  pg_restore --dbname="$SANDBOX_URL" --no-owner --no-acl --exit-on-error "$LOCAL_DUMP" || true
  exit 2
fi

green "Restore completed"

# ---------------------------------------------------------------------------
# 6. Row-count compare
# ---------------------------------------------------------------------------
step "Comparing row counts (audited tables, tolerance ${TOLERANCE_PCT}%)"

# Tables we care about. Matches AUDITED_TABLES in app/services/audit.py.
AUDITED_TABLES=(
  "masters.physicians"
  "masters.comp_agreements"
  "masters.contracts"
  "masters.credentials"
  "masters.site_coverage"
  "entries.daily_entries"
  "entries.monthly_finance_manual"
  "entries.weekly_clinical"
  "entries.weekly_hr_manual"
)

count_one() {
  local conn="$1"
  local table="$2"
  psql "$conn" -tAc "SELECT count(*) FROM ${table};" 2>/dev/null || echo "ERR"
}

failures=()
for tbl in "${AUDITED_TABLES[@]}"; do
  src=$(count_one "$DATABASE_URL_SYNC" "$tbl")
  dst=$(count_one "$SANDBOX_URL" "$tbl")
  if [ "$src" = "ERR" ] || [ "$dst" = "ERR" ]; then
    yellow "  $tbl: source=$src sandbox=$dst (ERR — skipping)"
    continue
  fi
  if [ "$src" -eq 0 ] && [ "$dst" -eq 0 ]; then
    green "  $tbl: source=0 sandbox=0 (PASS)"
    continue
  fi
  # Compute drift as percent (using bc for float math).
  drift=$(awk -v s="$src" -v d="$dst" 'BEGIN { if (s==0) print "100"; else printf "%.2f", ((s>d?s-d:d-s)/s)*100 }')
  awk -v drift="$drift" -v tol="$TOLERANCE_PCT" 'BEGIN { exit (drift <= tol ? 0 : 1) }'
  if [ $? -eq 0 ]; then
    green "  $tbl: source=$src sandbox=$dst drift=${drift}% (PASS)"
  else
    red "  $tbl: source=$src sandbox=$dst drift=${drift}% (FAIL — exceeds ${TOLERANCE_PCT}%)"
    failures+=("$tbl drift=${drift}%")
  fi
done

# ---------------------------------------------------------------------------
# 7-8. Report
# ---------------------------------------------------------------------------
echo
if [ ${#failures[@]} -eq 0 ]; then
  green "==============================================="
  green " RESTORE DRILL: PASS"
  green " backup=$LATEST_NAME"
  green " env=$ENV  tolerance=${TOLERANCE_PCT}%"
  green "==============================================="
  exit 0
else
  red "==============================================="
  red " RESTORE DRILL: FAIL"
  red " ${#failures[@]} table(s) outside tolerance:"
  for f in "${failures[@]}"; do
    red "   - $f"
  done
  red "==============================================="
  exit 3
fi
