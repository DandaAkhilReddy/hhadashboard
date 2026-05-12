# Phase 1 — Census Portal

> Audience: anyone (engineer, operator, sponsor) who needs to know what the portal collects, what it intentionally **doesn't** collect, and how to provision it. This doc is the contract for Phase 1 — anything outside it is out of scope.

---

## Purpose

HHA staff need a simple, write-only portal where one ops user logs in once a day and enters daily census totals for each of HHA's hospitals. The numbers feed the main Operations board in near-real-time. The portal is intentionally separated from the Entra-gated dashboard so the user entering census never has access to scorecards, finance, clinical, or HR data.

Vendor data feeds (Ventra, Paycom) are still blocked for HHA. The portal is therefore the only operational data source for census during Phase 1.

---

## Exact fields collected

Per **submission** (one row per facility per date):

| Field | Source | Notes |
|---|---|---|
| `site_id` | dropdown / inferred from row | FK to `masters.sites.id` |
| `census_date` | date picker (default: today) | DB column: `entries.daily_entries.entry_date` |
| `census_number` | numeric input, 0–2000 | DB column: `entries.daily_entries.census` |
| `created_at` / `updated_at` | server clock (`func.now()`) | DB columns from `TimestampMixin` |

That is all the portal writes.

### Forbidden fields (do NOT collect, do NOT display, do NOT add)

The portal MUST NOT collect or display any of the following:

- patient names, MRNs, DOBs
- claim IDs, encounter IDs
- admits, discharges
- free-text notes
- `submitted_by` (the row carries `entered_by_upn = 'census-portal@hhamedicine.com'` for audit attribution; the portal UI never shows or asks for who submitted)

The DB column `open_shifts` (NOT NULL DEFAULT 0) stays in `entries.daily_entries` for compatibility with the dashboard owner-form (`/daily-census`, owned by Crystal Anderson). The Phase 1 portal does NOT write or display it. On INSERT the DB defaults it to 0; on UPDATE the portal upsert intentionally leaves whatever value the dashboard form may have written. The lock-in test:

```
api/tests/test_census_portal.py::test_save_accepts_phase1_payload_without_open_shifts
```

### HIPAA classification

All Phase 1 columns are **Tier A** (aggregates) per [ADR-001](../02-architecture/adr/001-hipaa-data-classification.md). No PHI. No 18 HIPAA identifiers. The classification is enforced at the schema level by `tests/test_schema_classification.py`.

---

## Routes / pages

| Surface | Path | Purpose |
|---|---|---|
| Web · login | `/census/login` | email + password form (existing) |
| Web · entry | `/census/entry` | date picker + summary cards + per-row lock/edit table (Phase 1) |
| API · login | `POST /api/v1/census-portal/login` | issues `census_session` cookie |
| API · session | `GET  /api/v1/census-portal/session` | 200 + email if cookie valid; 401 otherwise (Phase 1) |
| API · sites | `GET  /api/v1/census-portal/sites?date=YYYY-MM-DD` | one row per facility with that date's census or null |
| API · summary | `GET  /api/v1/census-portal/summary?date=YYYY-MM-DD` | total / reported / missing / last_updated_at (Phase 1) |
| API · save | `POST /api/v1/census-portal/daily-census` | upsert one or more `(site_id, census)` rows for a date |
| API · logout | `POST /api/v1/census-portal/logout` | clear active token + cookie |

**Operations board integration** — `GET /api/v1/operations/summary` now also returns `facilities_reported`, `facilities_missing`, and `last_updated_at`. The dashboard's `/operations` page renders these next to the "+ Enter Today's Data" CTA so execs can see at a glance how fresh the census is. No new endpoint, just an extension to the existing summary shape.

### Files changed (summary)

- `api/app/settings.py` — `census_portal_email` setting
- `api/app/schemas/census_portal.py` — `PortalSummaryOut`, `PortalSessionOut`; trim `PortalCensusRow` to Phase 1 fields
- `api/app/routers/census_portal.py` — `?date=` param on `/sites`, new `/summary` + `/session` endpoints, Phase-1 whitelist on the upsert
- `api/app/schemas/operations.py` — extend `OperationsSummary`
- `api/app/services/fake_data.py` — populate the new `OperationsSummary` fields from real DB
- `web/app/census/entry/CensusEntryForm.tsx` — drop `open_shifts`, add date picker + four summary cards + empty-state
- `web/app/census/entry/page.tsx` — read `?date=` searchParam, fetch summary in parallel
- `web/app/operations/page.tsx` — display `facilities_reported / total · last update HH:MM` in the header
- `web/lib/api-client.ts` — add the new fields to the `OperationsSummary` type
- `api/tests/test_census_portal.py` — 7 new tests
- `docs/PHASE_1_CENSUS_PORTAL.md` — this file

