# ADR-004: Backup & Disaster Recovery

- **Status:** Accepted
- **Date:** 2026-04-26
- **Deciders:** Akhil Reddy
- **Supersedes:** None

## Context

Healthcare operations data is the kind of thing where "we forgot to back it up" is a career-ending answer. We have two backup mechanisms running in parallel by design:

1. **Azure Postgres Flexible Server's managed backups** — automatic, geo-redundant, point-in-time restore within a 35-day retention window. Operates inside the Azure subscription.
2. **Custom `pg_backup` cron** — nightly `pg_dump --format=custom` to an Azure Blob `backups/` container. Operates inside the same subscription.

Why both? Because they fail differently.

- The managed backup fails if the **subscription** is compromised or accidentally deleted (admin error, billing lapse, tenant takeover). All managed backups vanish with it.
- The custom cron fails if **our code** has a bug.

Two independent paths bound the joint failure probability. The custom cron lands in a Storage Account whose `backups/` container is locked under a WORM (Write-Once-Read-Many) immutability policy — even an admin with full subscription rights can't delete those blobs for the lock period.

## Decision

### Part 1 — Two layers, different roles

| Layer | RTO | RPO | Failure mode it covers |
|---|---|---|---|
| **Postgres Flex managed backups** | ~1h (PITR) | ≤5 min (continuous WAL) | Hardware, regional outage, point-in-time recovery from "just before this bad migration" |
| **Custom pg_backup → Blob WORM** | ~4h (download + restore) | 24h (nightly cron) | Subscription compromise, accidental DROP, ransomware on Postgres, "we lost the entire RG" |

Managed = primary. Custom = belt-and-suspenders + audit-trail-preservation.

### Part 2 — Custom pg_backup cron

Implementation: `jobs/pg_backup/main.py` + `jobs/pg_backup/backup.py`.

- Runs at `0 3 * * *` UTC (03:00 daily) via Azure Container Apps Job.
- Image bakes `postgresql-client-16` matching the server major version.
- `pg_dump --format=custom --no-owner --no-acl` to a temp file in the container.
- Uploads to Blob `backups/pg-backup-{env}-{ISO8601}.dump` with metadata: `env_name`, `dump_started_at`, `dump_finished_at`, `dump_size_bytes`, `postgres_url_hash` (sha256:16 of conn string — distinguishes envs without leaking creds).
- `overwrite=False` on the upload — same blob name twice is a bug, not a retry.
- Exit code: 0 on success, 1 on `BackupError`, 64 if `DATABASE_URL_SYNC` unset.

### Part 3 — WORM immutability lock

The `backups` container is provisioned by `infra/modules/storage.bicep` with soft-delete enabled but **no immutability policy at deploy time.** That's deliberate. Locking is irreversible (by design — the whole point of WORM is "even an admin can't") and we don't want to lock before the first real backup lands and we've verified the cron works end-to-end.

Operator procedure (run **once per environment** after ~3 successful nightlies):

```bash
ENV=prod
SA=$(az deployment group show -g rg-hha-dashboard-${ENV} -n <deploy> \
  --query 'properties.outputs.storage_account_name.value' -o tsv)

# Phase 1 — create unlocked policy
az storage container immutability-policy create \
  --account-name $SA \
  --container-name backups \
  --period 90 \
  --allow-protected-append-writes true

# Phase 2 — verify ~3 backups land successfully under it
sleep 86400  # come back tomorrow
az storage blob list --account-name $SA --container-name backups -o table

# Phase 3 — lock (irreversible)
ETAG=$(az storage container immutability-policy show \
  --account-name $SA --container-name backups --query etag -o tsv)
az storage container immutability-policy lock \
  --account-name $SA --container-name backups --if-match $ETAG
```

After lock: blobs in `backups/` cannot be deleted or modified for 90 days from each blob's upload time. Older blobs age out under the storage lifecycle policy after the lock period — that's how retention pruning works without breaking WORM.

### Part 4 — Restore drill (the proof)

A backup nobody has restored is theatre. **Run `bash scripts/restore_drill.sh` quarterly**, and after every schema migration that touches an audited table.

The drill:

