#!/usr/bin/env bash
# scripts/smoke_deploy.sh
#
# End-to-end smoke check for any deployed HHA Dashboard environment.
# Covers the Phase 1 census portal (PR #44) — auth surface, session lifecycle,
# and the Phase 1 field whitelist (site_id + census + timestamps only).
#
# Usage: bash scripts/smoke_deploy.sh <api_base_url> <portal_email> <portal_password> [--cleanup]
# e.g.:  bash scripts/smoke_deploy.sh https://app-hha-api-prod.azurewebsites.net portal@hhamedicine.com 'TempCensus2026!'
#        bash scripts/smoke_deploy.sh http://localhost:8000 portal@hhamedicine.com TempCensus2026! --cleanup

set -euo pipefail

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <api_base_url> <portal_email> <portal_password> [--cleanup]" >&2
  exit 1
fi

API_BASE="${1%/}"   # strip trailing slash
EMAIL="$2"
PASSWORD="$3"
DO_CLEANUP=0
if [[ "${4:-}" == "--cleanup" ]]; then
  DO_CLEANUP=1
fi

# ---------------------------------------------------------------------------
# Color helpers — only when stdout is a tty
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
  GREEN='\033[0;32m'
  RED='\033[0;31m'
  BOLD='\033[1m'
  RESET='\033[0m'
else
  GREEN=''
  RED=''
  BOLD=''
  RESET=''
fi

pass() { printf "${GREEN}✓ %s${RESET}\n" "$*" >&2; }
fail() { printf "${RED}✗ FAILED: %s${RESET}\n" "$*" >&2; }
banner() { printf "\n${BOLD}%s${BOLD}\n" "$*" >&2; }

# ---------------------------------------------------------------------------
# JSON parsing helpers — prefer jq, fall back to Python (always available),
# then a best-effort sed approach for environments with neither.
# ---------------------------------------------------------------------------
USE_JQ=0
USE_PYTHON=0
if command -v jq &>/dev/null; then
  USE_JQ=1
elif command -v python3 &>/dev/null || command -v python &>/dev/null; then
  USE_PYTHON=1
  _PY="$(command -v python3 2>/dev/null || command -v python)"
fi

json_field() {
  # json_field <json_string> <field>  → prints the value, empty on missing
  local json="$1" field="$2"
  if [[ $USE_JQ -eq 1 ]]; then
    printf '%s' "$json" | jq -r ".${field} // empty"
  elif [[ $USE_PYTHON -eq 1 ]]; then
    printf '%s' "$json" | "$_PY" -c \
      "import sys,json; d=json.load(sys.stdin); v=d.get('${field}'); print('' if v is None else v)"
  else
    # Basic sed fallback — handles simple string/number top-level values.
    printf '%s' "$json" \
      | sed 's/.*"'"${field}"'"\s*:\s*"\([^"]*\)".*/\1/;t end;s/.*"'"${field}"'"\s*:\s*\([0-9][0-9]*\).*/\1/;t end;d;:end'
  fi
}

json_array_length() {
  # json_array_length <json_string> <array_field>  → integer count
  local json="$1" field="$2"
  if [[ $USE_JQ -eq 1 ]]; then
    printf '%s' "$json" | jq ".${field} | length"
  elif [[ $USE_PYTHON -eq 1 ]]; then
    printf '%s' "$json" | "$_PY" -c \
      "import sys,json; d=json.load(sys.stdin); print(len(d.get('${field}', [])))"
  else
    # Count occurrences of "site_id" as a proxy for array length.
    printf '%s' "$json" | tr ',' '\n' | grep -c '"site_id"' | tr -d ' '
  fi
}

# ---------------------------------------------------------------------------
# Temp cookie jar — cleaned up on exit
# ---------------------------------------------------------------------------
COOKIE_JAR="$(mktemp /tmp/hha_smoke_cookies.XXXXXX)"
trap 'rm -f "$COOKIE_JAR"' EXIT

