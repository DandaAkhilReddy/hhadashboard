# Alert Digest Cron

Weekday morning HTML email summarizing yesterday's variance flags from the
finance / clinical / HR / operations boards.

## Schedule

`0 11 * * 1-5` UTC ≈ 07:00 ET, Monday–Friday. Configured in
`infra/modules/containerjobs.bicep`.

## What it does

1. Reads `settings.email_configured` — exits 0 cleanly if no ACS env.
2. Calls `services.alert_engine.compute_alerts_for_date(yesterday)` to get
   today's variance flags.
3. Looks up `alerts.alert_subscriptions` rows where `frequency='daily'`.
4. For each (alert × subscriber) pair:
   - Skips if `alerts.alert_log` already has the (alert_id, target_date,
     recipient) — re-running on the same day is a no-op.
   - Otherwise renders `alert_digest.html.j2`, sends via ACS, persists to
     `alert_log` with the ACS message id.
5. Exits 1 only if every send failed and zero succeeded; otherwise 0.

## Local run

```bash
cd hha-dashboard/api
uv run python -m jobs.alert_digest.main
```

With no ACS env, expect:

```
INFO jobs.alert_digest :: Email not configured — exiting cleanly (no-op).
```

To exercise the path with real DB writes (still no email sent):

```bash
# 1. Apply the alerts schema if you haven't yet
uv run alembic upgrade head

# 2. Seed at least one daily subscriber
uv run python ../scripts/seed_alert_subscriptions.py \
  --role exec --email cfo@hha.test --frequency daily

# 3. Make sure there are variance rows in finance/clinical/hr (entry forms or test fixtures)

# 4. Run the cron
uv run python -m jobs.alert_digest.main
```

## Production troubleshooting

- **No emails arriving:** check that `alerts.alert_subscriptions` has rows
  with `frequency='daily'` and the right role. Then check `alerts.alert_log`
  for `target_date=<yesterday>` — empty rows means the cron didn't fire;
  populated rows mean ACS responded with a message id (delivery is then
  ACS's job to follow up on).
- **Duplicate emails:** shouldn't happen — the unique constraint on
  `(alert_id, target_date, recipient_email)` prevents it.
- **Need to disable a recipient temporarily:** UPDATE the row's `frequency`
  to `'never'`. Don't delete (audit trail).

## Slot-in path

The Bicep job resource is gated on `enable_email && enable_container_jobs`.
To turn the cron on in prod after the ACS connection lands:
1. `bash infra/seed_alert_subscriptions.sh` to populate recipients.
2. Set `enable_email=true` in `prod.bicepparam` (already true).
3. `az deployment group create` — the new job appears.
