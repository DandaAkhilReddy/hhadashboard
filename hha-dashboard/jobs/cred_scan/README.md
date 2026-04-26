# Credential Expiry Scan Cron

Daily HTML email summarizing credentials (DEA, license, hospital privileges,
etc.) crossing into the 30/60/90-day expiry bands since the last scan.

## Schedule

`0 12 * * *` UTC — daily at noon UTC. Configured in
`infra/modules/containerjobs.bicep`.

## Behavior

- Reads `masters.credentials` joined with `masters.physicians`.
- Filters to `status='ACTIVE'` and `expires_on <= today + 90d`.
- Buckets each into the tightest band crossed (90 → 60 → 30).
- Skips credentials that already have an `alerts.credential_alert_log`
  row for the same band — this is the daily-spam prevention.
- Sends one email per `owner_clinical` / `admin` subscriber with a grouped
  table of all band-crossings.
- Persists `credential_alert_log` rows ONLY if at least one email
  succeeded — guarantees a retry tomorrow if every send failed.

## Why per-band, not per-day

Credentials don't change minute-to-minute. If a DEA expires in 45 days, we
want **one** email when it crosses into the 60-day band, then **one** more
when it crosses 30, then nothing else. Daily emails for the same credential
would be noise.

## Local run

```bash
cd hha-dashboard/api
uv run python -m jobs.cred_scan.main
```

With no ACS env, expects:

```
INFO jobs.cred_scan :: Email not configured — exiting cleanly (no-op).
```

## Production troubleshooting

- **No emails arriving:** check `alerts.credential_alert_log` for today —
  if present and email_configured is true, the cron sent and ACS
  acknowledged. If empty, check that there are credentials within 90d
  of expiry that DON'T already have a log row.
- **Stuck at "we already alerted that band":** delete the
  `credential_alert_log` row for the affected (credential_id,
  threshold_band) — next run will re-alert.
- **Wanting to re-alert ALL pending creds (e.g., new owner takeover):**
  `DELETE FROM alerts.credential_alert_log;` — next run will re-emit
  every active band.

## Defer

- Per-physician routing (only alert the MD's primary site's medical
  director) — currently broadcasts to every owner_clinical subscriber.
- Per-band escalation (e.g., 30-day band copies admin@) — a follow-up if
  ops wants it.
- Re-issuance detection (a credential's `expires_on` updated → clear
  the alert log automatically). Today this is manual — admin clears the
  log row, next run re-alerts on the new date.