# ---------------------------------------------------------------------------
# Helper: perform a curl call, capture status + body, emit on bad status
# ---------------------------------------------------------------------------
# do_curl <expected_status> <step_name> [extra curl args...]
# Sets globals: LAST_STATUS, LAST_BODY
do_curl() {
  local expected_status="$1" step_name="$2"
  shift 2

  # Write status code to a temp file so we can capture it alongside the body
  local status_file
  status_file="$(mktemp /tmp/hha_smoke_status.XXXXXX)"
  trap 'rm -f "$status_file"' RETURN

  # -s = silent, -S = show errors, -w = write status, -o = body to stdout
  LAST_BODY="$(curl -sS -w '' -o /dev/null --write-out '' "$@" \
    --silent --output /dev/null 2>/dev/null || true)"

  # Re-run capturing body (-o -) and status separately
  LAST_BODY="$(curl -sS \
    -w "%{http_code}" \
    -o /tmp/hha_smoke_body.tmp \
    "$@" 2>&1 | tail -c 3 || true)"

  # Cleaner approach: capture body and status in one shot
  LAST_STATUS="$(curl -sS \
    -w "\n%{http_code}" \
    "$@" 2>/tmp/hha_smoke_curl_err.tmp | tee /tmp/hha_smoke_body.tmp | tail -1)"
  LAST_BODY="$(head -n -1 /tmp/hha_smoke_body.tmp 2>/dev/null || cat /tmp/hha_smoke_body.tmp)"

  # If status doesn't match expected, print diagnostics and exit 1
  if [[ "$LAST_STATUS" != "$expected_status" ]]; then
    local url=""
    # Find the URL arg (last positional that looks like http)
    for arg in "$@"; do
      if [[ "$arg" == http* ]]; then url="$arg"; fi
    done
    {
      fail "${step_name}"
      printf "  URL    : %s\n" "$url"
      printf "  Status : %s (expected %s)\n" "$LAST_STATUS" "$expected_status"
      printf "  Body   : %s\n" "$LAST_BODY"
    } >&2
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Smoke steps
# ---------------------------------------------------------------------------

banner "HHA Census Portal — Smoke Check"
printf "  Target : %s\n" "$API_BASE" >&2
printf "  User   : %s\n" "$EMAIL" >&2
printf "  Date   : %s\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
printf "\n" >&2

# ---------------------------------------------------------------------------
# Step 1 — Health check
# ---------------------------------------------------------------------------
do_curl "200" "Step 1: /health" \
  "${API_BASE}/health"
pass "/health"

# ---------------------------------------------------------------------------
# Step 2 — Login validation (empty body → 422)
# ---------------------------------------------------------------------------
do_curl "422" "Step 2: login validation (empty body)" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{}' \
  "${API_BASE}/api/v1/census-portal/login"
pass "login validation"

# ---------------------------------------------------------------------------
# Step 3 — Real portal login → 200 + census_session cookie
# ---------------------------------------------------------------------------
# Use -c to write cookie, -b to read (omitted here; cookie jar used for all
# subsequent authenticated requests).
LAST_STATUS="$(curl -sS \
  -w "\n%{http_code}" \
  -c "$COOKIE_JAR" \
  -X POST \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}" \
  "${API_BASE}/api/v1/census-portal/login" \
  2>/tmp/hha_smoke_curl_err.tmp | tee /tmp/hha_smoke_body.tmp | tail -1)"
LAST_BODY="$(head -n -1 /tmp/hha_smoke_body.tmp 2>/dev/null || cat /tmp/hha_smoke_body.tmp)"

if [[ "$LAST_STATUS" != "200" ]]; then
  fail "Step 3: login"
  printf "  URL    : %s/api/v1/census-portal/login\n" "$API_BASE" >&2
  printf "  Status : %s (expected 200)\n" "$LAST_STATUS" >&2
  printf "  Body   : %s\n" "$LAST_BODY" >&2
  exit 1
fi

# Verify cookie was set
if ! grep -q "census_session" "$COOKIE_JAR" 2>/dev/null; then
  fail "Step 3: login — census_session cookie not set in jar"
  exit 1
fi

# Extract first site_id from login response for later use
LOGIN_BODY="$LAST_BODY"
if [[ $USE_JQ -eq 1 ]]; then
  FIRST_SITE_ID="$(printf '%s' "$LOGIN_BODY" | jq '.sites[0].site_id')"
elif [[ $USE_PYTHON -eq 1 ]]; then
  FIRST_SITE_ID="$(printf '%s' "$LOGIN_BODY" | "$_PY" -c \
    "import sys,json; d=json.load(sys.stdin); print(d['sites'][0]['site_id'])")"
