#!/usr/bin/env bash
#
# seed_alert_subscriptions.sh — bash wrapper around scripts/seed_alert_subscriptions.py.
#
# Why this script: ops doesn't (yet) have an admin UI for editing alert
# recipients. Until they do, run this to seed each row. Idempotent — re-runs
# with the same (role, email) are a no-op unless `--update` is passed.
#
# Usage:
#   bash infra/seed_alert_subscriptions.sh \
#       --role exec --email cfo@hhamedicine.com \
#       --categories finance,clinical
#
# Env you'll likely want all six rows seeded once before the cron is enabled:
#   - admin@hhamedicine.com  (role: admin, all categories)
#   - ceo@hhamedicine.com    (role: exec)
#   - cfo@hhamedicine.com    (role: exec, finance)
#   - sandy@hhamedicine.com  (role: owner_finance, finance)
#   - crystal@hhamedicine.com (role: owner_ops, operations,clinical)
#   - aneja@hhamedicine.com   (role: owner_clinical, clinical)
#   - andrea@hhamedicine.com  (role: owner_hr, people)
#
# Run from the repo root.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$REPO_ROOT/api"
exec uv run python ../scripts/seed_alert_subscriptions.py "$@"
