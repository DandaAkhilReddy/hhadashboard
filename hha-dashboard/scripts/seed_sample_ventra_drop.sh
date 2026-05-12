#!/usr/bin/env bash
# Upload a sample Ventra drop to vendor-inbound for smoke-testing the
# ingest pipeline.
#
# CRITICAL: _MANIFEST.csv is uploaded LAST. The Event Grid subscription
# (infra/modules/vendor_eventgrid.bicep) filters to subjectEndsWith
# '/_MANIFEST.csv', so the data files must land first or the job would
# trigger on a partial drop. This script enforces the order.
#
# Usage:
#   scripts/seed_sample_ventra_drop.sh STORAGE_ACCOUNT [DROP_DATE [CONTAINER]]
#
# Defaults:
#   DROP_DATE = 2026-06-15 (matches the checked-in sample)
#   CONTAINER = vendor-inbound
#
# Auth: uses `az login` token (--auth-mode login). The signed-in user
# must hold "Storage Blob Data Contributor" on the target storage
# account, OR use a SAS via --sas-token if running unattended.

set -euo pipefail

ACCT="${1:?usage: $0 STORAGE_ACCOUNT [DROP_DATE [CONTAINER]]}"
DROP="${2:-2026-06-15}"
CONTAINER="${3:-vendor-inbound}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SAMPLE_DIR="$REPO_ROOT/samples/ventra/sample-drop-${DROP}"

if [[ ! -d "$SAMPLE_DIR" ]]; then
  echo "error: sample dir not found: $SAMPLE_DIR" >&2
  echo "regenerate with: python scripts/generate_sample_ventra_drop.py $DROP $SAMPLE_DIR --include-monthly" >&2
  exit 1
fi
if [[ ! -f "$SAMPLE_DIR/_MANIFEST.csv" ]]; then
  echo "error: $SAMPLE_DIR is missing _MANIFEST.csv" >&2
  exit 1
fi

echo "uploading sample drop $DROP to ${ACCT}/${CONTAINER}/ventra/${DROP}/"

# 1. Data files first — any file in the sample dir except _MANIFEST.csv.
for f in "$SAMPLE_DIR"/*.csv; do
  name="$(basename "$f")"
  if [[ "$name" == "_MANIFEST.csv" ]]; then
    continue
  fi
  echo "  -> ${name}"
  az storage blob upload \
    --account-name "$ACCT" \
    --container-name "$CONTAINER" \
    --name "ventra/${DROP}/${name}" \
    --file "$f" \
    --auth-mode login \
    --overwrite \
    --output none
done

# 2. _MANIFEST.csv LAST — this is the file Event Grid subscribes to. The
# Container Apps Job replica fires only after this blob lands.
echo "  -> _MANIFEST.csv (trigger)"
az storage blob upload \
  --account-name "$ACCT" \
  --container-name "$CONTAINER" \
  --name "ventra/${DROP}/_MANIFEST.csv" \
  --file "$SAMPLE_DIR/_MANIFEST.csv" \
  --auth-mode login \
  --overwrite \
  --output none

echo "done. event grid should fire within a few seconds; watch:"
echo "  az containerapp job execution list --name caj-ventra-ingest-<env> --resource-group <rg>"
echo "  or App Insights customEvents | where name startswith 'ventra.'"
