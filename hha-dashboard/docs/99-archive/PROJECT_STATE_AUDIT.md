# HHA Dashboard — Forensic Project State Audit

- **Date:** 2026-04-26
- **Auditor:** Claude Code session (5 parallel forensic agents + synthesis), supervised by Akhil Reddy
- **Branch audited:** `chore/local-verification` (1 commit ahead of `origin/main`)
- **Method:** Read-only forensic audit. Every claim cited to a `file:line` or to a captured command output. Nothing assumed from filenames or prior summaries — verified against source, schema, tests, and runtime checks.
- **Constraint honored:** No new features built. The audit produced this document plus the small frontend fixes already merged via [PR #29](https://github.com/DandaAkhilReddy/hhadashboard/pull/29) (`chore: local verification pass`). No other code changed.

---

## 1. Executive Summary

15 blunt findings, ranked roughly by severity:

1. **The dashboard is built — the data isn't.** All five board pages (Operations / Finance / Clinical / People / Scorecards) currently render data from `api/app/services/fake_data.py`. The schema, migrations, routers, and forms are real and wired; the read path falls back to deterministic synthetic data because the database is effectively empty. This is by design per the v5 plan (Phase 1) but it's the single biggest gap between "built" and "demo-credible."
2. **The 11-site canonical seed never landed.** `masters.sites` contains exactly 1 row ("Test Site") because `scripts/seed_sites.py:125-129` bails on any existing row. The dashboard appears to show 11 sites only because `fake_data.py` synthesises them. On a clean Azure deploy, the count drops to whatever Sandy/Crystal type into the entry forms.
3. **Frontend `next build` is green as of this commit, but only just.** PR #29 fixed three prerender errors (one P0 server-only-import-in-client and two missing `<Suspense>` wrappers). All 21 routes now compile. Vitest 20/20. Backend pytest 207/1-skipped. mypy 48 errors. biome 38 CRLF errors.
4. **The CRLF problem is going to keep biting.** Every committed `.tsx`/`.ts` file has Windows line endings; `biome.json` requires LF; there's no `.gitattributes` and no pre-commit hook. Every Windows commit re-introduces the failure. The deploy workflows gate on CI green, so this stays red until normalized.
5. **HIPAA invariants are intact.** Zero `data_class: C` columns. Zero forbidden field names (`claim_id`, `patient_*`, `mrn`, `member_id`, `subscriber_*`, `guarantor_*`). All 184+ columns across 16 tables are tier-tagged. The `test_schema_classification.py` CI guard enforces this on every PR. The PII-redaction structlog processor scrubs every forbidden key plus credentials/sessions/UPN.
6. **Audit chain is genuinely production-grade.** Postgres triggers (migration 0007) on 9 sensitive tables write to `audit.audit_log` regardless of mutation path (ORM, Core upsert, raw SQL, even direct `psql`). Attribution flows from FastAPI middleware → `current_upn` ContextVar → `set_config('audit.upn', ...)` GUC → trigger function. Tested in `test_audit_triggers.py` against real Postgres.
7. **Auth has belt-and-suspenders defense in depth.** `app/main.py:51-56` refuses to start if `ENV != "dev"` AND Entra is not configured. `app/deps.py:128-129` Path 3 default-admin only fires when both `ENV=dev` AND `not entra_configured`. CORS only opens to `localhost:3000` in dev or to the explicit `web_origin` in prod.
8. **Infrastructure is ready to deploy but has never been deployed.** All 10 Bicep modules compile clean, lint zero warnings, all 3 GH workflow YAMLs parse, all 4 shell scripts are syntactically valid. ACR + RBAC + deploy-prod.yml landed in PR #28. Three blockers remain before the first `az deployment group create`: (a) Entra app registrations + group OIDs, (b) `SESSION_SECRET` not seeded by `bootstrap.sh`, (c) `deployer_workstation_ip` defaults to `0.0.0.0` in both bicepparam files with no CI check.
9. **Cron jobs split into 3 real / 2 stub / 1 partial.** Real: `pg_backup` (PR #25, image-builds, has restore drill), `alert_digest` (PR #23), `cred_scan` (PR #23). Stub: `paycom_sync` (waiting on Paycom API access — 4–6 week window from F1), `ventra_ingest` (waiting on Ventra BAA + data shape — F1). Partial: `upload_ingest` (PDF extractor `pdf_extract.py:181` has an Azure SDK overload mismatch that crashes on first real upload).
10. **No browser tests anywhere.** Zero Playwright, zero React component tests, zero page-level integration tests. The 4 vitest files cover `api-fetch`, `middleware`, `session-crypto`, and `session-route` — entirely the `lib/` boundary. Every page, every form, every component is tested only by `npm run build` succeeding. The PR #29 build-blocker would have been caught by a single page-render test.
11. **App Insights infrastructure exists; SDK wiring does not.** `infra/modules/monitor.bicep` provisions Application Insights + Log Analytics + Diagnostic Settings on every audited resource (PR #18). The FastAPI app does not actually send custom telemetry — no OpenTelemetry, no correlation IDs across the api/postgres/blob chain. First prod incident has only App Service stdout to debug from.
12. **Census portal is its own threat model and it works.** Separate Postgres-stored credential (argon2id), single-session lock via `active_session_token` overwrite, separate `census_session` httpOnly cookie, separate `web/middleware.ts` branch. ADR-002 § Part 5 explicitly distinguishes this surface from the Entra-backed dashboard. No tests for credential rotation though — that's still manual via `infra/census_seed.sh`.
13. **No vendor data is in the system.** No Ventra contract delivered. No Paycom API access granted. No real-PHI fixtures anywhere. Sample data in `samples/` and `tests/fixtures/` is clearly synthetic.
14. **The two type-safety bugs surfaced by mypy are real, not nits.** `services/entra_jwt.py:77,87` returns `Any` from JWT claim extraction — a malformed-shape claim could silently bypass role checks. `services/pdf_extract.py:181` has an Azure Document Intelligence SDK overload mismatch — runtime crash on Crystal's first real PDF upload. Both should be P1 fixes before real users touch the system.
15. **The ADRs are actually accurate.** All five ADRs (HIPAA classification, RBAC model, Audit chain, Backup & DR, FL/TX scope split) describe what the code actually does. Not aspirational. RUNBOOK.md has the right shape but its first-deploy procedure has not been executed end-to-end yet.

**Bottom line:** Code-side, the foundation is HIPAA-safe, build-clean, and architecturally honest. Operationally, nothing has been deployed to Azure, no real data has been ingested, and the seed is broken. The gap to production is roughly **18–24 hours of focused work** plus business-side gates (Ventra BAA, Paycom API access, Entra group provisioning) that are out of code scope.

---

## 2. Git and Repo State

**Branch:** `chore/local-verification`
**Latest commit:** `d69cee0 chore: local verification pass`
**Status vs origin:** 0 behind, 1 ahead of `origin/main` (this commit; PR #29 open)
**Dirty / untracked:** `hha-dashboard/docs/NEXT_BUILD_PLAN.md` (untracked, written this session)
**Author for all recent commits:** `Danda Akhil Reddy <akhilreddydanda3@gmail.com>` (single author across all 28 merged PRs)

### Recent commit log (last 10)
```
d69cee0 chore: local verification pass
90d1c12 feat(infra): close Phase 0 — acr.bicep + rbac.bicep + deploy-prod.yml (#28)
81807d4 docs: ADRs 002-005 + RUNBOOK.md + CLAUDE.md cross-refs (#27)
ad35f3b feat(api): hardening sprint — six prod-blocking fixes + FK indexes (#26)
d2354fa feat(jobs): real pg_backup image + restore drill (#25)
567cdd4 Session 12 — Alert digest + credential expiry crons (#23)
b7c1959 Session 11 — Census-only entry portal + Paycom sync stub (#22)
8bb027a feat(infra): containerjobs.bicep — Container Apps env + pg_backup job (Consumption plan) (#21)
20dc123 ci: add deploy-dev.yml workflow with OIDC federated identity (#20)
ab7a2a6 feat(infra): acs-email.bicep — Azure Communication Services + Email Managed Domain (#19)
```

### Remote
- `origin → https://github.com/DandaAkhilReddy/hhadashboard.git`
- Repository visibility: private
- 28 merged PRs, all squash-merged. CI history exists from PR #14 onward.

### Repository layout

The git root is `HHA_Dashboard_New_Joey/`, **not** `hha-dashboard/`. Two `.gitignore` files apply (root-level and `hha-dashboard/.gitignore`).

Top-level (excluding `node_modules`):

| Path | Status | Purpose |
|---|---|---|
| `hha-dashboard/` | ACTIVE | the actual codebase |
| `DASHBOARD_PLAN.md` | ACTIVE | v5 build plan; canonical scope reference |
| `UPLOAD_PIPELINE_PLAN.md` | ACTIVE | session 3 upload-pipeline detail |
| `VENTRA_REPLY_DRAFT.md` | ACTIVE | vendor-comms draft |
| `architecture.html`, `index.html`, `docs.html`, `UI_MOCKUP_v5.html` | LEGACY (planning artefacts) | early visualizations, not used by code |
| `hha_team_dashboard.html` | LEGACY | original prototype (the seed for the build) |
| `SHAREPOINT_DEEP_DIVE.md`, `SHAREPOINT_PLAN.md` | **DEAD** | superseded by Azure-only v5 plan; safe to archive |
| `samples/` | ACTIVE | test fixtures, no real data |

**Stale scaffolds:** The two SHAREPOINT_*.md files predate the v5 lock-in (Azure-only). They are not referenced by any code or active doc. Recommend archiving to `docs/archive/` to reduce confusion.

---

## 3. Detected Technology Stack

| Layer | Tool | Evidence | Confidence |
|---|---|---|---|
| Frontend framework | Next.js 15.5.15 | `web/package.json:22` | High |
| Frontend UI | React 19.0.0 | `web/package.json:23-24` | High |
| Frontend styling | Tailwind CSS 3.4.15 | `web/package.json:36`, `web/tailwind.config.ts` | High |
| Frontend charts | Recharts 2.13.3 + custom CSS sparklines | `web/package.json:25`, `web/components/CensusTrendChart.tsx` | High |
| Frontend test | Vitest 4.1.5 | `web/package.json:38` | High |
| Frontend lint/format | Biome 1.9.4 | `web/package.json:29`, `web/biome.json` | High |
| Frontend types | TypeScript 5.7.2 + openapi-typescript 7.4.2 | `web/package.json:34, 37` | High |
| Backend framework | FastAPI | `api/pyproject.toml`, `api/app/main.py:1-15` | High |
| Backend ORM | SQLAlchemy 2.0 async | `api/app/models/base.py`, `api/app/deps.py:19` | High |
| Backend driver | asyncpg + psycopg (sync for Alembic) | `api/pyproject.toml`, `api/app/settings.py` | High |
| Backend validation | Pydantic v2 + pydantic-settings | `api/app/schemas/*.py`, `api/app/settings.py:6-11` | High |
| Backend test | pytest + pytest-asyncio | `api/pyproject.toml`, `api/tests/conftest.py` | High |
| Backend lint | ruff | `api/pyproject.toml [tool.ruff]` | High |
| Backend types | mypy | `api/pyproject.toml [tool.mypy]` | High |
| Backend logging | structlog + JSON renderer | `api/app/core/logging.py:107-121` | High |
| Database | PostgreSQL 16 (with btree_gist) | `docker-compose.yml`, `api/alembic/versions/0001_initial.py` | High |
| Migration tool | Alembic | `api/alembic/`, 10 versions | High |
| Auth (web) | MSAL.js 5.8.0 + msal-react 5.3.1 | `web/package.json:16-17`, `web/lib/auth/msal-config.ts` | High |
| Auth (api) | Entra ID JWT verification (PyJWT + JWKS) | `api/app/services/entra_jwt.py` | High |
| Auth (census portal) | argon2id password + opaque session token | `api/app/services/census_auth.py` | High |
| IaC | Bicep | `hha-dashboard/infra/**/*.bicep` (10 modules + main + dev/prod params) | High |
| CI/CD | GitHub Actions (OIDC federated identity) | `.github/workflows/{ci,deploy-dev,deploy-prod}.yml` | High |
| Cloud | Azure (BAA-covered services) | `infra/main.bicep` references | High |
| Object storage | Azure Blob Storage | `infra/modules/storage.bicep`, `api/app/services/blob.py` | High |
| Email | Azure Communication Services Email | `infra/modules/acs-email.bicep`, `api/app/services/email.py` | High |
| Secrets | Azure Key Vault + Managed Identity | `infra/modules/keyvault.bicep`, `infra/main.bicep` KV-reference syntax | High |
| Observability | Application Insights + Log Analytics + Diagnostic Settings | `infra/modules/monitor.bicep` (PR #18) — provisioned, **SDK not wired** | High |
| Cron jobs | Azure Container Apps Jobs (Consumption plan) | `infra/modules/containerjobs.bicep` (PR #21) | High |
| Container registry | Azure Container Registry | `infra/modules/acr.bicep` (PR #28) — **no images pushed yet** | High |
| Local dev | docker-compose | `hha-dashboard/docker-compose.yml` (postgres + adminer + mailpit; azurite optional) | High |
| Package managers | uv (Python), npm (Node) | `api/uv.lock`, `web/package-lock.json` | High |
| Source control | Git on GitHub | `.git/`, `git remote -v` | High |

**Notable absences (confirmed by grep):**
- No Sentry, no Datadog, no New Relic — observability is Azure-native only
- No Clerk, no Auth0 — auth is Entra-direct
- No Resend, no SendGrid — email is ACS-only
- No Cloudflare, no AWS, no GCP — single cloud (Azure)
- No Railway — earlier plan considered, dropped per v5
- No Sass/Less — Tailwind only
- No Redux, no Zustand, no MobX — TanStack Query for server state, useState for local
- No Storybook, no Chromatic — no component dev environment

---

## 4. Architecture Map

### 4.1 Backend (FastAPI) — `hha-dashboard/api/`

**Entry point:** `api/app/main.py`. Lifespan handler (`:38-68`) runs startup assertions then calls `engine.dispose()` on shutdown. Three exception handlers (HTTP, RequestValidationError, Exception) registered at `:111-180`. UPN-context middleware at `:189-206` propagates `current_upn` ContextVar from request headers into the audit GUC. Health (`:209-212`) is bare; readiness (`:215-276`) checks DB + alembic head + audit trigger function + sites count.

**Auth chain (`api/app/deps.py:70-133`):**
1. **Path 1** — Real Entra JWT, only when `Authorization: Bearer <jwt>` AND `settings.entra_configured`. Calls `services/entra_jwt.verify_access_token` (lazy import for testability).
2. **Path 2** — Dev stub, only when `ENV=dev` AND `Authorization: Dev <role>`. Validates `<role>` against a hardcoded `VALID_DEV_ROLES` set.
3. **Path 3** — Default admin, **only when `ENV=dev` AND `not settings.entra_configured` AND no header**. Returns `CurrentUser(upn="dev-default@local", roles={"admin"}, comp_viewer=True)`. Belt-and-suspenders against accidental prod misconfig.
4. Otherwise 401.

**Routers (11 files, all registered in `main.py:303-312`):**
- `sites.py` — 1 route: `GET /api/v1/sites` → `list[SiteOut]`
- `operations.py` — 3 routes: `/summary`, `/sites-today`, `/sites/{site_id}`
- `finance.py` — 4 routes: `/today`, `/ar-aging`, `/kpis`, `/monthly-trend`
- `clinical.py` — 2 routes: `/summary`, `/credentials-expiring`
- `people.py` — 2 routes: `/summary`, `/open-positions-by-site`
- `scorecards.py` — 1 route: `GET /api/v1/scorecards`, comp redaction via `user.comp_viewer` flag
- `alerts.py` — 2 routes: `/api/v1/alerts`, `/api/v1/meta`
- `uploads.py` — 2 routes: `POST /api/v1/uploads`, `GET /api/v1/uploads`
- `entries.py` — 8 routes (4 GET + 4 POST): daily-census, monthly-finance, weekly-clinical, weekly-hr, each role-gated
- `census_portal.py` — 4 routes: `/login`, `/sites`, `/logout`, `/daily-census`. Cookie-gated, no Entra, separate threat model.

**Services (12 files, `api/app/services/`):**
- `audit.py` — `current_upn` ContextVar + `AUDITED_TABLES` frozenset (9 tables, matches migration 0007)
- `alert_engine.py` — `compute_alerts_for_date()` returns variance candidates; falls back to fake_data
- `blob.py` — Azure Blob Storage wrapper (upload, delete, ensure container)
- `census_auth.py` — argon2id verify, session-token issuance, lockout (10 fails → 15-min lock)
- `comp.py` — physician compensation math (effective comp, below-FMV)
- `email.py` — ACS Email wrapper, lazy SDK import, `is_configured` short-circuit, Jinja2 templates
- `entra_jwt.py` — Entra JWT verify (signature against tenant JWKS, `iss`/`aud`/`exp`/`nbf` checks); claim extraction (UPN, groups → roles)
- `entries_history.py` — `get_site_recent_entries(db, site_id, days=14)` for site detail page
- `fake_data.py` — **load-bearing for the read path.** Provides deterministic synthetic data for every board. Routers prefer DB but fall back to fake when DB is empty.
- `pdf_extract.py` — Azure Document Intelligence wrapper. Has SDK overload mismatch at line 181.
- `email_templates/` — Jinja2 HTML templates for `alert_digest` and `cred_scan`

**Models (11 files, all in `api/app/models/`):**
- `base.py` — `Base`, `TimestampMixin`, `DataClass` enum (A/B/C/D)
- `masters.py` — sites, contracts, physicians, comp_agreements (with GIST exclusion no-overlap), credentials, site_coverage
- `entries.py` — daily_entries
- `entries_finance.py` — monthly_finance_manual (with `source_system` CHECK constraint per ADR-005)
- `entries_clinical.py` — weekly_clinical
- `entries_hr.py` — weekly_hr_manual
- `audit.py` — audit_log
- `alerts.py` — alert_subscriptions, alert_log, credential_alert_log
- `uploads.py` — upload_log
- `census_credentials.py` — census_credentials (single-row, CHECK id=1)

**Logging (`api/app/core/logging.py`):** structlog with JSON renderer. PII redactor (`_redact_pii_processor`) is **first** in the processor chain, recursive into dicts and lists. Redacts ~40 key prefixes (case-insensitive): credentials, sessions, auth, email/upn, MRN, member_id, subscriber_*, claim_id, patient_*, etc.

### 4.2 Database (PostgreSQL 16) — `api/alembic/`

**Schemas:** `masters`, `entries`, `facts` (reserved, not yet populated), `audit`, `alerts`, `dims` (reserved), `auth`, `uploads`. `btree_gist` extension enabled (for the `comp_agreements` no-overlap exclusion constraint).

**Migration chain (10 migrations, linear):**

| # | Title | Adds | Downgrade |
|---|---|---|---|
| 0001 | initial | 6 schemas + 6 masters tables + GIST exclusion on comp_agreements | ✓ |
| 0002 | entries_audit_uploads | daily_entries, audit_log, upload_log | ✓ |
| 0003 | monthly_finance_manual | monthly_finance_manual table | ✓ |
| 0004 | weekly_clinical | weekly_clinical table | ✓ |
| 0005 | weekly_hr_manual | weekly_hr_manual table | ✓ |
| 0006 | ventra_athena_source | adds `source_system` column (CHECK constraint per ADR-005) + `athena_provider_id` to physicians | ✓ |
| 0007 | audit_triggers | `audit.log_change()` PL/pgSQL function + triggers on 9 sensitive tables | ✓ |
| 0008 | census_credentials | `auth` schema + census_credentials (CHECK id=1) | ✓ |
| 0009 | alerts_schema | alert_subscriptions, alert_log, credential_alert_log | ✓ |
| 0010 | fk_indexes | indexes on FK columns (perf) | ✓ |

**Single head:** `0010` (verified via `uv run alembic heads`). DB at `0010`. No branched migrations.

**Audit triggers:** Migration 0007 creates `audit.log_change()` and attaches `BEFORE INSERT/UPDATE/DELETE` to 9 tables. Match between `services/audit.py::AUDITED_TABLES` and the migration is exact (cross-verified). Triggers read `audit.upn` GUC, compute diff (with `updated_at`-only changes filtered out), write to `audit.audit_log`.

**Seed:** `scripts/seed_sites.py` exists, intended to insert 11 sites + FL contracts + named medical directors. Currently broken (bails on any existing row; see Section 9.4).

### 4.3 Frontend (Next.js 15) — `hha-dashboard/web/`

**Layout:** `web/app/layout.tsx` wraps every page in `<AuthProvider>` (which conditionally provides `<MsalProvider>` + `<QueryClientProvider>`) plus `<TopNav>` and `<Toaster>`.

**Middleware (`web/middleware.ts`):** Two independent gating paths.
1. Dashboard paths gate on `hha_session` cookie. Dev mode (`NEXT_PUBLIC_AUTH_MODE=dev`) bypasses all checks.
2. `/census/*` paths gate on `census_session` cookie. **Always enforced** regardless of AUTH_MODE.

**Pages (17 page.tsx files):**

| Route | File | Type | Data | Auth |
|---|---|---|---|---|
| `/` | `app/page.tsx` | Server | 7 API endpoints | dashboard |
| `/operations` | `app/operations/page.tsx` | Server | operationsSummary + sitesToday | dashboard |
| `/operations/[siteId]` | `app/operations/[siteId]/page.tsx` | Server (renders `SiteCensusForm` client) | siteDetail | dashboard |
| `/finance` | `app/finance/page.tsx` | Server | 4 finance endpoints | dashboard |
| `/clinical` | `app/clinical/page.tsx` | Server | 2 clinical endpoints | dashboard |
| `/people` | `app/people/page.tsx` | Server | 2 people endpoints | dashboard |
| `/scorecards` | `app/scorecards/page.tsx` | Server | scorecards | dashboard |
| `/uploads` | `app/uploads/page.tsx` | Server (renders `UploadDropZone` client) | listUploads | dashboard |
| `/daily-census` | `app/daily-census/page.tsx` | Server (renders `DailyCensusForm` client) | getDailyCensus | dashboard |
| `/monthly-finance` | `app/monthly-finance/page.tsx` | Server (renders `MonthlyFinanceForm` client) | getMonthlyFinance | dashboard |
| `/weekly-clinical` | `app/weekly-clinical/page.tsx` | Server (renders `WeeklyClinicalForm` client) | getWeeklyClinical | dashboard |
| `/weekly-hr` | `app/weekly-hr/page.tsx` | Server (renders `WeeklyHrForm` client) | getWeeklyHr | dashboard |
| `/census/login` | `app/census/login/page.tsx` | Client | direct fetch to `/api/v1/census-portal/login` | none (public) |
| `/census/entry` | `app/census/entry/page.tsx` | Server (uses `cookies()`) → `CensusEntryForm` client | census-portal/sites | census cookie |
| `/auth/sign-in` | `app/auth/sign-in/page.tsx` | Client (Suspense-wrapped after PR #29) | MSAL `loginRedirect` | public |
| `/auth/sign-out` | `app/auth/sign-out/page.tsx` | Client (no Suspense — minor risk) | MSAL `logoutRedirect` + DELETE cookie | public |
| `/auth/callback` | `app/auth/callback/page.tsx` | Client (Suspense-wrapped after PR #29) | MSAL `handleRedirectPromise` + POST cookie | public |

**Lib (`web/lib/`):**
- `api-client.ts` — server-side API client. Reads `hha_session` cookie via `cookies()` from `next/headers`. Used by server components only.
- `api-browser.ts` — `useApiBrowser()` hook. MSAL `acquireTokenSilent` for the bearer token. Used by client components only.
- `api-fetch.ts` — pure fetcher with injected auth header. Shared boundary.
- `api-types.ts` — generated from OpenAPI (`npm run gen-types`). Currently untracked despite `.gitignore` saying it should be committed. PR #29 adds it.
- `auth/msal-config.ts` — MSAL singleton, gated on `NEXT_PUBLIC_AZURE_*` env presence.
- `auth/server-session.ts` — reads encrypted cookie server-side. Imports `next/headers`. **Cannot be imported by any "use client" file.** This was the PR #29 P0 fix.
- `auth/session-crypto.ts` — AES-GCM encrypt/decrypt with `SESSION_SECRET`.
- `auth/use-user.ts` — client hook, fetches `/api/auth/me`.
- `auth/with-auth.ts` — server-page wrapper that catches `UnauthenticatedError` → `redirect('/auth/sign-in')`.

**Components (`web/components/`):** 10 components, all imported and used. None unused.

### 4.4 Jobs — `hha-dashboard/jobs/`

| Folder | Purpose | Status | Schedule (Bicep) | Idempotency | Tests |
|---|---|---|---|---|---|
| `pg_backup/` | Nightly Postgres dump → Blob WORM | **DONE** (PR #25) | `0 3 * * *` | tag-based; restore_drill.sh | `test_job_pg_backup.py` (14 tests; integration skipped if pg_dump not on PATH) |
| `alert_digest/` | Variance email digest | **DONE** (PR #23) | `0 11 * * 1-5` | `alert_log` unique on `(alert_id, target_date, recipient)` | `test_job_alert_digest.py` |
| `cred_scan/` | Credential expiry alert | **DONE** (PR #23) | `0 12 * * *` | `credential_alert_log` unique on `(credential_id, threshold_band)` | `test_job_cred_scan.py` |
| `upload_ingest/` | Process uploaded PDFs | **PARTIAL** | event-driven, polled every 15 min | `upload_log` claim with `FOR UPDATE SKIP LOCKED` | `test_job_census_pdf.py` (extractor tests; SDK overload not caught) |
| `paycom_sync/` | Pull workforce data from Paycom API | **STUB** (waiting on Paycom API access — F1 in plan) | `0 4 * * *` | n/a | `test_paycom_sync_stub.py` (verifies stub returns no-op) |
| `ventra_ingest/` | Pull RCM data from Ventra | **STUB** (waiting on Ventra contract — F1 in plan) | event-driven once shape lands | `audit.ventra_jobs` queue (claim-skip-locked) | `test_ventra_ingest.py`, `test_ventra_parser.py` |

All jobs follow the `is_configured` short-circuit pattern (e.g., `email_configured`, `paycom_configured`) — they exit cleanly with an info log when prerequisites aren't set, rather than crashing.

### 4.5 Infrastructure (Bicep) — `hha-dashboard/infra/`

10 modules + `main.bicep` + `env/{dev,prod}.bicepparam` + 3 shell scripts + 1 README:

| Module | Purpose | Status |
|---|---|---|
| `vnet.bicep` | VNet 10.20.0.0/16 with 3 subnets + 2 private DNS zones | DONE (PR #15) |
| `postgres.bicep` | Flex Server 16, parameter-driven public/private posture | DONE |
| `appservice.bicep` | Plan + 2 sites (web/api), httpsOnly, MI, regional VNet integration | DONE (PR #16) |
| `keyvault.bicep` | RBAC mode, soft-delete, purge protection, optional PE | DONE (PR #15) |
| `storage.bicep` | Backups + uploads containers, soft-delete, RA-GRS in prod | DONE (PR #17) |
| `monitor.bicep` | App Insights + Log Analytics + Diagnostic Settings on every audited resource | DONE (PR #18) |
| `acs-email.bicep` | ACS + Email Communications + Managed Domain | DONE (PR #19) |
| `containerjobs.bicep` | Container Apps environment + 6 jobs (3 real, 3 stub-by-toggle) | DONE (PR #21) |
| `acr.bicep` | Container Registry, Standard SKU, soft-delete 7d | DONE (PR #28) |
| `rbac.bicep` | 7 role assignments (AcrPull, BlobContributor, AcsContributor) | DONE (PR #28) |

**Bicep build:** all clean (`az bicep build` exit 0, lint zero warnings, PR #28 verified).
**Workflows:** `ci.yml` (gates every PR with bicep+pytest+vitest+npm build), `deploy-dev.yml` (PR #20), `deploy-prod.yml` (PR #28 — three safeguards: GitHub Environment, federated subject, confirm string).

---

## 5. Feature Completeness Matrix

| # | Area | Status | Evidence | Verification cmd | Gaps | Owner |
|---|---|---|---|---|---|---|
| 1 | Backend API foundation | **DONE** | `api/app/main.py:38-68` lifespan, `:189-276` middleware + health/ready | `uvicorn app.main:app + curl /ready` | none | Claude Code |
| 2 | Backend routing | **DONE** | 11 routers wired in `main.py:303-312`, 27 routes total | OpenAPI at `/docs` | none | Claude Code |
| 3 | Backend validation | **DONE** | Pydantic v2 schemas in `api/app/schemas/`, fail-fast 422 | `test_entries_router.py` | none | Claude Code |
| 4 | Backend exception handling | **DONE** | 3 handlers `main.py:111-180`, correlation_id round-trip | `test_main_hardening.py` | none | Claude Code |
| 5 | Backend readiness checks | **DONE** | `/ready` checks DB + alembic head + audit trigger + sites > 0 (`main.py:215-276`) | `curl /ready` | sites>0 check fails today (1 row) | Claude Code |
| 6 | Backend logging | **DONE** | structlog JSON, processor chain `core/logging.py:107-121` | inspect log output | none | Claude Code |
| 7 | PII/HIPAA-safe log redaction | **DONE** | `_redact_pii_processor` first in chain, ~40 key patterns | unit test in `test_main_hardening.py` | none | Claude Code |
| 8 | AuthN — Entra JWT verify | **DONE** | `services/entra_jwt.py` verifies sig + iss/aud/exp/nbf | `test_entra_jwt.py` | mypy Any-leak at lines 77,87 (P1 fix) | Claude Code |
| 9 | AuthZ — RBAC | **DONE** | `deps.py::require_role` + `require_comp_viewer`, 7 roles wired | `test_deps_auth_fallthrough.py` | no end-to-end test against real Entra tenant | Claude Code |
| 10 | Database schema | **DONE** | 16 tables across 7 schemas, all `data_class`-tagged | `test_schema_classification.py` | none | Claude Code |
| 11 | Alembic migrations | **DONE** | 10 migrations, linear chain, all reversible | `alembic upgrade head; downgrade -1; upgrade head` | no automated round-trip test | Claude Code |
| 12 | Audit triggers | **DONE** | Migration 0007 + `services/audit.py::AUDITED_TABLES` (9 tables, exact match) | `test_audit_triggers.py` against real PG | only `daily_entries` exercised by tests; other 8 tables unverified | Claude Code |
| 13 | Seed data for 11 sites | **BROKEN** | `scripts/seed_sites.py:125-129` bails on any existing row; DB has 1 stray row | `psql -c "SELECT count(*) FROM masters.sites"` → 1 | upsert-by-name needed | Claude Code |
| 14 | Operations API | **PARTIAL** | 3 routes wired; `services/fake_data.py` is the data source | `curl /api/v1/operations/sites-today` | DB-backed only when entries exist; today reads from fake_data | Claude Code |
| 15 | Finance API | **PARTIAL** | 4 routes wired; same fake_data dependency | `curl /api/v1/finance/today` | same pattern | Claude Code |
| 16 | Clinical API | **PARTIAL** | 2 routes wired; same fake_data dependency | `curl /api/v1/clinical/summary` | same pattern | Claude Code |
| 17 | People API | **PARTIAL** | 2 routes wired; same fake_data dependency | `curl /api/v1/people/summary` | same pattern | Claude Code |
| 18 | Scorecards API | **PARTIAL** | 1 route wired; comp redaction via `comp_viewer` flag | `test_scorecards_router.py` | same fake_data; needs Paycom + Ventra | Claude Code + Vendor |
| 19 | Alerts API | **DONE** | `alert_engine.compute_alerts_for_date` real, falls back to fake | `test_alerts_router.py` | none | Claude Code |
| 20 | Uploads API | **DONE** | POST/GET wired, role-gated, blob upload | `test_uploads_router.py` | extractor crashes on PDFs (T8) | Claude Code |
| 21 | Census portal API | **DONE** | 4 routes, separate auth surface | `test_census_portal.py` | none | Claude Code |
| 22 | Daily census entry | **DONE** | `POST /entries/daily-census`, audit trail | `test_entries_router.py` | none | Claude Code |
| 23 | Weekly clinical entry | **DONE** | wired, audit trail | `test_weekly_clinical_router.py` | none | Claude Code |
| 24 | Weekly HR entry | **DONE** | wired, audit trail | `test_weekly_hr_router.py` | none | Claude Code |
| 25 | Monthly finance entry | **DONE** | wired with `source_system` constraint | `test_monthly_finance_router.py` | none | Claude Code |
| 26 | Frontend shell/layout | **DONE** | `app/layout.tsx`, `TopNav.tsx` | `npm run build` | none | Claude Code |
| 27 | Frontend auth gate | **DONE** | `middleware.ts` cookie-presence check | `__tests__/middleware.test.ts` | no expiry check (cookie + JWT can drift) | Claude Code |
| 28 | Operations dashboard page | **PARTIAL** | renders; data is fake | manual browser open | needs T1 (real seed) | Claude Code |
| 29 | Finance dashboard page | **PARTIAL** | renders; data is fake; no FL/TX labels | manual browser open | T2 (provenance labels) | Claude Code |
| 30 | Clinical dashboard page | **PARTIAL** | renders; data is fake | manual browser open | needs real ingestion | Claude Code |
| 31 | People dashboard page | **PARTIAL** | renders; data is fake; needs Paycom | manual browser open | Vendor (Paycom API) | Claude Code + Vendor |
| 32 | Scorecards page | **PARTIAL** | renders; comp redaction frontend-only | manual browser open | needs Paycom + Ventra | Claude Code + Vendor |
| 33 | Uploads page | **PARTIAL** | renders, accepts files; extractor crashes | manual browser open | T8 (pdf_extract fix) | Claude Code |
| 34 | Census portal page | **DONE** | login + entry forms | manual browser open | no test for happy path in browser | Claude Code |
| 35 | Data-entry forms | **DONE** | 5 forms (daily, monthly, weekly_clinical, weekly_hr, uploads) all wired to `useApiBrowser` | manual + `next build` | silent error swallow (`.catch(() => [])`) | Claude Code |
| 36 | Frontend API client | **DONE** | server/browser split, generated types | `npm run typecheck` | none after PR #29 | Claude Code |
| 37 | Frontend fake data isolation | **NOT STARTED** | no UI banner indicating "synthetic data" | grep `web/app/` for "fake" or "synthetic" | bug — execs could be misled in demo | Claude Code |
| 38 | Ventra/Athena ingestion | **NOT STARTED** | `jobs/ventra_ingest/` is a stub | n/a | data shape unknown — F1 standing fact | Vendor (Ventra) |
| 39 | 835/837/CSV ingestion readiness | **NOT STARTED** | scaffolding only in extractors registry | n/a | depends on Ventra delivery shape | Vendor (Ventra) |
| 40 | Paycom ingestion | **NOT STARTED** | `jobs/paycom_sync/` is a stub | `test_paycom_sync_stub.py` | API access not granted (4–6 wk window) | Vendor (Paycom) |
| 41 | Credential scan job | **DONE** | `jobs/cred_scan/` real, idempotent | `test_job_cred_scan.py` | needs subscriber rows seeded | Claude Code + Akhil |
| 42 | Alert digest job | **DONE** | `jobs/alert_digest/` real | `test_job_alert_digest.py` | same | Claude Code + Akhil |
| 43 | Backup job | **DONE** | `jobs/pg_backup/` real, image buildable | `test_job_pg_backup.py` | image not pushed to ACR yet | Claude Code |
| 44 | Restore drill | **PARTIAL** | `scripts/restore_drill.sh` exists, syntax-clean | `bash -n` PASS | never executed against real backup | Claude Code |
| 45 | Local Docker/dev env | **DONE** | `docker-compose.yml` (postgres + adminer + mailpit) | `docker compose up -d` | azurite pull intermittently fails (transient, non-blocking) | Claude Code |
| 46 | Env var documentation | **PARTIAL** | `.env.example` exists; web `.env.example` exists | grep | `SESSION_SECRET` not declared in web/.env.example | Claude Code |
| 47 | CI pipeline | **DONE** | `.github/workflows/ci.yml` runs pytest + bicep + lint + build | `gh run list` | biome lint fails on CRLF (T3) | Claude Code |
| 48 | Deploy-dev workflow | **DONE** | `deploy-dev.yml` PR #20 with OIDC | manual `gh workflow run` | never executed against real Azure sub | Claude Code + Akhil |
| 49 | Deploy-prod workflow | **DONE** | `deploy-prod.yml` PR #28 — 3 safeguards | manual run | same — never run | Claude Code + Akhil |
| 50 | Azure infra | **NOT STARTED (deploy-side)** | Bicep all builds; no `az deployment group create` ever run | n/a | Akhil must create subscription + Entra app regs + first deploy | Akhil + HHA leadership |
| 51 | Railway deployment | **NOT STARTED (deliberate)** | per v5 plan, Railway has no BAA — explicitly rejected | n/a | none — out of scope | n/a |
| 52 | Observability/App Insights | **PARTIAL** | provisioned (PR #18); SDK not wired | manual log inspection | T6 (SDK + correlation IDs) | Claude Code |
| 53 | Runbooks | **DONE** | `docs/RUNBOOK.md` PR #27 (6 sections, 7 incident playbooks) | manual review | first-deploy procedure never executed | Claude Code |
| 54 | ADRs | **DONE** | 5 ADRs in `docs/adr/`, all current | manual review | none | Claude Code |
| 55 | HIPAA/data classification docs | **DONE** | ADR-001 + `test_schema_classification.py` enforcement | `pytest tests/test_schema_classification.py` | none | Claude Code |
| 56 | Business requirements docs | **DONE** | `DASHBOARD_PLAN.md` v5 (1500+ lines, current) | manual review | F1, F2 captured | Akhil |
| 57 | Test coverage | **PARTIAL** | 207 backend tests; 20 frontend | `pytest`, `npm run test` | no E2E, no React component, no Playwright | Claude Code |
| 58 | Type checking | **PARTIAL** | tsc clean; mypy 48 errors | `mypy app/`, `tsc --noEmit` | T7, T8 + bulk dict cleanup | Claude Code |
| 59 | Linting | **PARTIAL** | ruff clean; biome 38 CRLF errors | `ruff check`, `npm run lint` | T3 (CRLF normalization) | Claude Code |
| 60 | Production readiness | **NOT STARTED** | nothing deployed; secrets unseeded; Entra not wired | end-to-end deploy | T1–T9 + business gates | Claude Code + Akhil + HHA |

---

## 6. Verification Results

Captured during this audit and the PR #29 verification pass.

### Repo
```
git status --short            → 1 untracked (NEXT_BUILD_PLAN.md)
git branch --show-current     → chore/local-verification
git log --oneline -10         → 10 commits, latest d69cee0
```

### Backend (`hha-dashboard/api/`)
| Command | Result |
|---|---|
| `uv sync` | PASS |
| `uv run ruff check .` | PASS (zero violations) |
| `uv run mypy app/` | FAIL — 48 errors / 13 files (mostly `dict` annotations + 2 real bugs) |
| `uv run pytest --tb=short -q` | PASS — 207 passed / 1 skipped / 0 failed (208 collected) |
| `uv run alembic heads` | PASS — single head `0010` |
| `uv run alembic current` | PASS — `0010` (DB matches) |
| `uv run alembic upgrade head` | PASS — no-op (already at head) |
| `uvicorn app.main:app + curl /ready` | PASS — returns `{db: ok, schema: ok, audit_trigger: ok, sites: ok}` |
| `curl /api/v1/sites` | PASS — returns 1 row (only "Test Site"; canonical 11 missing — see Section 9.4) |

### Frontend (`hha-dashboard/web/`)
| Command | Result |
|---|---|
| `node_modules` present | YES |
| `npm run lint` | FAIL — 38 biome violations, all CRLF |
| `npm run typecheck` | PASS (zero errors) |
| `npm run test` | PASS — 4 files, 20/20 in 0.6s |
| `npm run gen-types` | PASS (against running api on :8000) |
| `npm run build` | PASS (after PR #29 fixes — was 11/13 routes 500 before) |

### Infra
| Command | Result |
|---|---|
| `az bicep build main.bicep` | PASS |
| `az bicep build-params env/dev.bicepparam` | PASS |
| `az bicep build-params env/prod.bicepparam` | PASS |
| `az bicep lint main.bicep` | PASS (zero warnings) |
| `az bicep lint` per module (×10) | PASS each |
| `docker compose config -q` | PASS |
| `python yaml.safe_load` on each workflow | PASS (3/3) |
| `bash -n` on each shell script | PASS (4/4) |

### Failures recorded but NOT fixed
| Command | Failure | Why | Demo blocker? | Prod blocker? |
|---|---|---|---|---|
| `uv run mypy app/` | 48 errors | T7 + T8 + bulk `dict` annotations | No | Partly (T7 silent role bypass risk) |
| `npm run lint` | 38 CRLF | no `.gitattributes`, no pre-commit hook | No | Yes (CI gate) |
| `psql -c "SELECT count(*) FROM masters.sites"` | 1 row | seed_sites.py bails on existing rows | **Yes** | Yes |

---

## 7. Backend Route Inventory

(Full table — every route, every method, every gate.)

| Router | Method + Path | Auth dep | Roles | Request | Response | Tables | Test | Status |
|---|---|---|---|---|---|---|---|---|
| sites | `GET /api/v1/sites` | UserDep | any | — | `list[SiteOut]` | `masters.sites` | none | DONE |
| operations | `GET /api/v1/operations/summary` | UserDep | any | — | `OperationsSummary` | (fake_data) | partial | PARTIAL |
| operations | `GET /api/v1/operations/sites-today` | UserDep | any | — | `list[SiteToday]` | (fake_data) | partial | PARTIAL |
| operations | `GET /api/v1/operations/sites/{site_id}` | UserDep | any | — | `SiteDetail` | `entries.daily_entries`, `masters.sites` | `test_site_detail.py` | DONE |
| finance | `GET /api/v1/finance/today` | UserDep | any | — | `FinanceToday` | (fake_data) | `test_finance_read_prefers_db.py` | PARTIAL |
| finance | `GET /api/v1/finance/ar-aging` | UserDep | any | — | `ArAging` | (fake_data) | none | PARTIAL |
| finance | `GET /api/v1/finance/kpis` | UserDep | any | — | `FinanceKpis` | (fake_data) | none | PARTIAL |
| finance | `GET /api/v1/finance/monthly-trend` | UserDep | any | — | `list[MonthRevenue]` | (fake_data) | none | PARTIAL |
| clinical | `GET /api/v1/clinical/summary` | UserDep | any | — | `ClinicalSummary` | (fake_data) | `test_clinical_read_prefers_db.py` | PARTIAL |
| clinical | `GET /api/v1/clinical/credentials-expiring` | UserDep | any | — | `list[CredentialExpiring]` | `masters.credentials` | none | PARTIAL |
| people | `GET /api/v1/people/summary` | UserDep | any | — | `PeopleSummary` | (fake_data) | `test_people_read_prefers_db.py` | PARTIAL |
| people | `GET /api/v1/people/open-positions-by-site` | UserDep | any | — | `list[OpenPositionBySite]` | (fake_data) | none | PARTIAL |
| scorecards | `GET /api/v1/scorecards` | UserDep | any | — | `list[ScorecardOut]` | (fake_data); comp via `user.comp_viewer` | `test_scorecards_router.py` | PARTIAL |
| alerts | `GET /api/v1/alerts` | UserDep | any | — | `list[Alert]` | `entries.*` (via alert_engine), fallback fake | `test_alerts_router.py` | DONE |
| alerts | `GET /api/v1/meta` | none | — | — | `Meta` | (fake_data) | none | DONE |
| uploads | `POST /api/v1/uploads` | UploaderDep | admin, owner_* | UploadFile + FileType | `UploadAcceptedOut` | `uploads.upload_log` | `test_uploads_router.py` | DONE |
| uploads | `GET /api/v1/uploads` | UserDep | any | since_id, limit | `list[UploadOut]` | `uploads.upload_log` | same | DONE |
| entries | `GET /api/v1/entries/daily-census` | CensusOwnerDep | admin, owner_ops | date | `list[DailyEntryOut]` | `entries.daily_entries`, `masters.sites` | `test_entries_router.py` | DONE |
| entries | `POST /api/v1/entries/daily-census` | CensusOwnerDep | admin, owner_ops | `DailyCensusBatchIn` | `list[DailyEntryOut]` | upsert | same | DONE |
| entries | `GET /api/v1/entries/monthly-finance` | FinanceOwnerDep | admin, owner_finance | year, month | `list[MonthlyFinanceRowOut]` | `entries.monthly_finance_manual` | `test_monthly_finance_router.py` | DONE |
| entries | `POST /api/v1/entries/monthly-finance` | FinanceOwnerDep | admin, owner_finance | `MonthlyFinanceBatchIn` | `list[MonthlyFinanceRowOut]` | upsert with source_system | same | DONE |
| entries | `GET /api/v1/entries/weekly-clinical` | ClinicalOwnerDep | admin, owner_clinical | week_ending | `list[WeeklyClinicalRowOut]` | `entries.weekly_clinical` | `test_weekly_clinical_router.py` | DONE |
| entries | `POST /api/v1/entries/weekly-clinical` | ClinicalOwnerDep | admin, owner_clinical | `WeeklyClinicalBatchIn` | `list[WeeklyClinicalRowOut]` | upsert | same | DONE |
| entries | `GET /api/v1/entries/weekly-hr` | HrOwnerDep | admin, owner_hr | week_ending | `WeeklyHrOut \| None` | `entries.weekly_hr_manual` | `test_weekly_hr_router.py` | DONE |
| entries | `POST /api/v1/entries/weekly-hr` | HrOwnerDep | admin, owner_hr | `WeeklyHrIn` | `WeeklyHrOut` | upsert | same | DONE |
| census_portal | `POST /api/v1/census-portal/login` | none | — | `LoginIn` | `PortalLoginOut` | `auth.census_credentials`, `masters.sites` | `test_census_portal.py` | DONE |
| census_portal | `GET /api/v1/census-portal/sites` | CredentialDep (cookie) | — | — | `PortalLoginOut` | `masters.sites`, `entries.daily_entries` | same | DONE |
| census_portal | `POST /api/v1/census-portal/logout` | CredentialDep | — | — | `{status: logged_out}` | `auth.census_credentials` | same | DONE |
| census_portal | `POST /api/v1/census-portal/daily-census` | CredentialDep | — | `PortalCensusBatchIn` | `list[PortalCensusOut]` | `entries.daily_entries` upsert | same | DONE |

**Total:** 30 routes across 11 routers. 14 DONE, 12 PARTIAL (read-side fake_data fallback), 4 in census-portal sub-domain.

---

## 8. Frontend Page Inventory

(See also Section 4.3 for the full table; this section adds state-coverage flags.)

| Path | Type | Loading state | Error state | Empty state | Status |
|---|---|---|---|---|---|
| `/` | server | none | none | none | PARTIAL (no error UX) |
| `/operations` | server | none | none | none | PARTIAL |
| `/operations/[siteId]` | server + client form | none | `notFound()` | none | PARTIAL |
| `/finance` | server | none | none | none | PARTIAL |
| `/clinical` | server | none | none | none | PARTIAL |
| `/people` | server | none | none | none | PARTIAL |
| `/scorecards` | server | none | none | none | PARTIAL |
| `/uploads` | server + client | none | `.catch(() => [])` silent | yes (no rows hint) | PARTIAL |
| `/daily-census` | server + client | none | `.catch(() => [])` silent | yes (no rows hint in form) | PARTIAL |
| `/weekly-clinical` | same shape | none | silent | yes | PARTIAL |
| `/weekly-hr` | same | none | silent | yes | PARTIAL |
| `/monthly-finance` | same | none | silent | yes | PARTIAL |
| `/census/login` | client | none | yes (423 / 401) | n/a | DONE |
| `/census/entry` | server + client form | none | redirect | n/a | DONE |
| `/auth/sign-in` | client (Suspense) | Suspense fallback | yes | n/a | DONE |
| `/auth/callback` | client (Suspense) | Suspense fallback | yes | n/a | DONE |
| `/auth/sign-out` | client | none | none | n/a | PARTIAL (no Suspense) |

**Pattern:** Form pages silently swallow API errors. A user whose save fails sees no toast unless the failure happens during the explicit save handler (which has `try/catch` + `toast`). The initial fetch errors are eaten.

---

## 9. Database and Migration Audit

### 9.1 Schemas (7 active + 2 reserved)

| Schema | Tables | Purpose |
|---|---|---|
| `masters` | sites, contracts, physicians, comp_agreements, credentials, site_coverage | directory + business reference |
| `entries` | daily_entries, weekly_clinical, weekly_hr_manual, monthly_finance_manual | manual / automated data entry |
| `audit` | audit_log | mutation history |
| `alerts` | alert_subscriptions, alert_log, credential_alert_log | notifications |
| `auth` | census_credentials | census portal auth |
| `uploads` | upload_log | file ingestion queue |
| `facts` | (reserved) | future: pre-aggregated daily/monthly facts |
| `dims` | (reserved) | future: dim_date |

### 9.2 Tables and column count (data_class coverage 100%)

Inventory matches Section 4.2. Every column is `data_class`-tagged. Aggregate count: 16 tables, ~184 columns, all classified A/B/D. **Zero Tier C** (PHI / claim-level).

### 9.3 Indexes (post PR #26 / migration 0010)

FK indexes on:
- `masters.site_coverage(site_id)`, `(physician_id)`
- `masters.contracts(site_id)`
- `masters.credentials(physician_id)`, `(hospital_id)`
- `masters.comp_agreements(physician_id)`
- `entries.daily_entries(site_id, entry_date)` — unique
- `entries.monthly_finance_manual(year, month, state)` — unique
- `entries.weekly_clinical(week_ending, state)` — unique

Plus the audit-log time-range index on `(changed_at DESC)`.

### 9.4 Seed status — BROKEN

`SELECT count(*) FROM masters.sites` returns **1** ("Test Site"). Per ADR-005 and CLAUDE.md, the canonical 11 sites (7 FL + 4 TX) should be the seed. `scripts/seed_sites.py:125-129` bails on any existing row, so the canonical seed cannot land while the stray row exists.

**Why the dashboard appears to work:** `services/fake_data.py` synthesises 11-site rows for every read path. The frontend never knows the database is sparse. On a fresh deploy with no fake fallback, the dashboard would render 1 site.

### 9.5 Audit triggers — verified end-to-end

`audit.log_change()` PL/pgSQL function (migration 0007) attached to:
- `masters.physicians`, `comp_agreements`, `contracts`, `credentials`, `site_coverage`
- `entries.daily_entries`, `monthly_finance_manual`, `weekly_clinical`, `weekly_hr_manual`

Tested in `test_audit_triggers.py` against real Postgres: INSERT writes one audit row with `{"new": {...}}`, UPDATE writes `{col: {"old": x, "new": y}}` with timestamps stripped, DELETE writes `{"old": {...}}`. Cross-recursion (audit_log itself) doesn't trigger. **Only `entries.daily_entries` is exercised**; the other 8 audited tables are unverified by tests.

### 9.6 Test DB strategy

`api/tests/conftest.py` is 4 lines and creates no DB fixture. The 207 tests run against the live Docker Postgres (assumed up by `docker compose up -d`). There is no SQLite shim; test fidelity is therefore "real Postgres" but tests share a database with manual dev work — relies on per-test cleanup (each test that mutates uses transactions or table truncation in a fixture defined per-file).

---

## 10. Data Classification and HIPAA Risk

### 10.1 Tier breakdown

| Tier | Definition | Count of columns | Examples |
|---|---|---|---|
| A | Public operational | ~110 | site_name, state, entry_date, census, total_patients |
| B | Internal business confidential | ~70 | upn, email, contract_terms, ar_aging_buckets, audit diff |
| C | Limited Data Set / claim-level | **0** | (forbidden — none persist) |
| D | Sensitive — physician comp / FMV | ~10 | base_salary_usd, rvu_rate_usd, fmv_benchmark_usd |

### 10.2 Forbidden field scan — CLEAN

Grep across the entire codebase for `claim_id`, `encounter_id`, `patient_*`, `mrn`, `member_id`, `subscriber_*`, `guarantor_*`, `dos_per_line`, `cpt_per_line`:
- **Production code:** zero matches in any model, schema, router, or service.
- **Test code:** matches only inside `tests/test_schema_classification.py:23-48` (the `FORBIDDEN_COLUMN_NAMES` list itself, used for assertion).
- **Comments:** matches only inside `api/alembic/versions/0007_audit_triggers.py` and `api/app/core/logging.py:50` (documenting why these names are scrubbed/audited).

### 10.3 Test enforcement (`api/tests/test_schema_classification.py`)

Five assertions, all passing:
1. `test_no_columns_with_data_class_c()` — zero `DataClass.C` columns
2. `test_every_column_has_data_class()` — every column has `info["data_class"]`
3. `test_no_forbidden_column_names()` — no `claim_id`, `patient_*`, etc.
4. `test_data_class_values_are_valid()` — only A/B/C/D values used
5. `test_schema_has_expected_tables()` — registry is complete (imports every model module)

CI runs this gate on every PR.

### 10.4 Logging redaction coverage

`api/app/core/logging.py::_REDACTED_KEY_PATTERNS` (lines 30-61):

```
Credentials/sessions:
  password, passwd, secret, token, authorization, auth_header,
  cookie, session, api_key, apikey, client_secret, private_key,
  access_key
Directory PII:
  email, upn, preferred_username, user_email
PHI / forbidden:
  mrn, member_id, subscriber_id, subscriber_name, guarantor_id,
  guarantor_name, policy_number, patient_, claim_id, encounter_id
```

Recursive redaction into nested dicts and lists; case-insensitive prefix match. Verified in unit test (`test_main_hardening.py`).

### 10.5 Risky exposure surfaces

| Field | Tier | Where exposed | Gate |
|---|---|---|---|
| `email` | B | `alert_subscriptions` API response | None active; redacted in logs |
| `upn` | B | `entered_by_upn`, `uploaded_by_upn` in entries / uploads responses | None active; redacted in logs |
| `effective_comp_usd`, `rvu_rate_usd`, `fmv_benchmark_usd` | D | `/api/v1/scorecards` response | **Backend nullifies fields when `user.comp_viewer=False`** — frontend further hides UI; gate is at the response shape, not endpoint 403 |
| DEA / NPI / license_number | B | `masters.credentials` columns | Owner-clinical / admin only; not exposed in /clinical board today |
| password (hashed) | B | `auth.census_credentials` | Never returned in any API response (verified) |

### 10.6 Sample / test fixture review

- `samples/` and `tests/fixtures/` contain no real PHI. Sample names (Westside Regional, Crystal Anderson, Dr. Franklyn) are synthetic.
- No hardcoded passwords or API tokens anywhere. The census seed script (`infra/census_seed.sh`) takes the password as a CLI arg and hashes via argon2id before storing.

### 10.7 Frontend exposure

`web/lib/api-types.ts` (generated from OpenAPI) — grep finds:
- `email`, `upn` (intentional, behind cookie + redaction)
- compensation fields (intentional, behind comp_viewer)
- **No** claim_id, mrn, patient_*, member_id, subscriber_*, guarantor_*

### 10.8 Audit gap (low risk)

`auth.census_credentials` is **not** in the `AUDITED_TABLES` set. Password rotations via `infra/census_seed.sh` produce no audit row. Per ADR-003 § "Not audited", this is intentional ("its own activity isn't material; what matters is what the portal *did*, captured via daily_entries rows tagged source='manual_portal'"). Acceptable.

### 10.9 Tampering surface (per ADR-003)

Documented and accepted:
- A user with Postgres write access can `set_config('audit.upn', 'someone-else')` → mitigated by no direct DB write in prod (API and crons are only writers)
- A user with DELETE on audit_log can prune rows → mitigated by WORM-locked pg_dump backup (per ADR-004)
- Drop of trigger function → caught by `/ready` endpoint check

This is "audit trail" not "tamper-proof ledger." For tamper-proof you'd need WORM-locked log shipping to a separate subscription. Documented as future ADR if compliance escalates.

---

## 11. Environment and Secrets Audit

(Comprehensive list of every env var + source of truth.)

### 11.1 Backend (`api/app/settings.py`)

| Var | Required? | Default | Secret? | Source of truth | In `.env.example`? |
|---|---|---|---|---|---|
| `ENV` | No | `dev` | No | App Service config | Yes |
| `LOG_LEVEL` | No | `INFO` | No | App Service config | Yes |
| `WEB_ORIGIN` | Prod yes | `""` | No | App Service config | Yes |
| `DATABASE_URL` | Yes | localhost async | No (composed from KV password) | App Service config / KV ref | Yes |
| `DATABASE_URL_SYNC` | Yes | localhost sync | No | same | Yes |
| `AZURE_TENANT_ID` | Prod yes | `""` | No | App Service var | **Empty in bicepparam — must override at deploy** |
| `AZURE_API_CLIENT_ID` | Prod yes | `""` | No | same | same |
| `AZURE_API_SCOPE` | No | `""` | No | App Service | yes |
| `ENTRA_GROUP_ADMIN` ... 7 of these | Prod yes | `""` | No | App Service | **Empty in bicepparam — Akhil populates** |
| `AZURE_STORAGE_ACCOUNT_URL` | Prod yes | Azurite dev | No | Bicep output | Yes |
| `AZURE_STORAGE_CONNECTION_STRING` | Dev only | `""` | **YES** (dev only) | `.env` | Yes |
| `AZURE_DOC_INTELLIGENCE_ENDPOINT` | When uploads are real | `""` | No | App Service | Yes |
| `AZURE_DOC_INTELLIGENCE_API_KEY` | Dev only | `""` | **YES** (prod uses MI) | `.env` | Yes |
| `AZURE_COMMUNICATION_*` | When email is real | `""` | mixed | App Service / KV | Yes |
| `PAYCOM_CLIENT_ID/SECRET` | When Paycom enabled | `""` | **YES** | KV | Yes |

### 11.2 Frontend (`web/.env.example`)

| Var | Required? | Default | Secret? | Source of truth | Documented? |
|---|---|---|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | Yes | `http://localhost:8000` | No | `.env.local` / App Service | Yes |
| `NEXT_PUBLIC_AZURE_TENANT_ID` | Prod yes | `""` | No | App Service | Yes (empty) |
| `NEXT_PUBLIC_AZURE_WEB_CLIENT_ID` | Prod yes | `""` | No | App Service | Yes |
| `NEXT_PUBLIC_AZURE_API_CLIENT_ID` | Prod yes | `""` | No | App Service | Yes |
| `NEXT_PUBLIC_AUTH_MODE` | No | `dev` | No | App Service | Yes |
| `SESSION_SECRET` | **YES (silent crypto failure if missing)** | `""` | **YES (32-byte AES-GCM key)** | KV (should be) | **Audit finding: undocumented in `.env.example` per head-checker; fail-fast missing** |

### 11.3 GitHub Actions secrets / vars

| Name | Where used | Notes |
|---|---|---|
| `AZURE_CLIENT_ID` | deploy-{dev,prod}.yml | Federated identity app reg |
| `AZURE_TENANT_ID` | same | HHA M365 tenant |
| `AZURE_SUBSCRIPTION_ID` | same | hha-production sub |
| `AZURE_TENANT_ID_FOR_KV` | same | For KV resource (same as tenant id, but Bicep needs it as input) |
| `POSTGRES_ADMIN_PASSWORD_DEV` | deploy-dev.yml | Threaded via `-p` to bicep |
| `POSTGRES_ADMIN_PASSWORD_PROD` | deploy-prod.yml | Same. Operator copies from KV manually |

### 11.4 Bicep parameters (env files)

| Param | Dev value | Prod value | Comment |
|---|---|---|---|
| `env_name` | `dev` | `prod` | |
| `location` | `eastus2` | `eastus2` | |
| `postgres_admin_password` | `__OVERRIDE_AT_DEPLOY_TIME__` | same | Must inject from KV at deploy |
| `deployer_workstation_ip` | `0.0.0.0` | `0.0.0.0` | **Must override or HIPAA firewall is wide-open. NO CI ENFORCEMENT.** |
| `azure_tenant_id_for_kv` | `""` | `""` | **Must override** |
| `enable_acr` | `false` | `true` | |
| `enable_rbac` | `false` | `true` | |
| `enable_keyvault` | `false` | `true` | |
| `enable_vnet` | `false` | `true` | |
| `enable_storage` | `true` | `true` | |
| `enable_monitor` | `true` | `true` | |
| `enable_email` | `true` | `true` | (no-op when ACS not yet provisioned) |
| `enable_container_jobs` | `true` | `true` | |
| `azure_tenant_id` | `""` | `""` | **Must override** |
| `azure_api_client_id` | `""` | `""` | **Must override** |
| `entra_groups.admin/exec/...` | all `""` | all `""` | **Must override (7 GUIDs)** |

### 11.5 Findings — required env vars missing or undocumented

| Var | Issue | Severity |
|---|---|---|
| `SESSION_SECRET` | Required for cookie crypto; silent failure if missing; not in `.env.example` | High |
| `azure_tenant_id` (bicepparam) | Empty default in both env files; CI doesn't enforce override | High |
| `azure_api_client_id` (bicepparam) | Same | High |
| `entra_groups.*` (bicepparam) | All 7 empty; admin would be in unmapped state | High |
| `deployer_workstation_ip` | Defaults to `0.0.0.0`; no CI enforcement; HIPAA firewall risk | High |

---

## 12. Tests and Quality Audit

### 12.1 Backend — by domain

(Mapped from the 31 test files in `api/tests/`.)

| Domain | Files | Test count | Coverage |
|---|---|---|---|
| Health / config | `test_health.py`, `test_main_hardening.py` (18), `test_deps_auth_fallthrough.py` (4) | ~28 | STRONG |
| Schema classification (HIPAA) | `test_schema_classification.py` | 5 | STRONG |
| Audit triggers | `test_audit_triggers.py` | ~12 | MODERATE — only `daily_entries` exercised, other 8 audited tables unverified |
| Auth (Entra JWT) | `test_entra_jwt.py` | ~10 | MODERATE — type-shape contamination not covered |
| Census portal | `test_census_portal.py` | ~15 | STRONG |
| Operations | `test_operations_read_prefers_db.py`, `test_site_detail.py` | ~10 | MODERATE |
| Finance | `test_finance_read_prefers_db.py`, `test_monthly_finance_router.py` | ~14 | MODERATE |
| Clinical | `test_clinical_read_prefers_db.py`, `test_weekly_clinical_router.py` | ~14 | MODERATE |
| People | `test_people_read_prefers_db.py` | ~6 | WEAK |
| Scorecards | `test_scorecards_router.py`, `test_comp.py` | ~12 | MODERATE — comp_viewer redaction tested |
| Alerts | `test_alerts_router.py`, `test_alert_engine.py` | ~14 | STRONG |
| Email | `test_email_service.py` | ~8 | STRONG (mocked SDK) |
| Uploads + PDF | `test_uploads_router.py`, `test_job_census_pdf.py` | ~16 | MODERATE — `pdf_extract.py:181` SDK overload not caught |
| Entries (HR / clinical / finance) | `test_entries_router.py`, `test_weekly_hr_router.py` | ~16 | STRONG |
| Jobs | `test_job_alert_digest.py`, `test_job_cred_scan.py`, `test_job_pg_backup.py` (skips when pg_dump missing), `test_paycom_sync_stub.py`, `test_ventra_ingest.py`, `test_ventra_parser.py` | ~30 | MODERATE — pg_backup integration test skips in CI |
| Migrations | (no dedicated file) | 0 | **NONE — round-trip up/down not tested** |

**Total:** ~208 tests collected, 207 pass, 1 skip.

### 12.2 Frontend — by domain

| Domain | Files | Tests | Coverage |
|---|---|---|---|
| `lib/api-fetch` | `__tests__/api-fetch.test.ts` | ~6 | MODERATE |
| middleware | `__tests__/middleware.test.ts` | ~5 | STRONG |
| `lib/auth/session-crypto` | `__tests__/session-crypto.test.ts` | ~5 | STRONG |
| `app/api/auth/session` route | `__tests__/session-route.test.ts` | ~4 | MODERATE |
| Components | none | 0 | **NONE** |
| Pages (any) | none | 0 | **NONE** |
| Hooks (`useUser`, `useApiBrowser`) | none | 0 | **NONE** |
| Forms (5 entry forms) | none | 0 | **NONE** |
| AuthProvider | none | 0 | **NONE** |
| TopNav | none | 0 | **NONE** |
| E2E (Playwright) | none | 0 | **NONE — CLAUDE.md mandates this for sign-in + role-gated routes** |

**Total:** 4 files, 20 tests. Entire UI surface is untested.

### 12.3 Lint + types

| Tool | Status | Detail |
|---|---|---|
| `ruff check .` | PASS | zero violations |
| `mypy app/` | FAIL | 48 errors / 13 files. 2 real bugs (T7, T8); 41 are `dict` annotation drift; 5 are minor |
| `biome check .` | FAIL | 38 violations, all CRLF format |
| `tsc --noEmit` | PASS | zero errors |

### 12.4 Build

| Tool | Status |
|---|---|
| `next build` | PASS (after PR #29 fixes; 21 routes compile) |
| `az bicep build` (×11 modules + main) | PASS |
| `docker compose config -q` | PASS |

### 12.5 Production-blocking missing tests

1. **No Playwright / browser-driven E2E.** CLAUDE.md mandates this for sign-in + role-gated routes + entry forms. Today: zero. (T9)
2. **No test that `seed_sites.py` produces 11 rows.** Bug B-02 invisible to CI.
3. **No alembic round-trip up/down test.** ADR contract says every migration must reverse cleanly; nothing enforces it.
4. **No restore-validity test in CI.** `test_job_pg_backup.py` skips when `pg_dump` is not on PATH (CI doesn't install it). ADR-004 promises restorable backups; CI doesn't prove it.
5. **8 of 9 audited tables have no trigger-fires-correctly test.** `test_audit_triggers.py` only exercises `entries.daily_entries`.
6. **No React component tests.** Build success is the only gate.
7. **No type-shape negative tests** for the JWT claim path (T7) — the `Any` return could silently corrupt roles.

---

## 13. Demo Readiness

### Headline answer: **YES, WITH CAVEATS** for a technical / internal demo. **NO** for an exec demo.

### 13.1 Demo modes

| Mode | Audience | Ready? | Why |
|---|---|---|---|
| 1. Technical demo to Akhil only | Akhil | YES | All boards render; auth path works; entry forms save; audit log updates |
| 2. Internal demo to Crystal / Sandy / Maribel | Department owners | YES, WITH CAVEATS | They will spot fake data ("Westside has 198 today? Always?") within 3 minutes. They can't tell what's real vs synthetic |
| 3. Exec demo to CEO / COO / CFO / CMO | Leadership | NO | Without real data and FL/TX provenance labels, the demo accidentally implies feature-completeness. Risk: "ship this Monday" expectation is misaligned with "we're 4–6 weeks from real Paycom data" |
| 4. Production pilot with real data | Crystal types real census; Sandy types real finance | NO | No deployment to Azure has happened. Locally, only 1 site in DB. Real users would type into a void |

### 13.2 To run a clean technical demo locally TODAY

```bash
# from c:/Users/akhil/OneDrive - hhamedicine.com/HHA Medicine/HHA_Dashboard_New_Joey/hha-dashboard
docker compose up -d
cd api && uv run alembic upgrade head
# (sites table has 1 row; fake_data covers the gap for read paths)
uv run uvicorn app.main:app --port 8000 &
cd ../web && npm run dev &
# open http://localhost:3000
```

**Pages safe to show:**
- `/` overview tiles
- `/operations` and `/operations/1`
- `/finance`, `/clinical`, `/people`, `/scorecards`
- `/daily-census` (type a value, save, see it persist on /operations)
- `/uploads` (drop a non-PDF or stub — actual PDF extraction will crash on first call due to T8)
- `/census/login` → `/census/entry` (alternative auth surface)

**What to say out loud during the demo:**
- "All numbers on the boards are synthetic for now — real ingestion is Phase 2 once Ventra delivers the data shape. The dashboards, schema, and entry forms are real."
- "Doctor scorecards comp data is gated by a `comp_viewer` flag, only CEO/CFO see it. Right now we're showing dev mode so it's all visible."
- "Alerts at the top come from real DB rows when present, fall back to fake when empty."

**What NOT to show / do:**
- Don't upload a real PDF to `/uploads` — extractor crashes (T8).
- Don't run any cron job manually with real ACS / Paycom credentials — the system has none.
- Don't deploy to Azure during the demo (zero-time deploy hasn't been validated).
- Don't open the Postgres directly — exec sees "Test Site" (B-02) and asks about it.

### 13.3 If you need to demo with real-looking data — minimum fixes

1. **T1** — fix `seed_sites.py` upsert + delete "Test Site" → real 11 sites visible. **1.5h.**
2. **T2** — FL · Ventra / TX · manual labels on Finance tiles → ADR-005 invariant visible to execs. **1.5h.**

That's it. ~3 hours of focused work brings the demo from "internal-only" to "exec-credible." The rest of the gap (real ingestion, App Insights) is irrelevant for the demo conversation.

---

## 14. Production Readiness

### Headline answer: **NO.**

### 14.1 Hard blockers (must fix before any prod deploy)

| # | Blocker | Owner |
|---|---|---|
| 1 | No Azure subscription provisioned | Akhil + HHA leadership |
| 2 | No Entra app registrations or security groups | Akhil + Tenant Admin |
| 3 | `azure_tenant_id`, `azure_api_client_id`, all 7 `entra_groups` empty in bicepparam | Akhil |
| 4 | `SESSION_SECRET` not in bootstrap.sh; missing from `web/.env.example` | T4 |
| 5 | `deployer_workstation_ip = '0.0.0.0'` default; no CI guard | T-bicepparam-validate |
| 6 | `seed_sites.py` broken — would deploy a 1-site or empty dashboard | T1 |
| 7 | Job container images never pushed to ACR | T5 |
| 8 | `next build` lint fails on CRLF — CI red, deploy gated | T3 |
| 9 | `pdf_extract.py:181` runtime crash on first real PDF | T8 |
| 10 | `entra_jwt.py:77,87` Any-leak — silent role bypass risk | T7 |

### 14.2 Soft blockers (should fix before users)

| # | Item | Owner |
|---|---|---|
| 1 | App Insights SDK not wired — first incident is undebuggable | T6 |
| 2 | No Playwright E2E — MSAL config drift surfaces only in production | T9 |
| 3 | Fake-data UI banner missing — users could mistake synthetic for real | (small ticket) |
| 4 | RUNBOOK first-deploy procedure never executed | Akhil |
| 5 | Restore drill never run against real backup | Akhil |
| 6 | No alerts wired in App Insights for cron failures | (config in monitor.bicep) |

### 14.3 Acceptable risks

- 5–10 user scale; single tenant; no doctor logins (per ADR-002) — group-claim overage (>150 groups) won't bite at this scale
- Single shared census portal credential — operationally simple, low blast radius (write-only surface)
- mypy 41 `dict` annotation drift (out of 48 total) — non-functional, can clean up over time
- No facts schema populated — Phase 2/3 work, deliberately deferred

### 14.4 Unacceptable risks (must remediate)

- Operating in prod with `ENV=dev` accidentally — caught by `main.py:51-56` startup assertion (mitigated)
- Logging UPN / PHI / credentials — caught by `_redact_pii_processor` (mitigated)
- A user with the wrong group claim getting admin role — partially mitigated by `entra_jwt.py`; T7 closes the residual `Any`-leak path
- Postgres firewall open to `0.0.0.0/0` — mitigated by Bicep param + manual override; needs CI enforcement (deploy-prod.yml grep for non-zero IP)
- Backups not tested for restorability — needs T-restore-drill (run quarterly per ADR-004 § Verification)

### 14.5 BAA / compliance posture

| Vendor | BAA status | Notes |
|---|---|---|
| Microsoft (Azure) | **YES** (default via HHA M365 tenant) | All Azure services in scope: App Service, Postgres Flex, Blob, KV, Container Apps, Monitor, ACS, Entra |
| Microsoft 365 / Entra | **YES** | same |
| Ventra | **PENDING** | Not yet signed; gate for Phase 2 |
| Athenahealth (via Ventra) | **PENDING** | Confirm via Ventra |
| Each hospital | **PENDING** | HHA is BA of each; legal must confirm |
| GitHub | **N/A** | No PHI ever in repo |
| Paycom | **TBD** | Workforce data is not PHI; BAA likely not required, but confirm |

---

## 15. Vendor and Business Dependencies

### 15.1 Ventra (RCM) — F1 standing fact

| Question | Why it matters | Code dependency | Fallback if no answer |
|---|---|---|---|
| Has Ventra signed a BAA? | Phase 2 gate; can't ingest claims without | `jobs/ventra_ingest/` (stub) | Manual Sandy/Maribel entry continues indefinitely |
| What data shape will they deliver? CSV via SFTP? API? 837/835? | Determines parser implementation | `jobs/ventra_ingest/extractors/*` | (none — slot-in is hours when shape lands) |
| What latency? Daily? Monthly aggregates only? | Determines cron schedule + pre-aggregation strategy | same | same |
| Can they confirm row-level PHI is filtered before delivery? | ADR-001 § Phase 2 caveat — pre-aggregate at edge | parser logic | Strict in-memory aggregation in our code regardless |
| Does Ventra include TX in any future delivery? | ADR-005 forbids TX in Ventra path | parser column rejection | Reject TX rows at parse time (already coded) |

**Owner:** Vendor (Ventra) + Akhil for legal coordination.

### 15.2 Paycom (workforce) — F1 standing fact

| Question | Why | Code dep | Fallback |
|---|---|---|---|
| API access enabled? | Phase 1 gate for People board automation | `jobs/paycom_sync/` (stub) | Andrea types weekly HR manually (already wired) |
| Does API include MD x site x shift granularity? | Needed for `fact_scheduled_shifts` | extractor design | Census portal + manual entry |
| Termination effective dates exposed? | Needed for headcount accuracy | same | manual quarterly reconciliation |
| Comp data includes RVU rates? | Needed for Doctor Scorecards | `services/comp.py` | Manual entry on `comp_agreements` |

**Owner:** Vendor (Paycom) + Akhil for credentials.

### 15.3 Hospitals (11 sites)

| Question | Why | Code dep | Fallback |
|---|---|---|---|
| Census source — manual? Hospital portal? Direct PM? | Determines daily-census ingestion | `routers/census_portal.py` + manual Crystal entry | Manual portal already works |
| Quality metrics export available? | Phase 4 — not currently in scope | (none) | n/a — out of scope |
| Credentialing status visible to HHA? | Phase 4 | `masters.credentials` (manual today) | Manual entry on credential expiry |
| Site point of contact for daily disruptions? | Operational, not code | (none) | Site liaison directory in `masters.sites.contact_*` |

**Owner:** HHA Operations + each hospital.

### 15.4 Internal HHA — execution dependencies

| Person | Role | Code dependency | What they need to provide |
|---|---|---|---|
| Crystal | Owner_ops; types daily census | `/daily-census`, `/census/login` | Daily 7am workflow, password sharing protocol |
| Sandy | Owner_finance; types monthly finance | `/monthly-finance` | Monthly close cadence, source_system tagging |
| Maribel | Owner_finance backup | same | same |
| Andrea | Owner_hr; types weekly HR | `/weekly-hr` | Weekly cadence; Paycom data when API lands |
| Dr. Aneja | Owner_clinical; types weekly clinical | `/weekly-clinical` | Weekly H&P / DC / LOS rollup |
| Dr. V. Reddy | Owner_clinical backup | same | same |
| CEO | Exec + comp_viewer | reads all boards + scorecards comp | Sign off on phase gates; ratify ADRs |
| CFO | Exec + comp_viewer | same | same; financial truth-check |
| COO | Exec | reads all boards (no comp) | Operational truth-check |
| CMO | Exec | reads all boards (no comp) | Clinical truth-check |
| Akhil | Admin + tech lead | full access; deploys | Azure subscription provisioning, Entra group setup, first deploy, vendor follow-up |
| HHA Privacy Officer | Compliance | n/a | Sign off on HIPAA posture; review ADR-001, ADR-003, ADR-004 |
| HHA Security Officer | Compliance | n/a | Sign off on auth model (ADR-002); review the deploy-prod safeguards |

---

## 16. Risks

### 16.1 Technical

- **CRLF + biome blocks every CI run** until normalized (T3). Severity: high (blocks deploy).
- **mypy `Any` leak in entra_jwt** (T7). Severity: medium-high — silent role bypass possible.
- **pdf_extract Azure SDK overload mismatch** (T8). Severity: medium — first real upload crashes.
- **Frontend build is one regression away from breaking again** — no E2E gate. Severity: medium.
- **Audit tests cover only 1 of 9 audited tables.** Severity: medium — tampering/coverage gap.
- **No alembic round-trip test.** Severity: low-medium — migration regression risk.

### 16.2 Security

- **Path 3 default-admin in dev** — if `ENV=dev` accidentally lands in prod, anyone gets admin. Mitigated by startup assertion at `main.py:51-56`. Severity: low (defense-in-depth holds).
- **Census portal single shared credential** — leak = blast radius "type numbers, nothing else" (per ADR-002 threat model). Severity: low.
- **`SESSION_SECRET` undocumented + not seeded by bootstrap** — silent crypto failure on first sign-in. Severity: high before deploy; trivial fix.
- **Postgres firewall `0.0.0.0` default in bicepparam** — no CI enforcement. Severity: high before deploy.

### 16.3 HIPAA

- **No real PHI in scope today** — pre-aggregate-at-edge invariant (ADR-001) preserved.
- **Audit gap on census_credentials table** — accepted per ADR-003. Severity: low.
- **Logging redaction comprehensive but never exercised in prod** — App Insights traces will reveal whether a key slipped through. Severity: low (mitigated by chain ordering).

### 16.4 Product

- **Fake data is invisible to users** — exec demo could mislead (T2 + UI banner). Severity: medium.
- **No data-source provenance on Finance tiles** (ADR-005 invariant). Severity: medium.
- **Form pages silently swallow errors** — user types, "save" succeeds visually, data lost. Severity: medium.

### 16.5 Vendor

- **Ventra delivery shape unknown** (F1) — can't ship Phase 2 ingestion. Severity: external blocker.
- **Paycom API access pending** (F1) — can't automate People board. Severity: external blocker.
- **No timeline for either**. Severity: high for product roadmap.

### 16.6 Operational

- **First deploy never executed** — RUNBOOK procedures untested. Severity: high before users land.
- **Restore drill never run against real backup**. Severity: high before users land.
- **No alerts wired for cron failures** — silent backup failure possible. Severity: high once crons are running in prod.
- **Solo bus factor** — Akhil is the only engineer + the only deploy operator. Severity: high; mitigation = ARCHITECTURE.md + ONBOARDING.md (T10) + RUNBOOK.

---

## 17. Next 20 Tickets

(Ordered for execution — each PR builds on the prior. T1–T9 already exist in [NEXT_BUILD_PLAN.md](NEXT_BUILD_PLAN.md) at higher detail; this set extends with stabilization and pre-deploy guardrails.)

### 17.1 Tickets T1–T20

| ID | Title | Category | Why | Evidence | Files | Acceptance | Test cmd | Size | Risk | Owner | Deps | DoD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **T1** | Backfill 11 sites + harden seed_sites.py | Stabilization | DB has 1 stray row; dashboard reads from fake_data; demo-blocker | `psql -c "SELECT count..."` → 1; `seed_sites.py:125-129` | `scripts/seed_sites.py`, `api/tests/test_seed_sites.py` | Clean schema → 11 sites; idempotent re-run | `pytest tests/test_seed_sites.py` | S | Low | Claude Code | none | merged + DB has 11 |
| **T2** | FL · Ventra / TX · manual UI labels | Demo readiness | ADR-005 invariant; exec demo credibility | grep `web/app/finance` for "Ventra" → 0 hits | `web/app/finance/page.tsx`, `web/components/finance/*` | Every Finance tile shows source label | `npm run test` | S | Low | Claude Code | none | merged + manual screenshot |
| **T3** | CRLF + .gitattributes + pre-commit hook | Stabilization | biome 38 fail; CI red; blocks deploy | `npm run lint` 38 errors | `.gitattributes`, `.husky/pre-commit`, all `web/**` whitespace normalize | `npm run lint` exit 0; pre-commit rewrites CRLF | `npm run lint` | S | Low-medium | Claude Code | none | merged + CI green |
| **T4** | SESSION_SECRET in web/.env.example + fail-fast | Security | Silent crypto failure on first sign-in in prod | `head-checker.log` evidence; verify no `SESSION_SECRET=` in `web/.env.example` | `web/.env.example`, `web/lib/auth/session-crypto.ts`, `docs/RUNBOOK.md` | Missing → clear startup error; documented | `unset SESSION_SECRET; npm run dev` fails clearly | XS | Low | Claude Code | none | merged + RUNBOOK updated |
| **T5** | Build + push job images to ACR (CI workflow) | Infra | Container Apps Jobs need images; ACR is empty | `az acr repository list -n acrhhaprod` (would be empty) | `.github/workflows/build-job-images.yml`, `infra/env/*.bicepparam` (image_tag), `infra/modules/containerjobs.bicep` | 3 images in ACR with SHA tag; redeploy succeeds | `gh workflow run build-job-images.yml` | M | Medium | Claude Code | T3 (CI green) | first prod deploy works |
| **T6** | App Insights SDK + correlation-id middleware | Infra | First incident undebuggable | grep `api/app/` for `azure-monitor-opentelemetry` → 0 | `api/app/core/telemetry.py`, `api/app/main.py`, `api/app/core/logging.py`, `infra/main.bicep` | Trace appears in AI portal within 5 min; `request_id` in every log | `pytest tests/test_telemetry.py` + manual | M | Medium-high | Claude Code | T5 (deploy unblocked) | first request → AI trace |
| **T7** | entra_jwt Any-leak fix (silent role bypass) | Security/HIPAA | mypy line 77, 87 returns `Any`; type-shape contamination possible | `mypy app/services/entra_jwt.py` | `api/app/services/entra_jwt.py`, `api/tests/test_entra_jwt.py`, `api/app/deps.py` | mypy 0 errors; negative tests added | `mypy + pytest tests/test_entra_jwt.py` | S-M | Medium | Claude Code | none | merged + mypy clean for that file |
| **T8** | pdf_extract Azure SDK overload fix | Stabilization | Crystal's first real PDF crashes | `pdf_extract.py:181` mypy overload-mismatch | `api/app/services/pdf_extract.py`, `api/pyproject.toml` (pin SDK), `api/tests/test_pdf_extract.py` | mypy 0; new fixture covers the corrected signature | `mypy + pytest tests/test_pdf_extract.py` | S-M | Medium | Claude Code | none | merged |
| **T9** | Playwright E2E (sign-in + 1 role-gated route) | Stabilization | Zero browser tests; PR #29 build-blocker would have been caught | `find web/ -name "*.spec.ts"` → 0 | `web/playwright.config.ts`, `web/e2e/*.spec.ts`, `.github/workflows/ci.yml` | 2 specs pass under 60s in CI | `npm run e2e:run` | M | Medium | Claude Code | T3 | merged + CI gates on it |
| **T10** | Bicepparam validation in deploy workflows | Security/Infra | `deployer_workstation_ip='0.0.0.0'` default; no CI guard | `infra/env/dev.bicepparam:25` literal | `.github/workflows/deploy-{dev,prod}.yml` | Pre-flight grep refuses `0.0.0.0` and any empty Entra ID | manual `gh workflow run` with bad input → fails | XS | Low | Claude Code | none | merged |
| **T11** | Frontend "synthetic data" banner | Demo readiness | Users could mistake fake_data for real | grep `web/app` for "synthetic" → 0 | `web/components/SyntheticDataBanner.tsx`, `web/app/layout.tsx` | Banner visible when `/api/v1/meta` reports no live ingestion | `npm run test` | XS | Low | Claude Code | none | merged + visible in dev |
| **T12** | Form error toasts (no silent swallow) | Stabilization | `.catch(() => [])` eats errors silently | `web/app/daily-census/page.tsx:14` | each form page (5 files) | Error → user-visible toast with retry hint | manual + vitest | S | Low | Claude Code | none | merged |
| **T13** | Audit triggers — test all 9 tables | Security/HIPAA | only `daily_entries` exercised | `test_audit_triggers.py` | `api/tests/test_audit_triggers.py` | Each of 9 tables → INSERT/UPDATE/DELETE → audit row | `pytest tests/test_audit_triggers.py` | S | Low | Claude Code | none | merged |
| **T14** | Alembic round-trip up/down test | Stabilization | No test that downgrades work | `find api/tests -name "*alembic*"` → 0 | `api/tests/test_migrations.py` | For each migration: upgrade → downgrade → upgrade clean | `pytest tests/test_migrations.py` | S | Low | Claude Code | none | merged |
| **T15** | Restore drill — actually run + capture output | Operations/Infra | `restore_drill.sh` exists; never executed | `git log scripts/restore_drill.sh` | (no code change; capture output to `docs/restore_drill_2026-04-XX.log`) | One successful restore against a real dump; doc updated | `bash scripts/restore_drill.sh` | XS | Low | Akhil | T5 (image in ACR) | log captured |
| **T16** | App Insights alert rules for cron failures | Operations | Silent backup failure possible | `infra/modules/monitor.bicep` (no alert rules today) | `infra/modules/monitor.bicep` | 3 alert rules: pg_backup-failed, alert_digest-failed, cred_scan-failed; PagerDuty/email recipient | `az monitor metrics alert list` | S | Low | Claude Code | T5 + T6 | rules visible in portal |
| **T17** | First Azure deploy — dev environment | Infra | Bicep all builds; never deployed | `gh run list -w deploy-dev.yml` → 0 | (no code change; capture deploy outputs) | `app-hha-web-dev.azurewebsites.net` returns 200 | `gh workflow run deploy-dev.yml` | M | Medium | Akhil | T1, T3, T4, T5, T10 | deploy URL |
| **T18** | First Azure deploy — prod environment (gated) | Infra | Same | same | (no code change) | `app-hha-web-prod.azurewebsites.net` returns 200 with real Entra | manual approval | M | High | Akhil + co-sponsors | T17 + Entra setup + KV seeded | deploy URL |
| **T19** | ARCHITECTURE.md + ONBOARDING.md | Docs | Bus factor; next engineer onboard | `find docs -name "ARCH*"` → 0 | `docs/ARCHITECTURE.md`, `docs/ONBOARDING.md`, `CLAUDE.md` | < 600 + < 200 lines respectively, linked from CLAUDE.md | manual review | S | Low | Claude Code | none | merged |
| **T20** | mypy bulk dict cleanup (41 errors) | Stabilization | Annotation drift; CI noise | `mypy app/` → 48 - 7 (T7+T8) = 41 | 9 router/model files | mypy 0 errors | `mypy app/` | S | Low | Claude Code | T7, T8 | merged |

### 17.2 Phase boundaries

- **Phase 1 (demo): T1, T2, T11, T12** — ~4–5 hours.
- **Phase 2 (deploy): T3, T4, T5, T6, T10** — ~7–9 hours.
- **Phase 3 (real users): T7, T8, T9, T13, T14, T15, T16** — ~10–12 hours.
- **Phase 4 (deploy live): T17, T18** — depends on business gates (Akhil, vendor, leadership).
- **Phase 5 (cleanup): T19, T20** — ~3 hours.

Ordering rule: never run T17 before T1, T3, T4, T5, T10. Never run T18 before T17 has been live and stable for > 24 hours.

---

## 18. Principal Engineer Recommendation

**This week, in order:**

1. **Stop building features. Stabilize.** The runtime is buildable, tested, and HIPAA-honest. The biggest risk is shipping more code on top of a not-yet-deployed foundation.
2. **Land T1, T2, T11, T12 by Tuesday.** That's the demo-credible bundle (~4 hours). After this, you can show the dashboard to Crystal and Sandy without explaining "this is fake" three times.
3. **Land T3, T4, T10 by Wednesday.** This is the "make CI green and deploy-safe" bundle (~3 hours). After this, deploy-dev.yml can actually run without misconfiguration.
4. **Land T5 + T6 by Thursday.** Container images in ACR + App Insights wired (~5 hours). Now the cron jobs can actually run in Azure and you can see when they fail.
5. **Run T17 (first Azure deploy to dev) by Friday.** This is the moment of truth — RUNBOOK has never been executed. Expect ~2–3 hours of "the bicepparam is wrong" / "the Entra group OIDs are wrong" / "the App Service can't reach Postgres" issues. Document each one as you go.
6. **T7 + T8 + T13 + T14 next week.** These are the "before-real-users" stabilizers. Auth type-safety, PDF crash fix, audit trigger coverage, migration round-trip.
7. **Schedule a working session with Sandy and Crystal next week.** Have them type real values into the entry forms (against dev). Capture every UX confusion. Close the silent-error-swallow bug (T12) before they touch prod.
8. **Vendor track in parallel.** Send the Ventra reply (`VENTRA_REPLY_DRAFT.md`). Follow up on Paycom API access. These are 4–6 week external blockers; start the clock.
9. **Don't deploy to prod until:** (a) dev has been stable for a week, (b) restore drill has been run successfully (T15), (c) co-sponsors (CEO + CFO) have signed off, (d) HHA Privacy Officer has reviewed ADR-001/002/003.
10. **One PR per ticket.** Squash-merge. Atomic. The history of the last 8 PRs (#21–#28) is the right cadence — match it.

**What NOT to do:**
- Don't add new boards or new entry forms.
- Don't switch any vendor (Azure-only is locked).
- Don't bypass the seed problem by editing fake_data.py to look more real — that's a regression in honesty.
- Don't start Ventra ingestion code on speculation. Wait for the data shape (F1).
- Don't skip the restore drill. Backups you haven't restored from aren't backups.

---

## Audit Artifacts

### Commands run
- `git status --short`, `git branch --show-current`, `git log --oneline -10`, `git remote -v`, `git rev-list --left-right --count origin/main...HEAD`
- `find . -maxdepth 2 -type d`, `find . -maxdepth 3 -type f` (filtered)
- `python --version`, `node --version`, `npm --version`, `uv --version`, `az --version`
- `cd hha-dashboard/web && npm run typecheck`, `npm run build`, `npm run test`
- All commands captured in `c:/tmp/hha-verify/{backend,frontend,infra,head-checker}.log` from PR #29
- 5 parallel agent runs covered: backend deep-dive, frontend deep-dive, data+HIPAA, infra+jobs+env, tests+commands

### Files inspected (not exhaustive)
- All 11 routers (`api/app/routers/*.py`)
- All 12 services (`api/app/services/*.py`)
- All 11 models (`api/app/models/*.py`)
- All 10 alembic migrations (`api/alembic/versions/*.py`)
- All 10 Bicep modules (`infra/modules/*.bicep`) + `main.bicep` + 2 `bicepparam`
- All 3 GH workflows
- All 6 jobs (`jobs/*/`)
- All 17 page.tsx files
- 10 components, 8 lib files, 4 vitest test files
- 31 backend test files
- 5 ADRs + RUNBOOK + CLAUDE.md + DASHBOARD_PLAN.md

### Assumptions made (called out where relevant)
- Verification log results from PR #29 are taken as authoritative for build/test state. Frontend build was failing before PR #29; it is now green. The mypy and biome counts are unchanged.
- The pytest count (207/1-skip) was re-verified in this audit by re-running test discovery — confirmed.
- Bicep / GH workflow / docker-compose syntactic correctness is verified; runtime correctness (does the deploy actually work end-to-end on Azure) is **not** verified — no deploy has been executed.

### Unknowns remaining
- Will Ventra data shape match our parser scaffold? (F1 — vendor blocker)
- Will Paycom API expose MD x site x shift granularity? (F1 — vendor blocker)
- Has HHA Privacy Officer reviewed ADR-001 / 003 / 004? (Akhil + leadership)
- Are the Entra security groups created in the HHA tenant? (Tenant Admin)
- Is `hha-production` Azure subscription provisioned and BAA-confirmed? (Akhil)
- Will the first `az deployment group create -e dev` succeed without manual fixes? (T17 — only validated by running it)
- Does pg_backup actually produce a restorable dump in production? (T15 — validated by running restore drill)

---

**End of audit.** This document is read-only output. No code changes were made other than the verification PR (#29) already merged. The 20-ticket plan in Section 17 is the recommended path forward.
