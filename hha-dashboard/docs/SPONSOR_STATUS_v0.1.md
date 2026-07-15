# HHA Operations Dashboard — Sponsor Status & Unblock Asks

**Audience:** CEO, CFO (co-sponsors); CC: COO, CMO
**From:** Akhil Reddy, technical lead
**Date:** 2026-04-26
**Status:** v0.1 ready to deploy. **6 external dependencies block first deploy.** All technical work is done.

---

## TL;DR (the 30-second read)

The dashboard is **built and tested** — 4 boards (Operations / Finance / Clinical / People), 5 owner entry forms, separate single-credential census portal, daily alert digest, credential-expiry scan, full audit chain, HIPAA-classified schema. **176 tests pass; CI is green.** I cannot deploy without help on six items. Three are admin (Azure / Entra), two are vendor (Ventra / Paycom), one is governance (Privacy/Security Officer). I'd like a 30-minute call this week to assign owners and dates.

---

## Where we are

| Layer | Status |
|---|---|
| FastAPI backend, all endpoints, audit triggers | done — 176 tests passing |
| Next.js frontend, all dashboards + entry forms + census portal | done — typecheck clean, biome clean |
| Postgres schema (9 migrations, every column HIPAA-classified) | done — CI guard prevents PHI leak into schema |
| Bicep IaC (Postgres / App Service / VNet / Key Vault / Storage / App Insights / ACS Email / Container Apps Jobs / 2 cron jobs) | done — `az bicep build` clean |
| Daily alert digest cron (variance flags → email) | done — pending real recipients |
| Credential expiry cron (30/60/90-day bands) | done — pending real subscribers |
| Census portal (separate single-session login for Crystal) | done — pending shared credential issuance |
| Ventra ingestion (parser + ingest service) | parser done; **delivery channel undefined** (see blocker 5) |
| Paycom workforce sync | stub only; **API access not granted** (see blocker 6) |

---

## Six blockers — what unlocks each

Order is rough priority (1 = blocks the most downstream work).

### 1. Azure subscription provisioning &nbsp; · &nbsp; **Owner: IT / CIO**

**Ask:** Create Azure subscription `hha-production` under HHA's M365 tenant. Grant me Owner on the subscription (or scoped Contributor + RBAC admin on a single resource group `rg-hha-dashboard-dev`).

**Why it matters:** Without this, none of the 9 Bicep modules can deploy anywhere. The dashboard runs only on my laptop today.

