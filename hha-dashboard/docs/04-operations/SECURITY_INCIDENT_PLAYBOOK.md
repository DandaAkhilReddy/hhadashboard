# Security incident playbook

> **For on-call + compliance.** What to do when something more serious than "a service is slow" happens. This expands on the operational playbooks in [RUNBOOK.md](RUNBOOK.md) with security-focused scenarios. Aligned to the standard 5-stage incident response framework (Detect → Contain → Eradicate → Recover → Learn).
>
> Last updated 2026-05-11.

## Severity ladder

| Severity | Example | Response window |
|---|---|---|
| **SEV-1** | Suspected PHI breach, credential compromise affecting prod | < 15 minutes — immediate escalation |
| **SEV-2** | Audit log anomaly, unauthorized access attempt logged, suspected DoS | < 1 hour |
| **SEV-3** | Cert expiry pending, suspicious user behavior, vendor BAA lapse | < 24 hours |
| **SEV-4** | Low-priority advisory, dependency vulnerability with no public exploit | < 1 week |

When in doubt, **upgrade severity**, don't downgrade.

## Universal first 5 minutes (any SEV-1 or SEV-2)

1. **Acknowledge.** Write a timestamped one-liner in a private notebook: "What I just saw."
2. **Do not delete anything.** Preserve evidence.
3. **Notify Akhil** (areddy@hhamedicine.com) and HHA legal counsel if PHI-relevant.
4. **Open a private incident log** — a markdown file in `~/incident-logs/YYYY-MM-DD-<short-name>.md`. Append timestamped actions to it. **This becomes the post-mortem source.**
5. **Set `audit.upn = 'incident-responder-<your_upn>'`** on any DB session you open during response, so audit log captures who.

---

## Scenario 1 — Suspected PHI breach

**Symptom:** Any of these:

