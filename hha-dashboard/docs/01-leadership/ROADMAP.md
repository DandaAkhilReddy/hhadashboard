# HHA Dashboard — Roadmap

> **For leadership and engineering.** Four phases. Current status: Phase 1 live. Last updated 2026-05-11.

## Phase overview

| Phase | What | Status | Window |
|---|---|---|---|
| **Phase 0** | Foundation — infra, schema, auth, CI/CD | ✅ Complete | Apr 2026 |
| **Phase 1** | Manual entry + Operations board live in prod | ✅ Live | May 2026 |
| **Phase 2** | Ventra finance automation + Doctor Scorecards | 🟡 Design | Jun–Jul 2026 |
| **Phase 3** | Polish + mobile + alerting | ⚪ Planned | Aug 2026 |
| **Phase 4** | Optional — Paycom integration, multi-region, advanced analytics | ⚪ Future | 2027+ |

---

## Phase 0 — Foundation (✅ Complete)

**What it delivered:**

- Azure subscription provisioned under HHA's Microsoft tenant
- Resource group `rg-hha-dashboard-prod` in `centralus` region
- Postgres Flexible Server (Burstable B1ms — cost-tuned)
- Key Vault for secrets (`kv-hha-prod2`)
- App Service Plan + two App Services (api + web)
- Storage Account for backups (with immutability)
- App Insights + Log Analytics
- GitHub Actions OIDC federated identity (no static credentials)
- Bicep IaC modules for all of the above
- Schema design: 6 Postgres schemas (`masters`, `entries`, `facts`, `audit`, `alerts`, `dims`)
- Alembic migrations (10 applied)
- HIPAA classification — every column tagged `data_class` A/B/C/D; CI test enforces no-PHI invariant
- Audit triggers on every mutating table
- 5 ADRs locked (HIPAA classification, RBAC, audit chain, backup/DR, FL/TX scope)

**Engineering gate met:** deploy via `az deployment group create`; sign in via Microsoft; data persists; audit log captures changes; backup + restore drill works.

**Reference:** [ARCHITECTURE.md](../02-architecture/ARCHITECTURE.md), [adr/](../adr)

---

## Phase 1 — Manual entry + Operations board (✅ Live)

**What it delivered:**

- **Daily census entry portal** (`/census`) for site leaders to enter daily census numbers per FL + TX site
- **Operations board** — today's census, 3-mo avg, MTD, variance, MD status per site; rolls up to state + overall totals
- **Manual entry forms** for monthly finance (Sandy/Maribel — Texas + Florida), clinical (Aneja), people (Andrea)
- **Audit log** captures every entry/edit with `audit.upn` propagation
- **Entra ID sign-in** via MSAL (browser + server)
- **Email digest** stub (daily 7am summary, currently configured for areddy@hhamedicine.com)
- **Site master** seeded — 11 hospitals

**Live as of:** 2026-05-04 (verified `https://app-hha-api-prod.azurewebsites.net/ready` = 200 with all 4 sub-checks ok)

**Cost:** ~$35/mo on degraded SKUs (B1ms postgres, B1 app plan, no VNet, no ACR, no Container Apps Jobs)

**Reference:** [PHASE_1_CENSUS_PORTAL.md](../05-product/PHASE_1_CENSUS_PORTAL.md), [boards/OPERATIONS.md](../05-product/boards/OPERATIONS.md)

---

## Phase 2 — Ventra finance + Doctor Scorecards (🟡 In design)

**Target window:** June–July 2026 (gated on Ventra data feed delivery date)

**What it adds:**

- **Automated daily collections** from Ventra (FL only) → `fact_collections_daily`
- **AR aging snapshot** from Ventra (FL only) → `fact_ar_snapshot`
- **Per-physician monthly metrics** from Ventra → `fact_revenue_by_physician_mo`
- **Finance board** populated with real numbers (currently manual entry only)
- **Doctor Scorecards** (exec-only) — RVU productivity, revenue/FTE, encounters/day, documentation timeliness, overall rank composite
- **HIPAA firewall ingestion job** — strips PHI at the edge, persists only aggregates

**Blocking item:** Ventra BAA confirmed + delivery shape agreed. Ventra sent their default claim-level extract spec (2026-05-08); HHA has asked for pre-aggregated CSVs instead. Awaiting Ventra response (Gilda on PTO until 2026-05-14).