else
  # Portable sed: grab first numeric value after "site_id":
  FIRST_SITE_ID="$(printf '%s' "$LOGIN_BODY" | tr '{' '\n' | sed -n 's/.*"site_id"\s*:\s*\([0-9][0-9]*\).*/\1/p' | head -1)"
fi

if [[ -z "$FIRST_SITE_ID" || "$FIRST_SITE_ID" == "null" ]]; then
  fail "Step 3: login — could not extract site_id from login response"
  printf "  Body: %s\n" "$LOGIN_BODY" >&2
  exit 1
fi
pass "portal login (cookie issued, first site_id=${FIRST_SITE_ID})"

# ---------------------------------------------------------------------------
# Step 4 — Session check → 200 + email matches
# ---------------------------------------------------------------------------
LAST_STATUS="$(curl -sS \
  -w "\n%{http_code}" \
  -b "$COOKIE_JAR" \
  "${API_BASE}/api/v1/census-portal/session" \
  2>/tmp/hha_smoke_curl_err.tmp | tee /tmp/hha_smoke_body.tmp | tail -1)"
LAST_BODY="$(head -n -1 /tmp/hha_smoke_body.tmp 2>/dev/null || cat /tmp/hha_smoke_body.tmp)"

if [[ "$LAST_STATUS" != "200" ]]; then
  fail "Step 4: session check"
  printf "  Status : %s (expected 200)\n" "$LAST_STATUS" >&2
  printf "  Body   : %s\n" "$LAST_BODY" >&2
  exit 1
fi

SESSION_EMAIL="$(json_field "$LAST_BODY" "email")"
if [[ "$SESSION_EMAIL" != "$EMAIL" ]]; then
  fail "Step 4: session check — email mismatch (got '${SESSION_EMAIL}', expected '${EMAIL}')"
  exit 1
fi
pass "session valid (email=${SESSION_EMAIL})"

# ---------------------------------------------------------------------------
# Step 5 — Sites prefill → JSON with entry_date + sites array
# ---------------------------------------------------------------------------
LAST_STATUS="$(curl -sS \
  -w "\n%{http_code}" \
  -b "$COOKIE_JAR" \
  "${API_BASE}/api/v1/census-portal/sites" \
  2>/tmp/hha_smoke_curl_err.tmp | tee /tmp/hha_smoke_body.tmp | tail -1)"
LAST_BODY="$(head -n -1 /tmp/hha_smoke_body.tmp 2>/dev/null || cat /tmp/hha_smoke_body.tmp)"

if [[ "$LAST_STATUS" != "200" ]]; then
  fail "Step 5: sites prefill"
  printf "  Status : %s (expected 200)\n" "$LAST_STATUS" >&2
  printf "  Body   : %s\n" "$LAST_BODY" >&2
  exit 1
fi

# Validate required fields exist
ENTRY_DATE="$(json_field "$LAST_BODY" "entry_date")"
if [[ -z "$ENTRY_DATE" || "$ENTRY_DATE" == "null" ]]; then
  fail "Step 5: sites prefill — missing entry_date"
  printf "  Body: %s\n" "$LAST_BODY" >&2
  exit 1
fi
SITE_COUNT="$(json_array_length "$LAST_BODY" "sites")"
if [[ -z "$SITE_COUNT" || "$SITE_COUNT" -lt 1 ]]; then
  fail "Step 5: sites prefill — sites array empty or missing"
  printf "  Body: %s\n" "$LAST_BODY" >&2
  exit 1
fi
pass "sites prefill (${SITE_COUNT} facilities, entry_date=${ENTRY_DATE})"

# ---------------------------------------------------------------------------
# Step 6 — Summary → total_census, facilities_reported, facilities_missing, last_updated_at
# ---------------------------------------------------------------------------
LAST_STATUS="$(curl -sS \
  -w "\n%{http_code}" \
  -b "$COOKIE_JAR" \
  "${API_BASE}/api/v1/census-portal/summary" \
  2>/tmp/hha_smoke_curl_err.tmp | tee /tmp/hha_smoke_body.tmp | tail -1)"
LAST_BODY="$(head -n -1 /tmp/hha_smoke_body.tmp 2>/dev/null || cat /tmp/hha_smoke_body.tmp)"

if [[ "$LAST_STATUS" != "200" ]]; then
  fail "Step 6: summary"
  printf "  Status : %s (expected 200)\n" "$LAST_STATUS" >&2
  printf "  Body   : %s\n" "$LAST_BODY" >&2
  exit 1
