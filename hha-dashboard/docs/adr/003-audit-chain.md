# ADR-003: Audit Chain — PG Triggers, Not ORM Listeners

- **Status:** Accepted
- **Date:** 2026-04-26
- **Deciders:** Akhil Reddy
- **Supersedes:** Migration 0007's commit message (`refactor: replace ORM listener with PL/pgSQL triggers`) — that's the implementation; this is the rationale.

## Context

HIPAA §164.312(b) requires an audit trail of access and modifications to PHI-adjacent data. We're aggregate-only (per ADR-001), so we don't audit *reads* — but **every mutation** to operational and HR tables must be attributable to a specific UPN with a specific timestamp and a diff of what changed.

The first attempt was a SQLAlchemy `before_flush` event listener (Session 3). It worked for ORM-managed instances. It silently failed for everything else.

Concrete misses:

1. **Owner-form upserts.** Every entry router uses `pg_insert(...).on_conflict_do_update(...)` (Session 4). That's a Core-level statement — it doesn't go through the ORM unit-of-work. The listener never fires.
2. **Cron job inserts.** `jobs/upload_ingest`, `jobs/ventra_ingest`, future `jobs/paycom_sync` all use Core upserts for the same reason. No audit rows.
3. **Raw `text()` calls** anywhere — none today, but a future "fix this one row in prod via psql" is a real on-call action that the listener wouldn't catch.

Net effect: by the end of Session 8 we had ~6 mutation paths, of which the listener caught 1. **Audit was theatre.**

## Decision

### Trigger-based, attributed via session-scoped GUC

Migration 0007 (Session 9) replaced the ORM listener with a Postgres trigger function `audit.log_change()` attached to `BEFORE INSERT/UPDATE/DELETE` on every audited table. Triggers fire regardless of which API issued the SQL — ORM, Core, raw, even `psql -c "UPDATE ..."`. They're the lowest-level catch.

Attribution flows like this:

```
FastAPI request
   │
   ▼
middleware sets `current_upn` ContextVar from CurrentUser.upn
   │
   ▼
get_db opens AsyncSession; SQLAlchemy after_begin event fires:
   SELECT set_config('audit.upn', <upn>, false)   ← session-scoped GUC
   │
   ▼
mutation runs (any path)
   │
   ▼
Postgres trigger reads current_setting('audit.upn', true)
   ↓
inserts row into audit.audit_log with that UPN + diff + timestamp
```

The `set_config(..., false)` makes the GUC session-scoped (not transaction-scoped) so it persists across `BEGIN/COMMIT` boundaries and is reset only when the connection is returned to the pool. The connection pool is per-request (via `async_sessionmaker`), so cross-request leakage is bounded by pool reuse — and the next request's `after_begin` overwrites the GUC anyway.

**Cron jobs** set the GUC at startup via `set_current_upn("upload-ingest@hhamedicine.com")` etc., and the same listener propagates it.

### What gets audited

Per `api/app/services/audit.py::AUDITED_TABLES`:

| Schema.Table | Why |
|---|---|
| `masters.physicians` | Directory + HR profile changes |
| `masters.comp_agreements` | Comp + FMV — Stark/AKS-relevant |
| `masters.contracts` | Hospital contract terms — material to subsidies |
| `masters.credentials` | DEA/license/privileges — HIPAA + regulatory |
| `masters.site_coverage` | MD coverage assignments |
| `entries.daily_entries` | Census numbers (typed by Crystal or PDF-extracted) |
| `entries.monthly_finance_manual` | Finance figures (typed by Sandy or Ventra-ingested) |
| `entries.weekly_clinical` | H&P / DC compliance |
| `entries.weekly_hr_manual` | HR rollups |

**Not audited:**

- `audit.audit_log` itself (no recursive trigger; would deadlock and 100x-amplify writes).
- `auth.census_credentials` — its own activity isn't material; what matters is what the portal *did*, captured via `entries.daily_entries` rows tagged with `source='manual_portal'`.
- `alerts.*` — operational state (subscriptions, send log, threshold log). Not user data.
- `uploads.upload_log` — operational queue.
- `dims.*`, `facts.*` — mostly read-only fact tables; would 10x audit volume on cron sync.

### Diff format

```jsonc
// INSERT
{ "new": { "census": 198, "open_shifts": 0, "site_id": 4, ... } }

// UPDATE (changed columns only, timestamps stripped)
{ "census": { "old": 198, "new": 205 } }

// DELETE
{ "old": { "census": 205, "site_id": 4, ... } }
```

UPDATE rows where the only change is `updated_at` (touch with no real value change) write **no audit row.** This prevents stamping noise from the audit trigger itself if a future migration rewrites timestamp defaults.

