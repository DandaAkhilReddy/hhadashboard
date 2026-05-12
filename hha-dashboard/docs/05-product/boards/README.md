# Board specs

> **Audience:** Product owners + UI developers.
> **Start with the board you own.**

Each board doc follows the same template: tiles, sources, formulas, RBAC, refresh cadence, alerts, phase-by-phase enhancements.

## The 4 team boards + 1 scorecard

| Board | Audience | Status |
|---|---|---|
| [OPERATIONS.md](OPERATIONS.md) | All execs + owner_ops | **Phase 1 live** — daily census, MTD, variance, MD status per site |
| [FINANCE.md](FINANCE.md) | All execs + owner_finance | **Phase 1 manual only; Phase 2 FL via Ventra** — collections, AR aging, days in A/R, NCR |
| [CLINICAL.md](CLINICAL.md) | All execs + owner_clinical | **Phase 1 manual entry** — H&P/DC compliance, LOS, credentials expiring |
| [PEOPLE.md](PEOPLE.md) | All execs + owner_hr | **Phase 1 manual entry; Phase 4 Paycom** — headcount, open positions, turnover, fill rate |
| [DOCTOR_SCORECARDS.md](DOCTOR_SCORECARDS.md) | **exec only** | **Partial Phase 1; Phase 2 lights up Ventra-sourced tiles** — RVU, revenue per FTE, encounters/day, documentation, overall rank |

## What every board doc covers

- **What it shows** — the question this board answers
- **URL + access** — the route and RBAC
- **Tiles** — each tile's source, formula, display rules, empty state
- **API endpoints** — what powers each tile
- **Data freshness** — latency per source
- **RBAC** — exact role mapping
- **Alerts** — what triggers a digest entry
- **Phase 2+ enhancements** — what's coming
- **Known limitations / open items**

## Sensitivity warning

[DOCTOR_SCORECARDS.md](DOCTOR_SCORECARDS.md) is **exec-only**. Doctors never see their own rank or peers'. This is enforced by the `require_role(['exec'])` decorator on every scorecard endpoint and confirmed in [adr/002-rbac-model.md](../../02-architecture/adr/002-rbac-model.md).

---

*Back to [05-product/README.md](../README.md) or [docs/README.md](../../README.md).*