fi

PRE_TOTAL="$(json_field "$LAST_BODY" "total_census")"
PRE_REPORTED="$(json_field "$LAST_BODY" "facilities_reported")"
MISSING="$(json_field "$LAST_BODY" "facilities_missing")"
LAST_UPDATED="$(json_field "$LAST_BODY" "last_updated_at")"

for field_name in total_census facilities_reported facilities_missing; do
  val="$(json_field "$LAST_BODY" "$field_name")"
  if [[ -z "$val" && "$val" != "0" ]]; then
    # Accept 0 as valid
    :
  fi
done

# Check the four required keys exist at all (allow null for last_updated_at)
if [[ $USE_JQ -eq 1 ]]; then
  for key in total_census facilities_reported facilities_missing; do
    kval="$(printf '%s' "$LAST_BODY" | jq "has(\"${key}\")")"
    if [[ "$kval" != "true" ]]; then
      fail "Step 6: summary — missing key '${key}'"
      printf "  Body: %s\n" "$LAST_BODY" >&2
      exit 1
    fi
  done
fi

{
  printf "  total_census        : %s\n" "$PRE_TOTAL"
  printf "  facilities_reported : %s\n" "$PRE_REPORTED"
  printf "  facilities_missing  : %s\n" "$MISSING"
  printf "  last_updated_at     : %s\n" "${LAST_UPDATED:-null}"
} >&2
pass "summary read"

# ---------------------------------------------------------------------------
# Step 7 — Save smoke census (site_id=FIRST_SITE_ID, census=42)
# ---------------------------------------------------------------------------
TODAY="$(date -u +%Y-%m-%d)"
CENSUS_PAYLOAD="{\"entry_date\":\"${TODAY}\",\"rows\":[{\"site_id\":${FIRST_SITE_ID},\"census\":42}]}"

LAST_STATUS="$(curl -sS \
  -w "\n%{http_code}" \
  -b "$COOKIE_JAR" \
  -X POST \
  -H "Content-Type: application/json" \
  -d "$CENSUS_PAYLOAD" \
  "${API_BASE}/api/v1/census-portal/daily-census" \
  2>/tmp/hha_smoke_curl_err.tmp | tee /tmp/hha_smoke_body.tmp | tail -1)"
LAST_BODY="$(head -n -1 /tmp/hha_smoke_body.tmp 2>/dev/null || cat /tmp/hha_smoke_body.tmp)"

if [[ "$LAST_STATUS" != "200" ]]; then
  fail "Step 7: save census"
  printf "  Status : %s (expected 200)\n" "$LAST_STATUS" >&2
  printf "  Body   : %s\n" "$LAST_BODY" >&2
  exit 1
fi

# Response is an array; grab entered_at from first element
if [[ $USE_JQ -eq 1 ]]; then
  ENTERED_AT="$(printf '%s' "$LAST_BODY" | jq -r '.[0].entered_at // empty')"
elif [[ $USE_PYTHON -eq 1 ]]; then
  ENTERED_AT="$(printf '%s' "$LAST_BODY" | "$_PY" -c \
    "import sys,json; d=json.load(sys.stdin); print(d[0].get('entered_at',''))")"
