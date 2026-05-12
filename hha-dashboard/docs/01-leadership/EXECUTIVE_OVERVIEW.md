# HHA Dashboard — Executive Overview

> **For HHA leadership.** Plain English. Read in 5 minutes. Last updated 2026-05-11.

## In one paragraph

HHA Dashboard is an internal, executive-only operations platform that gives HHA's leadership a single live view across **operations, finance, clinical quality, and workforce** for all 11 HHA hospitals. It replaces today's patchwork of Excel files and email digests. Phase 1 (daily census entry by site leaders) is **live in production today**. Phase 2 (automated finance metrics from Ventra, our RCM partner) is in design and depends on a data feed Ventra is building for us. The platform runs entirely on Microsoft Azure under our existing HIPAA-covered tenant and costs roughly **$35 per month** to run.

## Who uses it

- **Exec leadership** — CEO, CFO, CMO, COO. They view all dashboards.
- **Named department owners** — Crystal, Sandy, Maribel, Dr. Aneja, Dr. Reddy, Andrea. They enter monthly numbers via the entry forms.
- **Site leaders** — enter daily census numbers via the census portal (Phase 1).
- **Total user count: under 20.** No public access. No patient access.

Doctors and other clinical staff do **not** have logins. The system is exec-only.

## What's live today (Phase 1)

| Capability | Status |
|---|---|
| Daily census entry from each FL + TX site | ✅ Live |
| Operations board (today's census, MTD, variance, MD status per site) | ✅ Live with manual + portal data |
| Sign-in via your Microsoft 365 account | ✅ Live |
| Audit trail on every data change | ✅ Live |
| Daily Postgres backup with immutable storage | ✅ Live |
| Live URL | `https://app-hha-web-prod.azurewebsites.net` |

Custom domain `pulse.hhamedicine.com` is not yet bound (a one-day item for next sprint).

## What's coming (Phases 2–4)

| Phase | What it adds | Status | Target |
|---|---|---|---|
| **Phase 2** | Automated finance metrics from Ventra (FL only) + Doctor Scorecards | In design | June–July 2026 |
| **Phase 3** | Mobile-responsive polish, weekly digest email | Planned | August 2026 |
| **Phase 4** | Optional: Paycom integration for workforce data, multi-region failover | Future | 2027+ |

Details in [ROADMAP.md](ROADMAP.md).

## What this system is NOT

To prevent scope drift, the following are **explicitly out of scope**:

- **No denial analytics** — Ventra owns RCM end-to-end. We don't duplicate their work.
- **No patient identifiable information ever** — no patient names, DOBs, MRNs, or any HIPAA identifier in the database.
- **No claim-level data** — we work with aggregates only.
- **No Texas automated billing data** — TX is manual-entry only; only Florida is automated through Ventra.
- **No clinical decision support** — this is operations and finance reporting, not clinical workflow.
- **No external sharing** — system stays inside HHA's Microsoft tenant.

## What it costs

| Item | Monthly | Annual |
|---|---|---|
| **Current — Phase 1 in production** | **$35** | **$420** |
| If we upgrade for higher load (Phase 2+ heavier user count) | $200–465 | $2,400–5,600 |

Detail in [COST_AND_CAPACITY.md](COST_AND_CAPACITY.md).

For context: this is roughly the cost of one part-time consultant for half a day per month.

## HIPAA and compliance

HHA's data architecture is HIPAA-conscious by design.

- **Microsoft Azure BAA** covers all infrastructure (Postgres, App Service, Storage, Email, Key Vault, Entra).
- **No PHI in our database.** All Ventra data is aggregated at the ingestion edge — patient identifiers are read, summed in memory, discarded. Only roll-ups persist.
- **Audit trail** on every data change, with the responsible user attached.
- **Daily backups** to immutable (WORM) storage. Quarterly restore drill.
- **Encryption** at rest and in transit (TLS 1.2+).
- **Ventra BAA** is being confirmed (gating Phase 2).

Summary in [COMPLIANCE_POSTURE.md](COMPLIANCE_POSTURE.md). Engineering detail in [adr/001-hipaa-data-classification.md](../02-architecture/adr/001-hipaa-data-classification.md).

## What's the risk

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Vendor data delivery (Ventra) slipping | Medium | Phase 2 delays | Manual entry stays as fallback indefinitely |
| Solo engineer single-point-of-failure | Medium | Hand-off pain if Akhil leaves | This documentation set; comprehensive runbook; Microsoft-native stack means any Azure-fluent engineer can pick it up |
| Cost escalation if subscription tier upgraded | Low | $400/mo ceiling | Cost-tuned SKUs documented; alerts before upgrade |
| HIPAA breach (any vector) | Very low | Existential | Aggregate-only architecture is the strongest mitigation; daily audit log review; quarterly compliance check |
| Microsoft regional outage | Low | Hours of downtime | Recovery from PITR backup within 60 min documented in RUNBOOK |

The biggest risk by far is **solo-engineer dependence**. This documentation set is the primary mitigation — any senior Azure-fluent engineer can pick up the project cold by reading these docs.

## Who to call

| Scenario | Person | How |
|---|---|---|
| Day-to-day questions | Akhil Reddy, IT Director | areddy@hhamedicine.com |
| System is down | Akhil first, then Azure support | Az support via portal |
| Sponsor decisions / scope | HHA CEO + CFO | (per ADR-005, both co-sign) |
| HIPAA incident | Akhil → HHA legal → Microsoft BAA contact | See [SECURITY_INCIDENT_PLAYBOOK.md](../04-operations/SECURITY_INCIDENT_PLAYBOOK.md) |

## What leadership should review

- Monthly: [COST_AND_CAPACITY.md](COST_AND_CAPACITY.md) — confirm spending is on plan.
- Quarterly: [COMPLIANCE_POSTURE.md](COMPLIANCE_POSTURE.md) — confirm BAA inventory + audit trail integrity.
- Phase boundaries: [ROADMAP.md](ROADMAP.md) — sign off before each phase begins.

## What leadership does NOT need to review

- Technical architecture detail (engineers' problem)
- Code reviews (handled in GitHub)
- Day-to-day incident response (handled in runbook)

## Bottom line

HHA Dashboard is live, cheap, HIPAA-conscious, and documented for handoff. The platform is the lowest-risk way to centralize operations visibility for HHA's 11 hospitals. The only meaningful risk is solo-engineer dependence, which this documentation set is designed to eliminate.

---

**Next read for leadership:** [ROADMAP.md](ROADMAP.md)
