# pg_backup Cron

Nightly `pg_dump` of the entire `hha_dashboard` Postgres database into the
Storage Account's `backups/` container.

## Schedule

`0 3 * * *` UTC (03:00 daily). Configured in
`infra/modules/containerjobs.bicep`. 30-min `replicaTimeout`. 1 retry on
failure (Container Apps Job built-in).

## Behavior

- Runs `pg_dump --format=custom --no-owner --no-acl` against the configured
  database. Default `-Z 6` compression.
- Writes to `/tmp/pg-backup-{env}-{ISO8601}.dump` inside the container.
- Uploads to `backups/<same name>` in the Storage Account.
- Tags blob metadata: `env_name`, `dump_started_at`, `dump_finished_at`,
  `dump_size_bytes`, `postgres_url_hash` (sha256:16 of the connection
  string — useful for cross-env detection without leaking creds).
- Exits 0 on success. Exits 1 on `BackupError` (pg_dump failed, upload
  failed, output empty). Exits 64 if `DATABASE_URL_SYNC` is unset.

## Why `--format=custom`

- Compact (binary, ~10x smaller than plain SQL).
- Restorable in parallel via `pg_restore -j 4`.
- Tolerates minor postgres version mismatches better than `--format=plain`.
- Doesn't bake role names in (`--no-owner`) — restore target picks roles.

## Auth

- **Prod:** Container Apps Job MI must have `Storage Blob Data Contributor`
  on the Storage Account. Granted via `rbac.bicep` (follow-up session).
- **Dev:** `AZURE_STORAGE_CONNECTION_STRING` from settings → Azurite or a
  real storage account. The cron uses whichever is present.

## Local run

The dev run requires:
- A reachable Postgres at `DATABASE_URL_SYNC` (the docker-compose `db` service is fine)
- `pg_dump` on your PATH (`brew install postgresql@16` / `apt-get install postgresql-client-16` / etc.)
- An Azurite or real Blob target. Azurite via docker-compose works.

```bash
cd hha-dashboard/api
# expects docker-compose up -d in another terminal
uv run python -m jobs.pg_backup.main
```

Expected output:
```
INFO jobs.pg_backup :: pg_dump.start path=/tmp/.../pg-backup-dev-2026-04-26T...Z.dump
INFO jobs.pg_backup :: pg_dump.done path=... size_bytes=1234567
INFO jobs.pg_backup :: pg_backup.uploaded blob_url=http://... size_bytes=1234567 duration_s=0.5
INFO jobs.pg_backup :: pg_backup.success blob=pg-backup-dev-...dump size_bytes=1234567
```

## Restore drill (the proof)

A backup nobody has restored is theatre. **Run the drill quarterly** (or
after every schema migration), per `docs/adr/004-backup-dr.md` (TBD):

```bash
bash scripts/restore_drill.sh
```

The drill:
1. Lists the most recent backup in the `backups/` container.
2. Downloads it to `/tmp/`.
3. Spins up a sandbox Postgres via `docker run` (NOT the dev compose
   instance — we don't restore over your working DB).
4. Runs `pg_restore -d <sandbox>` against it.
5. Compares row counts: every audited table's count in the sandbox must
   match the count in source within ±1% (ingestion may have written rows
   between dump-start and the row-count query).
6. Reports PASS / FAIL.

## Operator: lock the immutability policy

The `backups` container is provisioned with soft-delete only. **After the
first ~3 successful nightly backups, lock the WORM policy** (irreversible
by design — prevents tampering even by an admin):

```bash
ENV=prod
SA=$(az deployment group show -g rg-hha-dashboard-${ENV} -n <deploy-name> --query 'properties.outputs.storage_account_name.value' -o tsv)

az storage container immutability-policy create \
  --account-name $SA \
  --container-name backups \
  --period 90 \
  --allow-protected-append-writes true

# Confirm a few backups landed, then lock
ETAG=$(az storage container immutability-policy show \
  --account-name $SA --container-name backups --query etag -o tsv)
az storage container immutability-policy lock \
  --account-name $SA --container-name backups --if-match $ETAG
```

After lock, blobs in the container cannot be deleted or overwritten for 90
days. The lifecycle policy still applies to age-based pruning of older
backups.

## Failure modes

| Failure | Symptom | Fix |
|---|---|---|
| `pg_dump not on PATH` | Cron exits 1 with "Install postgresql-client" | Dockerfile bug — confirm `postgresql-client-16` is installed in image |
| Connection refused | pg_dump stderr "could not connect" | DATABASE_URL_SYNC wrong, or Postgres firewall blocks the Container Apps egress IP |
| Upload 403 | Blob upload fails with AuthorizationFailure | MI doesn't have Storage Blob Data Contributor — fix `rbac.bicep` |
| Disk full in container | pg_dump succeeds but file size 0 | Bump cpu/memory in containerjobs.bicep; default 0.5 CPU / 1 GiB is fine for <5GB DB |
| Backup ran but blob missing | Blob upload silently no-op'd | Check that AZURE_STORAGE_ACCOUNT_URL points at the right account; metadata mismatch means cross-env contamination |

## Defer

- Compression tuning beyond `-Z 6` — fine for current size.
- Encrypted-at-rest with customer-managed key (CMK) — Storage Account
  default encryption is HIPAA-acceptable for v0.
- Per-table parallel dump (`pg_dump -j N`) — overkill for this size.
- Snapshot-style point-in-time recovery — Postgres Flex's built-in PITR
  (35-day retention in prod) covers that. This cron is the *off-Azure*
  copy that survives even an Azure tenant compromise.
