# Ventra Health — vendor integration

> **Audience:** Engineers + leadership working with the Ventra data feed.
> **Status:** Phase 2 in design. Data shape under negotiation as of 2026-05-11.

Ventra is HHA's RCM (Revenue Cycle Management) partner. They process billing for HHA's **Florida** hospitals via the Athenahealth practice-management system. We've asked them to deliver three pre-aggregated daily CSVs (Option A); currently their default delivery is claim-level (Option B).

## BAA status

🟡 **Pending** — Ventra to confirm in writing. Athenahealth coverage clarification also pending. Gating Phase 2 cutover. See [../../01-leadership/COMPLIANCE_POSTURE.md § BAA inventory](../../01-leadership/COMPLIANCE_POSTURE.md).

## Contents

- [DATA_REQUIREMENTS.md](DATA_REQUIREMENTS.md) — **The doc we send Ventra.** What HHA needs, in their language. Sent 2026-05-04 pre-meeting.
- [QUESTIONS.md](QUESTIONS.md) — Internal question bank organized by meeting block (BAA, scope, delivery shape, fields, ops). 60+ questions with anticipated answers.
- [MEETING_SCRIPT_30MIN.md](MEETING_SCRIPT_30MIN.md) — Literal speaking script for vendor calls: SAY / LISTEN FOR / IF-THEN / WRITE DOWN format. 5-page printable.
- [FOLLOWUP_EMAIL.md](FOLLOWUP_EMAIL.md) — Draft email asking Ventra to deliver pre-aggregated CSVs (Option A) instead of their claim-level Standard Data Extract.

## People

| Role | Name | Email |
|---|---|---|
| HHA technical lead | Akhil Reddy (IT Director) | areddy@hhamedicine.com |
| HHA exec sponsor | (per ADR-005, CEO + CFO co-sign) | — |
| Ventra Chief Data Officer | David Reck | (TBD) |
| Ventra VP Data & Analytics | Suma Bhat | (TBD) |
| Ventra client success | Gilda Romero, Stephanie | (TBD) |

## Phase 2 cutover plan

1. **BAA confirmed in writing** (gating)
2. **Delivery shape agreed** — Option A (pre-aggregated) or Option B (claim-level + HHA aggregates on receipt)
3. **SFTP endpoint provisioned on our side** (Bicep: enable SFTP on `sthhaprod`)
4. **SSH key exchanged**
5. **Sample feed delivered** to sandbox
6. **HHA builds ingestion job** — see [../../03-engineering/INGESTION_VENTRA.md](../../03-engineering/INGESTION_VENTRA.md)
7. **Shadow mode for 2 weeks** — Ventra data → `facts.*_staging`
8. **Reconciliation** — ≤$1K/site/month variance vs Ventra's client report
9. **Cutover to prod**

## Related folders

- [../../03-engineering/INGESTION_VENTRA.md](../../03-engineering/INGESTION_VENTRA.md) — implementation architecture
- [../../02-architecture/adr/005-fl-tx-scope-split.md](../../02-architecture/adr/005-fl-tx-scope-split.md) — why Ventra is FL-only
- [../../05-product/boards/FINANCE.md](../../05-product/boards/FINANCE.md) — the dashboard tiles Ventra data fills

---

*Back to [06-vendors/README.md](../README.md) or [docs/README.md](../../README.md).*