1. Lists `backups/` in the configured Storage Account.
2. Picks the most-recently-uploaded blob.
3. Downloads to `/tmp/restore-drill/`.
4. Spins up a sandbox Postgres on a non-default port via `docker run` (NOT the dev-compose `db` — we never restore over a working DB).
5. `pg_restore --jobs=4 --no-owner --no-acl` against the sandbox.
6. Compares row counts on each audited table: source vs sandbox must agree within ±1% drift (allows for ingestion writing rows between dump-start and the row-count query at drill time).
7. Reports PASS / FAIL.

Exit codes:
- 0 — drill passed
- 1 — download failed
- 2 — `pg_restore` failed
- 3 — row-count drift exceeded tolerance
- 4 — pre-flight (missing tool/env)

### Part 5 — RTO / RPO targets (committed)

| Scenario | RTO | RPO |
|---|---|---|
| App Service restart | <2 min | 0 |
| App Service redeploy from main | <15 min | 0 (DB untouched) |
| Postgres point-in-time restore (last 35 days) | <1 hour | <5 min |
| Full DR — restore from custom pg_backup blob | <4 hours | 24 hours |
| Whole-subscription loss + restore into fresh subscription | <24 hours | 24 hours |

The 24-hour RPO floor in DR scenarios is the cron cadence. If HHA later needs <24h RPO post-DR, increase cron frequency or move to logical replication; both are scope changes.

## Consequences

### Day-to-day

- **Lost a single row** — query the audit log, find the prior value, UPDATE manually. No backup involvement.
- **Lost a single table** — Postgres PITR. ~1 hour. RG admin clicks "restore to point-in-time."
- **Lost the whole DB but Azure is fine** — restore from PITR or from yesterday's pg_backup blob, whichever you trust more.
- **Lost the subscription** — provision a fresh one, run Bicep, download the latest pg_backup blob from the (separate) backups Storage Account, `pg_restore`. The 24h RPO is the worst case here.

### Incident response

The first question in any data-loss incident is **"is the audit log intact?"** That tells you what to recover and what state was right. The audit log lives in the same DB as everything else, so it's covered by the same backup mechanisms. The audit log is therefore part of the same RPO commitment.

### Compliance (HIPAA §164.308(a)(7))

- **Data backup plan**: this ADR + the cron + the WORM lock.
- **Disaster recovery plan**: RTO/RPO table above + restore drill + RUNBOOK.md procedures.
- **Emergency mode operation plan**: degrade to manual workflows (Crystal/Sandy use spreadsheets) for the duration of the outage. Document that the audit log will need a backfill from email/screenshots when service is restored.
- **Testing and revision procedures**: quarterly restore drill (this ADR Part 4).
- **Application and data criticality analysis**: Tier B (HR, comp, directory). The dashboard going down for 4 hours is operationally inconvenient but not patient-care-impacting (we're not in the clinical path). Tier C data does not exist in our system by ADR-001.

### What this ADR does NOT cover (yet)

- **Cross-region failover.** Postgres Flex with `geo_redundant_backup=Enabled` (prod) replicates backups to a secondary region. We have not exercised the failover. Add to next quarter's drill.
- **Customer-managed key (CMK) on backups.** Storage Account default encryption is HIPAA-acceptable for v0; CMK rotation is a future ADR.
- **Off-Azure escrow.** A copy of backups outside Microsoft would protect against Microsoft-tenant compromise. Not implemented; tradeoff is operational complexity vs. residual risk. Revisit if a HIPAA auditor asks.
- **Backup encryption at rest with our own key**. Today: Azure-managed key. Acceptable per HIPAA Security Rule. Future: add a CMK rotation if compliance asks.

## Verification

- `api/tests/test_job_pg_backup.py` — 13 unit tests covering filename, hash determinism, no-password-leak, pg_dump failure modes, end-to-end orchestration.
- CI runs the integration test against a real Postgres on every PR (skipped only when `pg_dump` isn't on PATH — which on CI Linux is never).
- Manual: `bash scripts/restore_drill.sh` against a real backup and watch the row-count comparison.

## References

- [jobs/pg_backup/](../../../jobs/pg_backup) — implementation
- [jobs/pg_backup/README.md](../../../jobs/pg_backup/README.md) — operator runbook
- [scripts/restore_drill.sh](../../../scripts/restore_drill.sh) — restore drill
- [infra/modules/storage.bicep](../../../infra/modules/storage.bicep) — backups container provisioning
- [docs/RUNBOOK.md](../../04-operations/RUNBOOK.md) — incident procedures referencing this ADR