- Audit log shows a forbidden column was somehow written to (the assert in the ingestion job didn't catch it)
- A `facts.*` table has a row with a forbidden column
- A backup file has PHI inside it that shouldn't
- A user reports seeing patient data they shouldn't have

### Detect

```bash
# Check audit log for forbidden columns in the diff
psql $DATABASE_URL_SYNC -c "
  SELECT id, actor_upn, table_name, occurred_at, diff
  FROM audit.audit_log
  WHERE diff::text ~ '(patient_|ssn|mrn|guarantor_|pat_dob)'
  ORDER BY occurred_at DESC
  LIMIT 50;
"
```

If anything returns, that's the trail.

### Contain

1. **Stop the ingestion job immediately** (if Phase 2 active):
   ```bash
   az containerapp job stop --name cj-hha-ventra-ingest -g rg-hha-dashboard-prod
   ```
2. **Snapshot the suspect data** before anyone modifies:
   ```bash
   pg_dump --schema=facts --schema=audit > /tmp/incident-snapshot-$(date +%Y%m%d_%H%M).sql
   ```
3. **Pause incoming Ventra deliveries**: revoke the SFTP user's SSH key
   ```bash
   az storage account local-user update --account-name sthhaprod --user-name ventra --has-ssh-key false
   ```
4. **Block public access** to the storage container that has any suspected raw drops (precaution):
   ```bash
   az storage container set-permission --account-name sthhaprod --name ventra-incoming --public-access off
   ```

### Eradicate

1. **Identify how PHI got in.** Three possible vectors:
   - Ingestion job's allowlist had a forbidden column added (look at `parse/option_*.py` git history)
   - A migration added a forbidden column (look at `api/alembic/versions/` git history)
   - A manual SQL fix bypassed all controls (check `audit_log` for direct SQL evidence)
2. **Patch the vector.** Revert the bad commit; add a regression test.
3. **Purge the offending data:**
   ```sql
   BEGIN;
   SET LOCAL audit.upn = 'incident-responder-<your_upn>';
   -- Cite incident log
   UPDATE facts.collections_daily SET <forbidden_col> = NULL WHERE <forbidden_col> IS NOT NULL;
   -- Or DELETE if entire row is contaminated
   COMMIT;
   ```
4. **Re-verify:** run the `tests/test_schema_classification.py` test against the live schema.

### Recover

1. **Re-enable ingestion** only after:
   - Patch deployed and verified in dev
   - `pytest tests/test_ventra_firewall.py` passes
   - Restored SFTP user with new SSH key
2. **Run shadow mode for 48 hours** — ingest to `facts.*_staging` tables, manually verify zero PHI, then cutover.

### Learn

1. Post-mortem within **48 hours**. Mandatory sections: timeline, root cause, contributing factors, what we did right, what we did wrong, action items with owners.
2. **Notify HHA legal** of disclosure obligations under HIPAA's Breach Notification Rule (45 CFR §§ 164.400-414):
   - If < 500 individuals affected: report to HHS within 60 days of end of calendar year
   - If ≥ 500: report to HHS within 60 days of breach discovery, notify affected individuals within 60 days, notify prominent media outlets
3. **Update ADR-001** if the data classification rules need tightening.
4. Add the post-mortem to `docs/incidents/YYYY-MM-DD-<name>.md` (sanitized — no PHI).

---

## Scenario 2 — Credential compromise

**Symptom:** Any of these:

- A credential is shared accidentally (Slack, screenshot, chat with a vendor)
- An ex-employee leaves with knowledge of a credential
- Audit log shows suspicious authenticated activity from an unfamiliar IP
- A GitHub secret-scanner alert fires on the repo

### Affected credentials (rotate per scenario)

| Credential | Where stored | How to rotate |
|---|---|---|
| Postgres admin password | KV `kv-hha-prod2/postgres-admin-password` + GitHub Actions secret | See "Rotate Postgres admin pw" below |
| Web `SESSION_SECRET` | App Service env var on `app-hha-web-prod` | See "Rotate session secret" below |
| GitHub Personal Access Token | Akhil's local + GitHub | `gh auth refresh` — see "Rotate GH PAT" below |
| Portal credential (census kiosk) | Hashed in `entries.portal_credentials` | Run `seed_census_credential.py` with new password |
| SFTP user SSH key | Ventra's side + our `sthhaprod` local user | Generate new keypair, push new public key, give private to Ventra |
| App Service deployment credentials | Azure-managed | `az webapp deployment list-publishing-credentials --reset` |

### Rotate Postgres admin pw

```bash
NEW_PG_PW=$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32)

# 1. Postgres
az postgres flexible-server update \
  -g rg-hha-dashboard-prod -n psql-hha-prod \
  --admin-password "$NEW_PG_PW"

# 2. KV secrets (3 entries)
az keyvault secret set --vault-name kv-hha-prod2 -n postgres-admin-password --value "$NEW_PG_PW" >/dev/null
az keyvault secret set --vault-name kv-hha-prod2 -n database-url --value \
  "postgresql+asyncpg://hhaadmin:${NEW_PG_PW}@psql-hha-prod.postgres.database.azure.com:5432/hha_dashboard?ssl=require" >/dev/null
az keyvault secret set --vault-name kv-hha-prod2 -n database-url-sync --value \
  "postgresql+psycopg://hhaadmin:${NEW_PG_PW}@psql-hha-prod.postgres.database.azure.com:5432/hha_dashboard?sslmode=require" >/dev/null

# 3. App settings (literal, until KV refs are re-enabled in Phase 3)
az webapp config appsettings set -g rg-hha-dashboard-prod -n app-hha-api-prod --settings \
  "DATABASE_URL=postgresql+asyncpg://hhaadmin:${NEW_PG_PW}@psql-hha-prod.postgres.database.azure.com:5432/hha_dashboard?ssl=require" \
  "DATABASE_URL_SYNC=postgresql+psycopg://hhaadmin:${NEW_PG_PW}@psql-hha-prod.postgres.database.azure.com:5432/hha_dashboard?sslmode=require"

# 4. GitHub Actions secret
printf '%s' "$NEW_PG_PW" | gh secret set POSTGRES_ADMIN_PASSWORD_PROD --repo DandaAkhilReddy/hhadashboard

unset NEW_PG_PW

# 5. Verify
sleep 30
curl -fsS https://app-hha-api-prod.azurewebsites.net/ready
```

**Important:** Never echo the password to chat, screen-share, or chat tools.

### Rotate session secret

```bash
NEW_SESSION_SECRET=$(openssl rand -base64 32)

az webapp config appsettings set -g rg-hha-dashboard-prod -n app-hha-web-prod \
  --settings "SESSION_SECRET=$NEW_SESSION_SECRET"

unset NEW_SESSION_SECRET
```

This invalidates all existing user sessions — users must sign in again. That's by design.

### Rotate GH PAT

```bash
gh auth refresh -s repo,workflow
```

If a specific scope was leaked: `gh auth refresh -s <scope>`.

---

## Scenario 3 — Audit log anomaly

**Symptom:** Audit log shows:

- Entries from an unexpected `actor_upn` (user no longer at HHA)
- Entries from `audit.upn = 'unknown'` (means GUC wasn't set — code bug)
- Gaps in `occurred_at` (means trigger wasn't firing — DB-side issue)
- Modifications to `audit.audit_log` itself (forbidden)

### Detect

```sql
-- Unknown actors
SELECT DISTINCT actor_upn, COUNT(*)
FROM audit.audit_log
WHERE occurred_at > now() - interval '7 days'
GROUP BY actor_upn
ORDER BY count DESC;

-- Unknown role assignments
SELECT actor_upn, actor_role, MIN(occurred_at), MAX(occurred_at)
FROM audit.audit_log
WHERE actor_role NOT IN ('admin', 'exec', 'owner_ops', 'owner_finance', 'owner_clinical', 'owner_hr', 'comp_viewer', 'portal-kiosk')
GROUP BY actor_upn, actor_role;

-- Gaps in audit (no mutation in 24h on a busy table is suspicious)
SELECT date_trunc('hour', occurred_at), COUNT(*)
FROM audit.audit_log
WHERE table_name = 'census_daily'
  AND occurred_at > now() - interval '7 days'
GROUP BY 1
ORDER BY 1;
```

### Contain

If you suspect ongoing unauthorized access:

1. **Disable the affected user** in Entra: `az ad user update --id <upn> --account-enabled false`
2. **Force token refresh** for everyone: increment a token-revocation timestamp via Entra (forces re-auth)
3. **Take a forensic snapshot:** `pg_dump --schema=audit > /tmp/audit-snapshot.sql`

### Recover

1. Investigate audit_log entries from the affected timeframe
2. Identify what was changed; reverse if needed
3. Communicate to leadership

---

## Scenario 4 — Suspected ransomware / data destruction

**Symptom:** Bulk deletion attempts, encryption-rename of files, audit log shows massive DELETEs from one actor.

### Contain

1. **Cut all access to the affected resource** immediately:
   ```bash
   # Stop the App Service
   az webapp stop -g rg-hha-dashboard-prod -n app-hha-api-prod

   # Take Postgres offline
   az postgres flexible-server stop -g rg-hha-dashboard-prod -n psql-hha-prod
   ```
2. **Disable the suspect user** in Entra.
3. **Do not pay any ransom.** Engage HHA legal + cyber insurance immediately.

### Recover

1. **Restore from last known-good backup:**
   ```bash
   # Point-in-time restore (Azure managed)
   az postgres flexible-server restore \
     -g rg-hha-dashboard-prod \
     --name psql-hha-prod-restored \
     --source-server psql-hha-prod \
     --restore-time '2026-05-10T08:00:00Z'

   # Verify content
   psql ... -c "SELECT COUNT(*) FROM masters.sites;"

   # Cutover: rename old → quarantine, restored → live
   ```
2. **Audit log will show the destruction event** — preserve it forensically.
3. **Backup integrity check:** WORM-locked Blob backups cannot be tampered with. Use those if managed PITR is compromised.

ADR-004 covers RTO (4h) and RPO (≤1h with PITR; ≤24h with daily WORM): [adr/004-backup-and-disaster-recovery.md](adr/004-backup-and-disaster-recovery.md).

---

## Scenario 5 — BAA gap discovered

**Symptom:** Compliance review reveals a vendor handling HHA data without a current BAA.

### Contain

1. **Stop data flow to the unprotected vendor** immediately
2. **Inventory what data they have already received**

### Eradicate

1. Negotiate + sign BAA before resuming data flow, OR
2. Replace the vendor with one that has a BAA

### Learn

1. Update [COMPLIANCE_POSTURE.md](COMPLIANCE_POSTURE.md) § BAA inventory
2. Add a recurring quarterly BAA renewal check to the calendar

---

## Scenario 6 — Lost / stolen device

**Symptom:** Akhil's (or any privileged user's) laptop is lost or stolen.

### Contain

1. **Revoke all sessions** for that user in Entra:
   ```
   az ad user revoke-sign-in-sessions --id areddy@hhamedicine.com
   ```
2. **Force MFA re-enrollment** on next sign-in
3. **Check Azure Activity Log** for any actions from unexpected locations:
   ```bash
   az monitor activity-log list --start-time 2026-05-11T00:00:00Z --offset 7d --query "[?caller=='areddy@hhamedicine.com']"
   ```
4. **Rotate any secrets that may have been cached** on the device:
   - GitHub PAT
   - Local KV access (`az login`)
   - Personal SSH keys (rotate Ventra SFTP key if it was on the device)

### Recover

1. Issue a new device with Conditional Access enforcement (MFA, device compliance, location-based)
2. Re-onboard the user

---

## Communication template

When you need to inform leadership of a SEV-1 or SEV-2 in-progress:

```
Subject: [INCIDENT] HHA Dashboard — <one-line summary> — <SEV-level>

What happened: <2-3 sentences>
When: <timestamp UTC>
Detected by: <person or system>
Impact: <users affected, data affected, services down>
Current status: <containing / eradicating / recovering>
Next update: <within X minutes/hours>

This is an incident-in-progress note. Full post-mortem will follow within 48 hours.

-- <responder>
```

Send to: areddy@hhamedicine.com + HHA legal counsel (for SEV-1) + HHA executive sponsor.

---

## Tools you'll need ready

Before you ever have an incident, ensure these are working:

- [ ] `az` CLI authenticated to HHA tenant
- [ ] `gh` CLI authenticated to DandaAkhilReddy
- [ ] `psql` client installed
- [ ] `pg_dump` installed
- [ ] Access to Azure portal (incident.azure.com or portal.azure.com)
- [ ] Application Insights link bookmarked
- [ ] HHA legal counsel contact memorized
- [ ] Microsoft BAA contact info (in compliance file)

A 2 a.m. incident is not the time to figure out where `az` is installed.

---

## When NOT to do this yourself

Some incidents require expertise you don't have:

- **Suspected sophisticated attacker** — engage Microsoft Defender Incident Response or a security firm
- **Anything involving law enforcement** — pause; HHA legal counsel coordinates
- **Press / public disclosure** — HHA CEO + legal handle this, never engineering alone
- **Federal regulatory inquiry** — HHA compliance officer + legal handle this

Your job is **detect + contain**. Eradicate and recover may need help.

---

**Next read:** [RUNBOOK.md](RUNBOOK.md) for operational (non-security) incident playbooks. Back to [INDEX.md](INDEX.md).