else
  ENTERED_AT="$(printf '%s' "$LAST_BODY" | tr '{' '\n' | sed -n 's/.*"entered_at"\s*:\s*"\([^"]*\)".*/\1/p' | head -1)"
fi

if [[ -z "$ENTERED_AT" || "$ENTERED_AT" == "null" ]]; then
  fail "Step 7: save census — entered_at missing in response"
  printf "  Body: %s\n" "$LAST_BODY" >&2
  exit 1
fi
pass "saved census=42 at ${ENTERED_AT}"

# ---------------------------------------------------------------------------
# Step 8 — Re-read summary; verify total_census >= 42, facilities_reported >= 1
# ---------------------------------------------------------------------------
LAST_STATUS="$(curl -sS \
  -w "\n%{http_code}" \
  -b "$COOKIE_JAR" \
  "${API_BASE}/api/v1/census-portal/summary" \
  2>/tmp/hha_smoke_curl_err.tmp | tee /tmp/hha_smoke_body.tmp | tail -1)"
LAST_BODY="$(head -n -1 /tmp/hha_smoke_body.tmp 2>/dev/null || cat /tmp/hha_smoke_body.tmp)"

if [[ "$LAST_STATUS" != "200" ]]; then
  fail "Step 8: summary post-write"
  printf "  Status : %s (expected 200)\n" "$LAST_STATUS" >&2
  printf "  Body   : %s\n" "$LAST_BODY" >&2
  exit 1
fi

POST_TOTAL="$(json_field "$LAST_BODY" "total_census")"
POST_REPORTED="$(json_field "$LAST_BODY" "facilities_reported")"

if [[ -z "$POST_TOTAL" ]]; then POST_TOTAL=0; fi
if [[ -z "$POST_REPORTED" ]]; then POST_REPORTED=0; fi

if [[ "$POST_TOTAL" -lt 42 ]]; then
  fail "Step 8: summary reflects write — total_census=${POST_TOTAL} (expected >= 42)"
  exit 1
fi
if [[ "$POST_REPORTED" -lt 1 ]]; then
  fail "Step 8: summary reflects write — facilities_reported=${POST_REPORTED} (expected >= 1)"
  exit 1
fi
pass "summary reflects write (total_census=${POST_TOTAL}, facilities_reported=${POST_REPORTED})"

# ---------------------------------------------------------------------------
# Step 9 — Logout → 200
# ---------------------------------------------------------------------------
LAST_STATUS="$(curl -sS \
  -w "\n%{http_code}" \
  -b "$COOKIE_JAR" \
  -c "$COOKIE_JAR" \
  -X POST \
  "${API_BASE}/api/v1/census-portal/logout" \
  2>/tmp/hha_smoke_curl_err.tmp | tee /tmp/hha_smoke_body.tmp | tail -1)"
LAST_BODY="$(head -n -1 /tmp/hha_smoke_body.tmp 2>/dev/null || cat /tmp/hha_smoke_body.tmp)"

if [[ "$LAST_STATUS" != "200" ]]; then
  fail "Step 9: logout"
  printf "  Status : %s (expected 200)\n" "$LAST_STATUS" >&2
  printf "  Body   : %s\n" "$LAST_BODY" >&2
  exit 1
fi
pass "logout"

# ---------------------------------------------------------------------------
# Step 10 — Session check after logout → 401
# ---------------------------------------------------------------------------
LAST_STATUS="$(curl -sS \
  -w "\n%{http_code}" \
  -b "$COOKIE_JAR" \
  "${API_BASE}/api/v1/census-portal/session" \
  2>/tmp/hha_smoke_curl_err.tmp | tee /tmp/hha_smoke_body.tmp | tail -1)"
LAST_BODY="$(head -n -1 /tmp/hha_smoke_body.tmp 2>/dev/null || cat /tmp/hha_smoke_body.tmp)"

if [[ "$LAST_STATUS" != "401" ]]; then
  fail "Step 10: session terminated — expected 401, got ${LAST_STATUS}"
  printf "  Body: %s\n" "$LAST_BODY" >&2
  exit 1
fi
pass "session terminated"

# ---------------------------------------------------------------------------
# Optional cleanup — delete the smoke row from entries.daily_entries
# Only runs with --cleanup flag; off by default to avoid data loss in prod.
# ---------------------------------------------------------------------------
if [[ $DO_CLEANUP -eq 1 ]]; then
  printf "\n" >&2
  printf "Cleaning up smoke row (site_id=%s, entry_date=%s, census=42)...\n" \
    "$FIRST_SITE_ID" "$TODAY" >&2

  DELETE_SQL="DELETE FROM entries.daily_entries \
WHERE site_id=${FIRST_SITE_ID} \
  AND entry_date=CURRENT_DATE \
  AND census=42 \
  AND source='manual_portal';"

  if docker exec hha-postgres psql -U hha -d hha_dashboard -c "$DELETE_SQL" >&2 2>/dev/null; then
    pass "smoke row removed from DB"
  else
    printf "  Warning: cleanup query failed (container may not be local) — row remains\n" >&2
  fi
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
printf "\n" >&2
printf "${BOLD}${GREEN}══════════════════════════════════════════${RESET}\n" >&2
printf "${BOLD}${GREEN}  ALL SMOKE CHECKS PASSED${RESET}\n" >&2
printf "${BOLD}${GREEN}══════════════════════════════════════════${RESET}\n" >&2
printf "\n" >&2

exit 0