### Schema

```sql
audit.audit_log (
  id            bigint primary key,
  table_schema  varchar(63) not null,
  table_name    varchar(63) not null,
  row_pk        text not null,         -- text so non-int PKs work
  action        varchar(10) not null,  -- INSERT | UPDATE | DELETE
  diff          jsonb not null,
  changed_by_upn text not null,
  changed_at    timestamptz not null default now()
)
```

Index on `(changed_at DESC)` for retention queries; index on `(table_schema, table_name, row_pk)` for "who changed this physician's salary?" queries.

## Consequences

### Operating the audit trail

**To find who changed a row:**

```sql
SELECT changed_at, changed_by_upn, action, diff
FROM audit.audit_log
WHERE table_schema = 'masters'
  AND table_name   = 'comp_agreements'
  AND row_pk       = '<id>'
ORDER BY changed_at DESC;
```

**To find everything a user changed in a window:**

```sql
SELECT *
FROM audit.audit_log
WHERE changed_by_upn = 'crystal@hhamedicine.com'
  AND changed_at BETWEEN '2026-04-01' AND '2026-05-01'
ORDER BY changed_at;
```

**To find unauthenticated mutations** (these should not exist in prod):

```sql
SELECT *
FROM audit.audit_log
WHERE changed_by_upn = '__system__'
  AND table_schema IN ('masters', 'entries');
```

`__system__` is the default value of the `current_upn` ContextVar (per `app/services/audit.py:43–45`). Seeing it on a `masters` or `entries` mutation in prod means the middleware didn't resolve the user — investigate as an authentication-bypass alarm.

### Tampering surface

A user with Postgres write access can:
- Set `audit.upn` to whatever they want for their session (`SELECT set_config('audit.upn', 'someone-else', false)`). **Mitigation:** nobody has direct DB write access in prod — the API and cron jobs are the only writers. Audit attribution is therefore as trustworthy as the code that sets it, no more.
- DELETE rows from `audit.audit_log`. **Mitigation:** the immutability lock on backups (per ADR-004) means a DELETE is recoverable from yesterday's pg_dump. We don't put a `BEFORE DELETE` trigger on `audit.audit_log` because operational pruning (90+ days) is legitimate.
- DROP the trigger function. **Mitigation:** detected by `/ready` endpoint (per Operation B hardening) — readiness probe checks that `audit.log_change` exists. App Service stops sending traffic to instances where it doesn't.

This is "audit trail," not "tamper-proof ledger." For tamper-proof you need WORM-locked log shipping to a separate Storage Account write-only from this subscription. That's a future ADR if compliance escalates.

### Volume planning

At HHA scale (5–10 users, ~200 mutations/week across all owner forms), audit volume is ~10K rows/year. Index size ~1MB. Trivial.

At 100x scale (Ventra monthly ingestion of, say, 1M aggregated rows over 5 years of history) the audit table grows to ~5M rows. Still queryable; would benefit from monthly partitioning. Triggered as a follow-up ADR when audit table size crosses 10M rows.

### Performance

Each audited mutation is now 2 row writes (data + audit). Plus the GUC `set_config()` once per transaction. At our write volume this is ~free. Measured impact in `test_audit_triggers.py` integration: <1ms median overhead per mutation.

## Verification

- `tests/test_audit_triggers.py` — INSERT writes one audit row with `{"new": {...}}` diff; UPDATE writes a `{col: {"old": x, "new": y}}` diff with timestamps stripped; UPDATE with only `updated_at` change writes nothing; DELETE writes `{"old": {...}}`; cross-recursion: audit_log itself doesn't trigger; non-audited tables (e.g., `masters.sites` if it weren't in the list) don't trigger.
- `/ready` endpoint check: confirms `audit.log_change` function exists; 503 if not.
- Manual smoke test: sign in as `owner_ops`, save a census change, query `audit.audit_log` ORDER BY changed_at DESC LIMIT 1 — see one row with `changed_by_upn = <crystal's upn>`, action `UPDATE`, diff showing the census change.

## References

- [api/alembic/versions/0007_audit_triggers.py](../../api/alembic/versions/0007_audit_triggers.py) — the trigger function + per-table attachments
- [api/app/services/audit.py](../../api/app/services/audit.py) — `current_upn` ContextVar + `set_current_upn()` helper
- [api/app/deps.py](../../api/app/deps.py) — `after_begin` listener that copies the ContextVar into the GUC
- [api/app/main.py](../../api/app/main.py) — middleware that sets the ContextVar from `CurrentUser`
- [api/tests/test_audit_triggers.py](../../api/tests/test_audit_triggers.py) — integration tests