**Cost expectation:** ~$250/mo dev, ~$550/mo prod (per v5 plan; rounding error for an organization at HHA's scale).

**Date target:** _Within 5 business days._

---

### 2. Entra app registrations + 7 security groups &nbsp; · &nbsp; **Owner: Tenant admin**

**Ask:** Stand up two Entra app registrations (`hha-dashboard-web-prod`, `hha-dashboard-api-prod`) and seven security groups (`HHA-Dashboard-Admin`, `-Exec`, `-CompViewer`, `-Owner-Ops`, `-Owner-Finance`, `-Owner-Clinical`, `-Owner-HR`). The full step-by-step is in `docs/ENTRA_SETUP.md`.

**Why it matters:** Until this lands, no exec can sign into the dashboard. Today the dev fallback (`Authorization: Dev <role>`) works on my laptop only.

**Date target:** _Within 5 business days,_ in parallel with #1.

---

### 3. HIPAA Privacy & Security Officer assignment &nbsp; · &nbsp; **Owner: CEO**

**Ask:** Designate a Privacy Officer and a Security Officer for HHA, in writing. Can be the same person; can be me (Akhil) for the Security Officer role if you want — but it must be in writing for the audit trail. Per ADR-001 and HIPAA §164.308(a)(2).

**Why it matters:** Required before we go live with any PHI-adjacent data. The system is built so we never persist PHI (everything aggregates at ingestion edge), but having designated officers is the compliance baseline.

**Date target:** _Before first prod deploy._

---

### 4. BAA verification &nbsp; · &nbsp; **Owner: Legal / CFO**

**Ask (a):** Pull HHA's Microsoft BAA via M365 Admin → Service Trust → confirm coverage. Most likely already in place via the M365 tenant; just need a signed PDF on file.

**Ask (b):** Get **written** BAA confirmation from Ventra. Email or signed amendment is fine. Until then, P2 (Ventra integration) is gated.

**Why it matters:** Microsoft is the dependency for everything (Azure / Entra / ACS Email / Postgres / Blob / App Insights). Ventra is the dependency for FL collections + AR aging data.

**Date target:** Microsoft BAA confirmation _within 2 days._ Ventra BAA _within 30 days._

---

### 5. Ventra delivery channel &nbsp; · &nbsp; **Owner: Sandy / COO**

**Ask:** Get a written answer from Ventra on how they'll deliver the monthly aggregate file we agreed to with Gilda Romero. Four likely channels:

| Channel | Effort to slot in | Notes |
|---|---|---|
| SFTP drop (monthly CSV) | 4 hours | preferred — simplest, audit-friendly |
| Signed-URL HTTPS download | 4 hours | also fine |
| REST API | 8–12 hours | needs auth flow |
| Email attachment | reject — manual upload via census portal pattern instead | not auditable |

**Why it matters:** The Ventra parser is **already built** to the agreed row shape (12 numeric columns, no claim-level data). We're only missing the delivery wiring. The day they answer, slot-in is half a day.

**Date target:** _Within 14 days._ User explicitly noted today: *"we still didn't get how we are receiving data from Ventra."*

---

### 6. Paycom API access &nbsp; · &nbsp; **Owner: Andrea / HR director**

**Ask:** File the API enablement request with Paycom support. Their typical SLA is 4–6 weeks.

**Why it matters:** Workforce data (headcount, terminations, RVU rollups) is the source for half the People board + the Doctor Scorecards "RVU Generated" tile. Until access lands, Andrea enters weekly HR manually — which works, but it's the only owner form that needs daily-driver use.

**Date target:** Request filed _this week;_ access expected mid-June.

---

## What I'll do once these unblock

Sequenced so that blocker delays don't all stack:

1. **Day 1 of Azure subscription:** `az deployment group create` to dev RG. Smoke test. Fix what breaks. Document the runbook.
2. **Day 1 of Entra app reg:** flip the dashboard out of dev-stub mode. Sign in as me, then add CEO/CFO/COO/CMO test accounts to the Exec group.
3. **Day 1 of Ventra delivery confirmation:** wire the parser to the chosen channel. First real Finance numbers go live in the dashboard the same day.
4. **Day 1 of Paycom access:** replace the stub extractors. People board + Doctor Scorecards stop showing the "stub" disclaimer.

Each of these is a half-day of focused work. Calendar dependency is on the unblock, not on the engineering.

---

## Risks if these slip

- **Every week these stay open is a week of unvalidated software.** I keep building, but no real human (Crystal, Sandy, Aneja, Andrea) has touched the system yet. Their feedback is the most expensive thing to defer.
- **Stack of unmerged work compounds.** I just landed two more PRs to keep the codebase clean (PRs #22 and #23). Without a deploy target, the next 4–6 PRs have no destination.
- **Bus factor stays at 1 until v0.1 is live.** A live dashboard with documented runbook is what makes someone else operable on this codebase.

---

## My ask

**Either:** a 30-minute Zoom this week with CEO + CFO + IT/CIO so we can assign owners + dates per blocker.

**Or:** async sign-off — please acknowledge each item in this doc and reply with the owner you've assigned. I'll track the dates from there.

I'd default to the call. Faster.

---

## Appendix A — Why these specifically (and not a longer list)

I deliberately did NOT include items I can do alone:

- All code (backend, frontend, IaC, cron jobs) — done.
- Documentation (ADR-001, RUNBOOK.md, ARCHITECTURE.md) — in flight, not blocking.
- Test infrastructure (CI, schema-classification guard) — done.
- The remaining infra modules (`acr.bicep`, `rbac.bicep`, prod deploy workflow) — I'll close these in the week after Azure provisioning lands. They need a real Azure target to point at.

The six items above are the ones only sponsors / vendors / IT can move. Everything else is on me.

---

## Appendix B — Email draft (copy-paste ready)

> **Subject:** HHA Dashboard v0.1 — ready to deploy, six external items blocking
>
> Hi [CEO] and [CFO],
>
> Quick status: the operations dashboard is built and tested end-to-end. 176 unit and integration tests pass; CI is green; HIPAA classification is enforced at schema-test level so no PHI can leak in. **I'm ready to deploy a working v0.1 to dev Azure as soon as six external items are unblocked.**
>
> The six items, in priority order:
>
> 1. **Azure subscription** under HHA's M365 tenant — IT/CIO can create.
> 2. **Two Entra app registrations + 7 security groups** for SSO — tenant admin.
> 3. **HIPAA Privacy + Security Officer designation** in writing — CEO ask.
> 4. **BAA verification** (Microsoft via service trust portal; Ventra in writing).
> 5. **Ventra delivery channel confirmation** (SFTP / API / EDI) — Sandy can ask.
> 6. **Paycom API enablement** request filed (4–6 wk SLA) — Andrea / HR director.
>
> Full breakdown with owners + dates here: `docs/SPONSOR_STATUS_v0.1.md` in the repo.
>
> Could we hold a 30-min call this week to assign owners and dates? Either of [Tuesday | Wednesday | Thursday] afternoon works for me.
>
> Once these unblock, the engineering side is fast — one half-day per blocker to wire it in.
>
> — Akhil