No alembic migration. The `entries.daily_entries` schema is unchanged.

---

## Auth

Reuses the existing portal auth chain (no changes):

- One row in `auth.census_credentials` (table from migration `0008_census_credentials`)
- `email` is the configurable login (default `portal@hhamedicine.com`, see env var below)
- `password_hash` is **argon2id** (OWASP 2023, time=3 / mem=64MB / par=4)
- Passwords are NOT env vars and NOT in code — only a hash exists, in the DB row, seeded by `scripts/seed_census_credential.py`
- Single-session lock: every login overwrites `active_session_token`, so a second browser kicks the first
- Lockout: 10 consecutive failures → 15-minute lock
- Session lifetime: 8h, rotated on every login

The portal is read-only against operational data: the only GETs available behind the cookie are `/sites`, `/summary`, and `/session`. Every write logs an audit row via Postgres triggers from migration `0007_audit_triggers`.

---

## Environment variables

The repo's existing pattern: secrets live in Azure Key Vault in prod, in `.env` locally. No password ever goes into env files (only the email is configurable).

In `api/.env.example`:

```bash
# Census portal — Phase 1
# Default email for the single shared portal credential. Override per-env if needed.
CENSUS_PORTAL_EMAIL=portal@hhamedicine.com
# CENSUS_PORTAL_PASSWORD_HASH is intentionally NOT set here — passwords live
# only as argon2id hashes inside the auth.census_credentials row, seeded via
# `scripts/seed_census_credential.py`. Never commit a password.
```

In production (Azure App Service), `CENSUS_PORTAL_EMAIL` is set via App Settings; the password hash is provisioned into the database directly by running the seed script in a one-shot Azure CLI session against the production DB.

---

## Local test steps

```bash
# 1. Bring up Postgres
cd hha-dashboard
docker compose up -d

# 2. Apply migrations
cd api
uv sync
uv run alembic upgrade head

# 3. Seed sites (11 hospitals)
uv run python scripts/seed_sites.py

# 4. Seed the portal credential
bash infra/census_seed.sh \
  --email portal@hhamedicine.com \
  --password '<choose a strong password — never commit>'

# 5. Start the API
uv run uvicorn app.main:app --reload   # http://localhost:8000

# 6. Start the web app (in a second terminal)
cd ../web
npm install
npm run dev                             # http://localhost:3000

# 7. In a browser:
#    - http://localhost:3000/census/login
#    - sign in with the email + password from step 4
#    - confirm the entry page loads with: date picker, 4 summary cards,
#      11-row table, "Enter" buttons on never-entered rows
#    - enter a value for one site, click Save → row goes green, locks
#    - change the date picker → page reloads with that date's data
#    - click /operations on the dashboard side → header shows
#      "X of Y reported · last update HH:MM"
```

### Run the gate

```bash
cd api
uv run ruff check .
uv run mypy app                    # 2 pre-existing deps.py errors are unaffected
uv run pytest                      # 12 portal tests + the rest of the suite

cd ../web
npm run lint
npm run typecheck
npm run test                       # vitest
npm run e2e                        # Playwright (Chromium)
```

---

## Production notes (Azure)

- **CENSUS_PORTAL_EMAIL** lives in App Service application settings (regular setting, not a Key Vault reference — it's not a secret).
- **Password** is set once via the seed script run against the production database. Rotate by re-running the seed with a new password — the script overwrites the existing hash and clears the active session token (kicking the live browser).
- **Backups** — every census write triggers an `audit.audit_log` row (see migration `0007_audit_triggers`). The nightly `pg_backup` cron writes pg_dump output to Blob with WORM, so audit history survives DB compromise.
- **Telemetry** — App Insights traces every `/api/v1/census-portal/*` request via the OpenTelemetry instrumentation wired in `app/core/telemetry.py`. Request bodies are NEVER logged (no PII risk; aggregate-only data anyway).

---

## What's intentionally NOT in Phase 1

These are out of scope for this phase. Adding any of them needs a new phase + sponsor sign-off:

- per-hospital portal logins (the brief explicitly chose one shared login)
- backfill / bulk import flows
- export to CSV / PDF
- mobile-optimized layout (the current responsive Tailwind layout is good baseline)
- copy-yesterday-as-default
- per-row save toasts (kept inline feedback only — no global toast system in the portal)
- cross-state aggregates (already in the Operations board on the dashboard side; no need to duplicate)

For the rationale on each, see commit history of this doc and the build plan.

---

_Last updated: 2026-04-27 · matches `feat(census): simplify portal census entry workflow`._
