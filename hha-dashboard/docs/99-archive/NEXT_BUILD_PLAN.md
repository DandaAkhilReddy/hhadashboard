# Next Build Plan — HHA Dashboard

- **Date:** 2026-04-26
- **Source inputs:** [LOCAL_VERIFICATION_REPORT.md](LOCAL_VERIFICATION_REPORT.md), [CLAUDE.md](../../CLAUDE.md), the 5 ADRs in [adr/](../adr), [RUNBOOK.md](../04-operations/RUNBOOK.md)
- **Status:** ranked backlog, 10 tickets, no code written yet
- **Author:** Claude Code session, supervised by Akhil Reddy

The verification pass on `chore/local-verification` (PR #29) confirmed the runtime is now buildable end-to-end and surfaced a ranked list of follow-ups. This document expands that list into 10 actionable tickets across four phase gates.

A demo-quality dashboard is closer than the engineering work suggests, but three categories of issues stand between us and a real Crystal-types-the-census moment: (a) the seed leaves the dashboard reading from `fake_data.py` instead of the database, (b) the deployment story is incomplete (no images in ACR, no telemetry, no verified secret), and (c) two genuine type-safety bugs sit in auth and PDF ingestion that will bite the first time a real user touches them.

The total work below is roughly **18–24 engineering hours** spread across the four phases. Phase 1 (demo) is ~3h. Phase 2 (Azure deploy) is ~7h. Phase 3 (real users) is ~6h. Phase 4 is ~2h.

Tickets are numbered T1–T10 in execution order. Within a phase, the order is mechanical: complete in sequence so each merge is atomic.

---

## Phase 1 — Must fix before demo

A demo to CEO/CFO/CMO/COO requires the dashboard to render real data, not synthetic, and to label every Finance tile by source so the FL vs TX provenance is legible at a glance. Without these two, the demo lands as "looks like a mockup" and creates a credibility tax.

### T1 — Backfill the canonical 11 sites + harden `seed_sites.py` to upsert-by-name

**Why it matters.** `/api/v1/sites` returns 1 row today (a stray "Test Site"). The dashboard appears to render 11 sites only because `app/services/fake_data.py` returns synthetic data when the DB is sparse. The instant we point Sandy or Crystal's owner forms at the real DB on a clean Azure deploy, the count goes from "11 fake" to "1 real" and the Operations / Finance boards both look broken. The seed script silently bails on any existing row, so the cycle is self-perpetuating.

**Files likely touched.**
- `hha-dashboard/scripts/seed_sites.py` (`125-129` — change bail-on-row to upsert)
- `hha-dashboard/api/tests/test_seed_sites.py` (**create**) — assert `count(*) = 11` after seeding against a clean schema
- `hha-dashboard/docs/RUNBOOK.md` (`§ Routine Operations`) — note the new idempotency contract

**Acceptance criteria.**
1. Running `uv run python scripts/seed_sites.py` against an empty database yields exactly 11 rows in `masters.sites` (7 FL + 4 TX) with named medical directors.
2. Running it a second time is a no-op (no duplicate rows, no error, no log spam).
3. Running it against a database that contains a stray "Test Site" row leaves the stray row alone (operator deletes it manually with a one-line SQL) but inserts the 11 canonical rows alongside it. Subsequent run with stray row deleted converges to 11.
4. The new pytest passes against a fresh schema.

**Test command.**
```bash
cd hha-dashboard/api && uv run pytest tests/test_seed_sites.py -v
# end-to-end manual:
docker compose down -v && docker compose up -d
uv run alembic upgrade head
uv run python ../scripts/seed_sites.py
psql -h localhost -U hha -d hha_dashboard -c "SELECT count(*) FROM masters.sites;"
# → 11
```

**Risk level.** Low. Single-script change with a deterministic test gate. The migration / schema is untouched; this only changes how rows land.

---

### T2 — Add FL · Ventra / TX · manual provenance labels on every Finance tile

**Why it matters.** ADR-005 ("FL/TX Scope Split") locks the invariant that **every aggregate finance row carries `source_system`** and that the UI labels every tile with its provenance — *"source label is part of the data, not a tooltip."* The backend already enforces the column-level invariant via `monthly_finance_manual.source_system` (migration `0006_ventra_athena_source.py`) and the frontend already displays Finance KPIs, but the source label is currently absent from the rendered tiles. A demo that shows "Collections $44.2M MTD" without the FL · Ventra qualifier accidentally implies that all numbers come from the same uniform pipeline. Sandy will correct that in front of the CEO. We don't want that.

**Files likely touched.**
- `hha-dashboard/web/app/finance/page.tsx` — board layout, split tiles by state
- `hha-dashboard/web/components/finance/FinanceKpiTile.tsx` (**create or modify**) — add `source` prop
- `hha-dashboard/web/lib/api-client.ts` + `api-types.ts` — confirm `source_system` is exposed in the response shape
- `hha-dashboard/api/app/routers/finance.py` — confirm the response includes `source_system` per row (may be a one-line addition to the response model)
- `hha-dashboard/api/app/schemas/finance.py` — Pydantic schema may need `source_system` field

**Acceptance criteria.**
1. Every tile on `/finance` shows `(FL · Ventra)`, `(FL · Ventra fallback)`, or `(TX · manual)` directly under the metric label, not in a tooltip.
2. The combined "HHA-wide Collections" tile (if rendered) shows a footnote: `FL: Ventra · TX: manual` per ADR-005 § Consequences.
3. The board never renders a tile that lacks a provenance label.
4. A vitest snapshot or component test asserts the label shape for at least one tile per source value.

**Test command.**
```bash
cd hha-dashboard/web && npm run test
# manual:
npm run dev
# open http://localhost:3000/finance, confirm every tile is labelled
```

**Risk level.** Low. Pure UI change driven by an existing schema field. No business-logic risk; the test is a snapshot of the rendered label. Worst case the label position is off and we tweak Tailwind classes.

---

## Phase 2 — Must fix before Azure deploy

Phase 2 is everything that has to be true the first time the runtime touches real Azure. CI must stay green for the deploy workflow to pass, secrets must fail loudly when missing, container-jobs Bicep can't actually run jobs without images, and the first incident on prod is undebuggable without telemetry.

### T3 — Normalize CRLF → LF + `.gitattributes` + pre-commit hook

**Why it matters.** Biome lint fails on 38 source files today because Windows line endings keep landing in commits. Every CI lint run on every Windows commit re-introduces the failure. The `deploy-dev.yml` and `deploy-prod.yml` workflows both gate on CI green. Until this is fixed at the gitattributes level (not just one-off `npm run format`), the pipeline is stuck.

**Files likely touched.**
- `hha-dashboard/.gitattributes` (**create**) — `* text=auto eol=lf` + explicit per-extension rules
- `hha-dashboard/web/**` — one-shot `npm run format` to normalize 38 files (CRLF → LF, no semantic change)
- `hha-dashboard/.husky/pre-commit` (**create**) + `package.json` devDependencies (`husky`, `lint-staged`) — hook that runs `biome check --apply` on staged files
- `hha-dashboard/web/package.json` — add `husky install` to `prepare` script

**Acceptance criteria.**
1. `git diff --check` finds no CRLF on any tracked file.
2. `npm run lint` exits 0 from a fresh checkout on Windows + macOS + Linux.
3. Attempting to commit a file with CRLF triggers the pre-commit hook and rewrites it to LF before the commit lands.
4. `.gitattributes` is committed at the repo root and explicitly covers `*.{ts,tsx,js,jsx,json,md,yml,yaml,sh}`.

**Test command.**
```bash
# from a fresh clone:
git clone <repo> /tmp/hha-clone && cd /tmp/hha-clone
cd hha-dashboard/web && npm ci && npm run lint
# → exit 0
```

**Risk level.** Low-medium. The diff is large (~38 files) but whitespace-only. Risk: any tooling that depends on CRLF (none in this stack, but worth grep'ing for `\r` in test fixtures) silently breaks. Keep the change in a dedicated branch (`chore/normalize-line-endings`) so the diff stays scannable.

---

### T4 — Document `SESSION_SECRET` in `web/.env.example` + fail-fast at startup

**Why it matters.** `web/lib/auth/server-session.ts` (and `session-crypto.ts`) reads `SESSION_SECRET` to AES-GCM-encrypt the access-token cookie. If the variable is missing, the encryption call returns garbage / throws at first MSAL sign-in — silently in some paths, loudly in others. A new developer copying `.env.example` today gets that silent failure, not a clear startup error. In prod, the App Service config blade has to set this before the first user signs in, or the entire auth surface goes dark with no clue why.

**Files likely touched.**
- `hha-dashboard/web/.env.example` — add `SESSION_SECRET=` with a generation comment (`openssl rand -base64 32`)
- `hha-dashboard/web/lib/auth/session-crypto.ts` — read the secret once at module load and throw a clear `Error("SESSION_SECRET is required for cookie encryption — set it in .env.local or App Service config")` if missing
- `hha-dashboard/web/middleware.ts` — early return + structured log if the secret is unset (defense in depth)
- `hha-dashboard/docs/RUNBOOK.md` — update `§ First Deploy → Phase 3 (App Service config)` with the secret-set step
- `hha-dashboard/infra/main.bicep` — confirm the App Service `app_settings` either includes a placeholder or the bootstrap script seeds it from KV

**Acceptance criteria.**
1. `web/.env.example` contains `SESSION_SECRET=` with a comment explaining how to generate.
2. `cd web && npm run dev` with `SESSION_SECRET` unset fails immediately at boot with a one-line message naming the missing variable; it does NOT serve any pages.
3. `cd web && npm run build` either compiles cleanly (the variable is build-time-optional) OR fails with the same clear message — but never silently produces a deploy artifact that crashes at runtime.
4. The RUNBOOK procedure for first-deploy lists the secret-set step before the smoke-test step.

**Test command.**
```bash
cd hha-dashboard/web
unset SESSION_SECRET && npm run dev 2>&1 | head -5
# → exits with a single clear error mentioning SESSION_SECRET
SESSION_SECRET=$(openssl rand -base64 32) npm run dev &
sleep 5 && curl -sI http://localhost:3000/ | head -1
# → HTTP/1.1 200 OK
```

**Risk level.** Low. Touches only the auth-bootstrap path and one example file.

---

### T5 — Build + push job container images to ACR (CI workflow)

**Why it matters.** PR #28 wired ACR + RBAC into Bicep. The Container Apps Jobs declared in `infra/modules/containerjobs.bicep` (alert_digest, cred_scan, pg_backup, future paycom_sync, ventra_ingest) all reference image names like `acrhhaprod.azurecr.io/jobs/alert_digest:latest`. **No images currently exist in ACR.** The first prod deploy of the jobs will fail because the image pull will 404. We need a CI job that builds each Dockerfile, pushes to the correct ACR with a SHA tag, and the Bicep params point at that tag.

**Files likely touched.**
- `hha-dashboard/.github/workflows/build-job-images.yml` (**create**) — manual + on-tag trigger, OIDC login to ACR, `docker buildx` per job folder
- `hha-dashboard/jobs/{pg_backup,alert_digest,cred_scan}/Dockerfile` — confirm each is buildable in CI (some may need a multi-arch base or apt cache fix)
- `hha-dashboard/infra/env/{dev,prod}.bicepparam` — add `image_tag` parameter (default to a SHA placeholder)
- `hha-dashboard/infra/modules/containerjobs.bicep` — accept image tag, compose the full image name from `acr_login_server` + tag
- `hha-dashboard/docs/RUNBOOK.md` — document the "deploy a new job version" sequence (build → push → bump tag → redeploy)

**Acceptance criteria.**
1. A manual workflow run completes successfully, logs into ACR via OIDC (no PAT), and pushes 3 images (`pg_backup`, `alert_digest`, `cred_scan`) tagged with the commit SHA.
2. `az acr repository list -n acrhhaprod` shows the three repos and `az acr repository show-tags -n acrhhaprod --repository pg_backup` shows the SHA tag.
3. A redeploy of `prod.bicepparam` with the new `image_tag` value succeeds and the Container Apps Job manifest references the SHA-tagged image.
4. The workflow's CI run is green on a PR that touches a Dockerfile.

**Test command.**
```bash
# manually trigger the workflow once via gh:
gh workflow run build-job-images.yml -f environment=prod
gh run watch
# verify:
az acr repository list -n acrhhaprod
```

**Risk level.** Medium. New CI job, new OIDC role for ACR push (already wired in `rbac.bicep` per PR #28), new Bicep parameter threading. Mitigation: ship to dev ACR first (gated on `enable_acr=true` in `dev.bicepparam`, currently false — flip it for this ticket), confirm all the way through, then bump prod.

---

### T6 — App Insights SDK wiring in api + structured request logging

**Why it matters.** `infra/modules/monitor.bicep` already provisions Application Insights and Log Analytics. Diagnostic Settings on App Services, Postgres, KV, Storage are wired (PR #18). But the FastAPI process itself isn't sending custom telemetry — no request traces, no service-level metrics, no correlation ID across the api → postgres → blob chain. The first prod incident with "users see a 500" produces zero useful data because we only have App Service stdout. RUNBOOK § 4.3 (Alert digest cron silently stopped) explicitly assumes App Insights traces exist; today they don't.

**Files likely touched.**
- `hha-dashboard/api/pyproject.toml` — add `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-sqlalchemy`, `azure-monitor-opentelemetry-exporter` (or the all-in-one `azure-monitor-opentelemetry`)
- `hha-dashboard/api/app/core/telemetry.py` (**create**) — initializes OTel + AI exporter when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set; no-op otherwise
- `hha-dashboard/api/app/main.py` — call `setup_telemetry(app)` from lifespan; correlation-id middleware adds `request_id` to every structlog record
- `hha-dashboard/api/app/core/logging.py` — extend the existing `_redact_pii_processor` chain with a processor that pulls `request_id` from contextvars
- `hha-dashboard/infra/main.bicep` — thread `applicationinsights_connection_string` into both `web` and `api` App Service `app_settings`
- `hha-dashboard/api/tests/test_telemetry.py` (**create**) — assert that with no env var the setup is a no-op; with a fake connection string the exporter is registered

**Acceptance criteria.**
1. With `APPLICATIONINSIGHTS_CONNECTION_STRING` unset, the api boots cleanly and behaves identically to today (no crashes, no warnings beyond a single info-level "telemetry disabled").
2. With the env var set against a dev AI resource, every HTTP request produces an OTel trace visible in the AI portal under "Performance" within 5 minutes, with the request path, status code, and duration.
3. Every structlog record on a request path includes `request_id` matching the trace.
4. PII redaction (existing) still applies — UPN, email, MRN-shaped values never appear in AI traces.
5. Pytest covers both branches (configured / not configured).

**Test command.**
```bash
cd hha-dashboard/api && uv run pytest tests/test_telemetry.py -v
# manual end-to-end:
APPLICATIONINSIGHTS_CONNECTION_STRING="<dev-ai-conn-string>" uv run uvicorn app.main:app
curl -H "Authorization: Dev admin" http://localhost:8000/api/v1/sites
# → wait 5 min, check AI portal "Performance" → see the trace
```

**Risk level.** Medium-high. Touches every request path (correlation-id middleware) and the logging chain. Low likelihood of breaking pytest because the new code is gated on env-var presence. Higher likelihood of subtle issues with OTel + asyncio + SQLAlchemy interactions on Windows; budget time for that.

---

## Phase 3 — Must fix before real HHA users

These three are pre-conditions for Crystal, Sandy, Aneja, Reddy, or Andrea actually using the system. Each is a real bug, not a polish item.

### T7 — Fix `entra_jwt` Any-leak (silent role-bypass risk)

**Why it matters.** `app/services/entra_jwt.py:77,87` returns `Any` from claim extraction. The `groups` claim flows through to `app/deps.py::get_current_user` and gets mapped to roles. If the claim shape drifts (Entra ID indirection in `_claim_names` for users in >150 groups, optional vs required claim, type-coercion silently producing the wrong list), a user could end up with the wrong role set and no test would catch it. The existing tests pass because they pass typed dicts; a real Entra response that drifts in production wouldn't. CLAUDE.md § Forbidden Operations explicitly lists "Bypassing `require_role` or `require_comp_viewer` decorators" as a bug class — silent type coercion is the same risk.

**Files likely touched.**
- `hha-dashboard/api/app/services/entra_jwt.py` (`_extract_groups`, `_extract_upn`, `_extract_name` — the three Any-return functions)
- `hha-dashboard/api/app/services/entra_jwt.py` — add Pydantic v2 model for the verified claims (typed)
- `hha-dashboard/api/tests/test_entra_jwt.py` — extend with negative cases (claim missing, claim wrong type, claim is `_claim_names` overage)
- `hha-dashboard/api/app/deps.py` — receive the typed claims object instead of a dict

**Acceptance criteria.**
1. `uv run mypy app/services/entra_jwt.py` exits 0.
2. New negative tests in `test_entra_jwt.py` cover: missing groups claim, groups claim as scalar instead of list, `_claim_names` indirection, `upn` claim missing.
3. A request whose JWT claim shape is malformed returns 401 with a clear error code, not a 500 or a silent role downgrade.
4. The full pytest suite stays at 207+ passing.

**Test command.**
```bash
cd hha-dashboard/api && uv run mypy app/services/entra_jwt.py
cd hha-dashboard/api && uv run pytest tests/test_entra_jwt.py -v
```

**Risk level.** Medium. Touches the auth happy path; a bug here breaks every dashboard request. Mitigation: keep the change additive (new typed model alongside old `dict` access during the migration), then flip `deps.py` and remove the `dict` access in a second commit.

---

### T8 — Fix `pdf_extract` Azure SDK overload mismatch (PDF upload crash)

**Why it matters.** `app/services/pdf_extract.py:181` has a mypy-flagged overload mismatch on `begin_analyze_document` — the `azure-ai-documentintelligence` SDK changed its signature in a recent release. Crystal's first real PDF upload will crash with a confusing TypeError. This is a real bug the current test suite doesn't catch because the tests stub the SDK call. Plus there's a `None`-deref at line 102 (`union-attr`) on an optional table list that crashes if a page genuinely has no tables.

**Files likely touched.**
- `hha-dashboard/api/app/services/pdf_extract.py` (`102, 136, 181` — three concrete bug fixes)
- `hha-dashboard/api/pyproject.toml` — pin `azure-ai-documentintelligence` to the exact version we're testing against
- `hha-dashboard/api/tests/test_pdf_extract.py` — add a fixture for an empty-tables PDF + a fixture that calls the real SDK signature (mocked, but typed correctly)
- `hha-dashboard/jobs/upload_ingest/extractors/census_pdf.py` — confirm the caller still works (likely no change)

**Acceptance criteria.**
1. `uv run mypy app/services/pdf_extract.py` exits 0.
2. New pytest fixture exercises the corrected SDK call signature with a mocked response and asserts the extraction returns the expected `CensusExtractionResult`.
3. A test that runs the extractor against a PDF with zero tables returns an empty `matches` list and a clear `unmatched_rows` warning, not a `NoneType` crash.
4. Manual: upload a real census PDF via `/uploads`; row flips to `processed` with `rows_written > 0` (deferred — needs a real PDF + Document Intelligence resource; document the procedure in the test plan).

**Test command.**
```bash
cd hha-dashboard/api && uv run mypy app/services/pdf_extract.py
cd hha-dashboard/api && uv run pytest tests/test_pdf_extract.py -v
```

**Risk level.** Medium. The SDK changelog is the source of truth here. If the breaking change is more substantial than an overload reorder, the diff balloons. Spike for ~30 min on the SDK version diff before committing to a fix shape.

---

### T9 — Playwright E2E for MSAL sign-in + 1 role-gated route

**Why it matters.** The frontend has zero browser-driven tests. MSAL config + Bicep `app_settings` + the encrypted `hha_session` cookie are a chain of three things that have to all be set correctly for sign-in to work, and they only manifest at runtime in a real browser. Today's vitest is module-level — it doesn't catch a redirect loop, a missing tenant ID, or a cookie-domain mismatch. The first user who tries to sign in on prod is the integration test. We need at least one happy-path E2E that catches a regression on this chain before it reaches Crystal.

**Files likely touched.**
- `hha-dashboard/web/package.json` — add `@playwright/test` devDep, `e2e:install` and `e2e:run` scripts
- `hha-dashboard/web/playwright.config.ts` (**create**)
- `hha-dashboard/web/e2e/sign-in.spec.ts` (**create**) — happy path: open `/`, get redirected to `/auth/sign-in`, dev-mode bypass to `/`, see the overview tile rendered with real data
- `hha-dashboard/web/e2e/operations.spec.ts` (**create**) — open `/operations`, click first site, see SiteCensusForm, type 198, save, confirm toast
- `hha-dashboard/.github/workflows/ci.yml` — add an E2E job that runs against a docker-compose-up'd backend
- `hha-dashboard/docs/RUNBOOK.md` § 6 — link to the E2E suite as a smoke-test reference

**Acceptance criteria.**
1. `npm run e2e:run` against a local stack passes 2 tests in under 60 seconds.
2. The CI job runs Playwright against the same fixture stack and gates the PR.
3. A regression that breaks `/auth/sign-in` (e.g., re-introducing the `next/headers` import in a client component) makes the E2E job red.

**Test command.**
```bash
docker compose up -d
cd hha-dashboard/api && uv run uvicorn app.main:app --port 8000 &
cd hha-dashboard/web && npm run dev &
cd hha-dashboard/web && npm run e2e:install && npm run e2e:run
```

**Risk level.** Medium. New tooling (Playwright), new CI job dependency (browser binaries cache). Risk of flake in CI; mitigate with a single retry and a clear timeout. The test set is intentionally small (2 specs) to bound scope — it's a smoke gate, not full E2E coverage.

---

## Phase 4 — Nice to have later

### T10 — ARCHITECTURE.md + ONBOARDING.md (bus-factor reduction)

**Why it matters.** The 5 ADRs cover decision rationale; RUNBOOK.md covers operations; CLAUDE.md covers session conventions. But there is no single document a brand-new engineer can read in 30 minutes to understand "what is this system, how does it fit together, where do I start." This is a real gap once the project grows beyond solo. It is **not** blocking demo, deploy, or first users — Akhil is the engineer and the context is in his head — so it sits in Phase 4. But the next engineer arriving (~6 months out per the v5 plan) will need it.

**Files likely touched.**
- `hha-dashboard/docs/ARCHITECTURE.md` (**create**) — system diagram, the 4 boards + scorecards, the FL/TX split, the audit chain, the cron job topology, the auth surfaces. Lifts heavily from the v5 DASHBOARD_PLAN.md but stays in the repo.
- `hha-dashboard/docs/ONBOARDING.md` (**create**) — "you just joined, do this in order: read these 3 ADRs, run QUICKSTART, run the verification suite, pick a P2 ticket from NEXT_BUILD_PLAN.md."
- `hha-dashboard/CLAUDE.md` — add cross-references to both new docs.

**Acceptance criteria.**
1. ARCHITECTURE.md is < 600 lines, uses one ASCII diagram and one table per major subsystem, links to each ADR for the deep dive.
2. ONBOARDING.md is < 200 lines, lists day-1 and week-1 actions, ends with a checklist.
3. CLAUDE.md links them in the "Read all three before any significant work" line.

**Test command.**
```bash
# no automated test; review-only
markdownlint hha-dashboard/docs/ARCHITECTURE.md hha-dashboard/docs/ONBOARDING.md
```

**Risk level.** Low. Documentation only. No code, no schema, no infra change.

---

## Summary

| # | Title | Phase | Time | Risk |
|---|---|---|---|---|
| T1 | Backfill 11 sites + harden seed_sites.py | Demo | 1.5h | Low |
| T2 | FL · Ventra / TX · manual UI labels | Demo | 1.5h | Low |
| T3 | CRLF normalize + .gitattributes + pre-commit | Deploy | 1h | Low-medium |
| T4 | SESSION_SECRET docs + fail-fast | Deploy | 1h | Low |
| T5 | Build + push job images to ACR (CI) | Deploy | 2h | Medium |
| T6 | App Insights SDK + correlation-id | Deploy | 3h | Medium-high |
| T7 | entra_jwt Any-leak fix | Users | 2h | Medium |
| T8 | pdf_extract SDK overload fix | Users | 1.5h | Medium |
| T9 | Playwright E2E (sign-in + 1 route) | Users | 2.5h | Medium |
| T10 | ARCHITECTURE.md + ONBOARDING.md | Later | 2h | Low |

**Recommended execution order:** T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10. Each PR is its own atomic merge against `main`. Phase 1 produces a demo-able artefact in roughly half a day. Phase 2 produces an Azure-deployable artefact within another day. Phase 3 is a real-user-ready artefact within another day. T10 fits whenever there's an empty afternoon.

Out-of-scope for this plan but worth tracking separately:
- Sponsor email send (user task, not engineering)
- Real Ventra ingestion code (waiting on vendor data shape — F1)
- Real Paycom API client (waiting on API access — F1)
- Per-site authorization (deferred per ADR-002)
- Bulk `dict` → `dict[str, Any]` mypy refactor across 9 router/model files (low-priority janitorial; can land alongside any of T6–T9)