**Decision tree:**

| Ventra answer | Work on our side |
|---|---|
| **Option A: pre-aggregated CSVs** (preferred) | ~2 weeks: parse 3 CSVs, UPSERT to fact tables |
| **Option B: claim-level CSV + we discard PHI on receipt** | ~4 weeks: full HIPAA firewall + aggregation logic |
| **Option C: REST API with claim-level** | ~5 weeks: same as B + paginated streaming |
| **Option D: raw 835 EDI** | ~6 weeks: same as B + EDI parser |

**Engineering effort estimate:** 2–6 weeks of solo-engineer time depending on which option lands.

**Exec gate to enter Phase 3:** for a chosen month, Finance board agrees with Ventra's client report within $1,000 per site (or 0.5% of monthly collections, whichever is greater).

**Reference:** [VENTRA_DATA_REQUIREMENTS.md](../06-vendors/ventra/DATA_REQUIREMENTS.md), [INGESTION_VENTRA.md](../03-engineering/INGESTION_VENTRA.md), [boards/FINANCE.md](../05-product/boards/FINANCE.md), [boards/DOCTOR_SCORECARDS.md](../05-product/boards/DOCTOR_SCORECARDS.md)

---

## Phase 3 — Polish + mobile + alerting (⚪ Planned)

**Target window:** August 2026 (after Phase 2 stabilizes)

**What it adds:**

- **Mobile-responsive pass** — execs use iPhone for morning check-ins
- **Custom domain** — `pulse.hhamedicine.com` with managed TLS certificate
- **Alert subscriptions** — per-recipient routing for credential expiry, AR threshold breach, census variance
- **Weekly digest email** in addition to daily morning email
- **Re-enable Key Vault purge protection** (currently off during early-deploy iteration)
- **Tighten Postgres firewall** — replace AllowAllAzureServices with VNet integration

**Engineering effort:** 1–2 weeks solo-engineer time.

**Cost impact:** none (uses existing managed cert + ACS Email tier).

---

## Phase 4 — Future / optional (⚪ 2027+)

These are **not committed** — they're parked for sponsor decision.

| Item | Trigger | Engineering effort |
|---|---|---|
| **Paycom integration** | HR confirms API access + Paycom BAA scope | 4–6 weeks |
| **Real-time HL7 / FHIR census feed** | Hospital IT willing to expose feed | 6–8 weeks |
| **Multi-region failover** | Azure regional outage incident OR compliance requirement | 2 weeks (Azure-native) |
| **Power BI integration** | Sponsor request for non-developer dashboards | 2–3 weeks |
| **Texas RCM automation** | TX vendor selected (currently no equivalent of Ventra in TX) | 8+ weeks (vendor-dependent) |

**Out of scope indefinitely** — these will not be built unless explicit sponsor approval changes scope:

- Patient PHI in any view or schema (per ADR-001)
- Denial analytics (Ventra's job per ADR-005)
- Cost-side P&L
- External sharing or vendor data marketplace
- Mobile app (mobile web is sufficient)

---

## Dependencies

| Dependency | Owner | Status | Phase blocked |
|---|---|---|---|
| Ventra BAA confirmed in writing | Ventra (Gilda) | Pending | Phase 2 |
| Ventra data delivery shape agreed | Ventra + HHA | Pending | Phase 2 |
| Ventra sample feed delivered | Ventra | Pending | Phase 2 build start |
| Athena BAA chain clarified | Ventra | Pending | Phase 2 prod cutover |
| Paycom API access | HHA HR + Paycom rep | Not started | Phase 4 (Paycom integration only) |
| Custom domain DNS record | HHA IT (Akhil owns) | Not started | Phase 3 |
| Azure subscription upgrade (if needed for VNet/GP-tier Postgres) | HHA CFO | Not requested | Phase 3 firewall tightening only |

---

## Status tracking

The roadmap is reviewed and updated:

- **Weekly** during active build phases
- **Monthly** at phase boundaries
- **Per phase** with sponsor sign-off before moving to the next phase

This document is the source of truth. If `DASHBOARD_PLAN.md` (in OneDrive) conflicts, this wins because it's version-controlled.

---

**Next read for leadership:** [COST_AND_CAPACITY.md](COST_AND_CAPACITY.md)
**Next read for engineering:** [ARCHITECTURE.md](../02-architecture/ARCHITECTURE.md)
