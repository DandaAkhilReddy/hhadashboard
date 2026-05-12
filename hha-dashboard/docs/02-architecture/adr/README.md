# Architecture Decision Records (ADRs)

> **Audience:** Anyone changing architecture. Read the relevant ADR before designing a change.
>
> An ADR is a **locked, dated, short document** capturing one architectural decision and its rationale. ADRs are not edited after locking — if a decision changes, write a new ADR that supersedes the old one.

## Contents

| # | Decision | Status |
|---|---|---|
| [001](001-hipaa-data-classification.md) | **HIPAA data classification** — column-level `data_class` (A/B/C/D), no-PHI invariant, BAA inventory | Locked |
| [002](002-rbac-model.md) | **RBAC model** — 7 Entra security groups, `comp_viewer` additive flag, separate census-portal threat model | Locked |
| [003](003-audit-chain.md) | **Audit chain** — Postgres triggers (not ORM listeners), session-scoped `audit.upn` GUC propagation | Locked |
| [004](004-backup-and-disaster-recovery.md) | **Backup & DR** — managed Postgres PITR + custom pg_dump → Blob WORM, RTO/RPO commitments | Locked |
| [005](005-fl-tx-scope-split.md) | **FL/TX scope split** — Ventra is FL-only, TX manual-only, `source_system` invariant | Locked |

## How to add a new ADR

1. Copy the structure of an existing ADR (title, status, context, decision, consequences)
2. Number it `00N-short-kebab-name.md` where N is next in sequence
3. Get sponsor sign-off (both co-sponsors per [adr/005](005-fl-tx-scope-split.md) if it changes scope)
4. Add the row to the table above

## How to supersede an ADR

1. Write the new ADR (e.g., `006-new-approach.md`)
2. Update the old ADR's status from "Locked" to "Superseded by 006"
3. Link to the new ADR from the old one
4. Old ADR stays — it's history

---

*Back to [02-architecture/README.md](../README.md) or [docs/README.md](../../README.md).*
