# Tomorrow's Plan — HHA Dashboard

- **Date written:** 2026-04-27 (end of day)
- **Branch state:** 8 PRs merged to `main` today (#27 docs sprint, #28 acr/rbac/deploy-prod, #29–#34 the verification → audit → polish → deploy-prep → AI SDK → entra-jwt chain).
- **Phase 1 complete:** demo-credible UI with real 11 sites + FL/TX provenance labels + Recharts on Finance + per-site detail.
- **Phase 2 complete:** every audit-flagged Azure-deploy prerequisite shipped (CRLF + pre-commit hook, SESSION_SECRET fail-fast, build-job-images workflow, App Insights SDK + correlation-id middleware).
- **Phase 3 in progress:** T7 (entra_jwt typed claims) shipped today. T8, T9, T13, T14 queued.

## Today's wins

| PR | Title | Phase / ticket |
|---|---|---|
| #29 | chore: local verification pass | Audit setup |
| #30 | feat(dashboard): demo-credible polish | T1 + T2 + Recharts |
| #31 | chore: pre-deploy prep | T3 + T4 |
| #32 | ci: build-job-images workflow | T5 |
| #33 | feat(api): App Insights SDK + request-id middleware | T6 |
| #34 | fix(auth): typed VerifiedClaims model | T7 |

Backend tests: 207 → 221 passing (+14 across the chain). mypy on entra_jwt clean. biome lint clean. next build green across 21 routes. 11 real sites in DB.

## Tomorrow — Phase 3 remaining (engineering)

### T8 — Fix `pdf_extract.py` Azure SDK overload (~1.5h)

`api/app/services/pdf_extract.py:181` — the `azure-ai-documentintelligence` SDK changed `begin_analyze_document`'s signature in a recent release. mypy flags the overload mismatch; runtime crash on Crystal's first real PDF upload (B-04 from the audit, plus `union-attr` at line 102 for the empty-tables edge case).

- Pin SDK version explicitly in `pyproject.toml`
- Read the SDK changelog for the breaking change
- Update `pdf_extract.py:102, 136, 181`
- Add fixture for empty-tables PDF (the `union-attr` crash path)
- mypy clean on this file

### T9 — Playwright E2E for sign-in + 1 role-gated route (~2.5h)

Zero browser-driven tests today. CLAUDE.md mandates this for sign-in + role-gated routes. PR #29's build-blocker would have been caught by a single page-render test.

- `npm install --save-dev @playwright/test`
- `web/playwright.config.ts` (Chromium only initially)
- `web/e2e/sign-in.spec.ts` — happy path: open `/`, dev-mode redirect to `/`, see overview tile
- `web/e2e/operations.spec.ts` — open `/operations`, click first site, see SiteCensusForm, save, confirm toast
- `.github/workflows/ci.yml` — new e2e job that boots docker-compose + dev servers + runs Playwright

### T13 — Audit-trigger full table coverage (~1h)

`api/tests/test_audit_triggers.py` only exercises `entries.daily_entries`. The other 8 audited tables (per `services/audit.py::AUDITED_TABLES`) are unverified.

- Parameterize the existing trigger test across all 9 tables
- INSERT/UPDATE/DELETE per table → assert audit row written + diff shape
- Confirm `_claim_names`-overage path doesn't mistakenly write audit rows

### T14 — Alembic round-trip up/down test (~1h)

CLAUDE.md requires `downgrade()` to work on every migration. Nothing enforces it.

- New `tests/test_migrations.py`
- For each migration 0001 → 0010: `alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head` — assert no exceptions
- Add to CI

## Tomorrow — Phase 4 (lower priority but valuable)

### T10 — `ARCHITECTURE.md` + `ONBOARDING.md` (~2h)

Bus-factor reduction. The 5 ADRs cover decision rationale; RUNBOOK covers operations; CLAUDE.md covers conventions. **Nothing covers "what is this system, where do I start"** in a single doc.

- `docs/ARCHITECTURE.md` — system diagram, the 4 boards + scorecards, FL/TX split, audit chain, cron job topology, auth surfaces. < 600 lines, 1 ASCII diagram, 1 table per subsystem.
- `docs/ONBOARDING.md` — day-1 / week-1 actions checklist for the next engineer. < 200 lines.
- Cross-link from `CLAUDE.md`.

### Bulk mypy `dict` annotation cleanup (~1h)

41 `dict` → `dict[str, Any]` annotations across 9 router/model files. Mechanical refactor; satisfies mypy strict mode.

## Vendor + business gates (Akhil's tasks, not engineering)

These don't move with code. Schedule them in parallel.

1. **Sponsor email** — draft from earlier session at `docs/SPONSOR_EMAIL_DRAFT.md` (if committed). Send to CEO + CFO.
2. **Azure subscription** — provision `hha-production` under HHA M365 tenant.
3. **Entra app registrations** — `hha-dashboard-{web,api}-{dev,prod}` per [docs/ENTRA_SETUP.md](../03-engineering/ENTRA_SETUP.md).
4. **Entra security groups** — 7 groups per [ADR-002](../02-architecture/adr/002-rbac-model.md).
5. **Ventra BAA** — confirm in writing. Gating for Phase 2 ingestion.
6. **Paycom API access** — 4–6 week request window (started 2026-04-26).

## First Azure deploy (T17, when above gates pass)

Once Akhil has the subscription + Entra setup, run:

```bash
ENV=dev
RG=rg-hha-dashboard-${ENV}

# Phase 1: provision
az deployment group create \
  -g $RG -f infra/main.bicep \
  -p infra/env/${ENV}.bicepparam \
  -p postgres_admin_password='__placeholder__' \
  -p deployer_workstation_ip=$(curl -s ifconfig.me) \
  -p azure_tenant_id_for_kv=$(az account show --query tenantId -o tsv)

# Phase 2: secrets (postgres password + database URLs in KV)
ENV=dev bash infra/bootstrap.sh

# Phase 2.5: SESSION_SECRET (per RUNBOOK § B.2.5)
az keyvault secret set --vault-name kv-hha-${ENV} \
  --name session-secret --value "$(openssl rand -base64 32)"
az webapp config appsettings set -g $RG -n app-hha-web-${ENV} \
  --settings "SESSION_SECRET=@Microsoft.KeyVault(VaultName=kv-hha-${ENV};SecretName=session-secret)"
az webapp restart -g $RG -n app-hha-web-${ENV}

# Phase 2.6: build + push job images (per RUNBOOK § B.2.6)
gh workflow run build-job-images.yml -f environment=${ENV}

# Phase 3: seed application data
cd hha-dashboard/api
uv run python ../scripts/seed_sites.py
bash ../infra/census_seed.sh --email crystal@hhamedicine.com --rotate-random
bash ../infra/seed_alert_subscriptions.sh --role exec --email cfo@hhamedicine.com --frequency daily

# Phase 4: smoke
curl -s https://app-hha-api-${ENV}.azurewebsites.net/health
curl -s https://app-hha-api-${ENV}.azurewebsites.net/ready
```

**Capture every surprise in `docs/FIRST_DEPLOY_NOTES.md`.** Those become the next iteration's RUNBOOK additions.

## Recommended order for tomorrow

1. **Morning** — T8 (pdf_extract) — quick win, removes a real runtime crash. ~1.5h.
2. **Morning** — T13 (audit triggers all tables) — ~1h. Quick.
3. **Lunch** — T14 (alembic round-trip) — ~1h.
4. **Afternoon** — T9 (Playwright E2E). New tooling, biggest single ticket. ~2.5h.
5. **Late afternoon if time** — T10 docs (ARCHITECTURE + ONBOARDING). Pure writing. ~2h.
6. **Vendor track in parallel** — Akhil schedules the Ventra/Paycom/Tenant-Admin items.

After tomorrow: Phase 3 + Phase 4 mostly complete. The only remaining engineering before users sign in is anything surfaced during T17 first-deploy. That's a separate conversation (calendar event, not engineering).

## Known unknowns

- Will `configure_azure_monitor` (T6) play cleanly with our async SQLAlchemy + structlog under real Azure load? Local tests pass mocked. First prod request is the real test.
- Does the `build-job-images.yml` workflow's OIDC federated credential subject pattern match what's actually configured on the Azure side? Audit assumes yes; first `gh workflow run` will tell.
- Is the Postgres firewall properly opened to App Service outbound IPs? Bicep wires it; first deploy validates.

These are deploy-time discoveries, not engineering blockers.

## Out of scope for tomorrow

- Adding new boards / new entry forms
- Real Ventra / Paycom ingestion (vendor-blocked, F1)
- Per-facility logins (rejected — contradicts F2 + ADR-002)
- shadcn/ui migration
- Custom App Insights alert rules (T16, needs SLA decisions)
- Frontend Application Insights JS SDK
- App Insights live-metrics streaming
