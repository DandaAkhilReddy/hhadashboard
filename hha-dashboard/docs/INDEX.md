# Documentation index — HHA Dashboard

> **Read this first.** This is the doorway into the entire documentation set. If you don't know where to look for something, start here.

## Start here, based on who you are

| You are… | Read in this order |
|---|---|
| **A new HHA leader / sponsor** | 1. [EXECUTIVE_OVERVIEW.md](EXECUTIVE_OVERVIEW.md) → 2. [ROADMAP.md](ROADMAP.md) → 3. [COST_AND_CAPACITY.md](COST_AND_CAPACITY.md) → 4. [COMPLIANCE_POSTURE.md](COMPLIANCE_POSTURE.md) |
| **A new developer joining the project** | 1. [../CLAUDE.md](../CLAUDE.md) (the contract) → 2. [ARCHITECTURE.md](ARCHITECTURE.md) → 3. [DIAGRAMS.md](DIAGRAMS.md) → 4. [ONBOARDING.md](ONBOARDING.md) → 5. [../QUICKSTART.md](../QUICKSTART.md) |
| **An on-call engineer at 2 a.m.** | 1. [RUNBOOK.md](RUNBOOK.md) → 2. [TROUBLESHOOTING.md](TROUBLESHOOTING.md) → 3. [SECURITY_INCIDENT_PLAYBOOK.md](SECURITY_INCIDENT_PLAYBOOK.md) |
| **A compliance / audit reviewer** | 1. [COMPLIANCE_POSTURE.md](COMPLIANCE_POSTURE.md) → 2. [adr/001-hipaa-data-classification.md](adr/001-hipaa-data-classification.md) → 3. [adr/003-audit-chain.md](adr/003-audit-chain.md) → 4. [adr/004-backup-and-disaster-recovery.md](adr/004-backup-and-disaster-recovery.md) |
| **A product owner / exec for a specific board** | Pick your board: [boards/OPERATIONS.md](boards/OPERATIONS.md) · [boards/FINANCE.md](boards/FINANCE.md) · [boards/CLINICAL.md](boards/CLINICAL.md) · [boards/PEOPLE.md](boards/PEOPLE.md) · [boards/DOCTOR_SCORECARDS.md](boards/DOCTOR_SCORECARDS.md) |
| **A vendor / integration partner (e.g. Ventra)** | 1. [VENTRA_DATA_REQUIREMENTS.md](VENTRA_DATA_REQUIREMENTS.md) → 2. [INGESTION_VENTRA.md](INGESTION_VENTRA.md) → 3. [COMPLIANCE_POSTURE.md](COMPLIANCE_POSTURE.md) |

## The complete doc map

### Tier 1 — Leadership-facing

Plain English. No engineering jargon. Read in 5 minutes.

| Doc | What it answers |
|---|---|
| [EXECUTIVE_OVERVIEW.md](EXECUTIVE_OVERVIEW.md) | What is HHA Dashboard, who uses it, what's live, what's coming, what does it cost, what's the risk |
| [ROADMAP.md](ROADMAP.md) | Phase-by-phase plan with dates, dependencies, ownership, status |
| [COST_AND_CAPACITY.md](COST_AND_CAPACITY.md) | Monthly cost breakdown, 1-year and 3-year projections, scaling triggers |
| [COMPLIANCE_POSTURE.md](COMPLIANCE_POSTURE.md) | HIPAA controls summary, BAA inventory, audit trail design, incident reporting |

### Tier 2 — Architecture diagrams

| Doc | What it answers |
|---|---|
| [DIAGRAMS.md](DIAGRAMS.md) | 10 Mermaid diagrams: system context, containers, deployment, auth flow, ingestion data flow, HIPAA firewall, audit chain, schema ERD, phase progression |

### Tier 3 — Technical deep-dives

For engineers. Assumes you've read `CLAUDE.md` and `ARCHITECTURE.md`.

| Doc | What it answers |
|---|---|
| [DATA_MODEL.md](DATA_MODEL.md) | Every schema, table, and column in Postgres. data_class tag per column. |
| [INGESTION_VENTRA.md](INGESTION_VENTRA.md) | Ventra → SFTP → Blob → Container Job → Postgres. The HIPAA firewall. Both delivery shapes (pre-aggregated and claim-level). |
| [API_ENDPOINT_CATALOG.md](API_ENDPOINT_CATALOG.md) | Every FastAPI route by domain — auth, census, operations, finance, clinical, people, scorecards, admin. |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common dev + prod issues with fixes. Categories: local dev, Docker, Azure, deploy, alembic. |
| [SECURITY_INCIDENT_PLAYBOOK.md](SECURITY_INCIDENT_PLAYBOOK.md) | Breach response, suspicious audit logs, credential compromise. 5-stage runbook. |

### Tier 4 — Per-board product specs

What tiles, what data, what formulas, what refresh cadence, what RBAC.

| Doc | Board |
|---|---|
| [boards/OPERATIONS.md](boards/OPERATIONS.md) | Operations — daily census, open shifts, contract thru, MD status |
| [boards/FINANCE.md](boards/FINANCE.md) | Finance — collections, AR aging, days in A/R, net collection rate |
| [boards/CLINICAL.md](boards/CLINICAL.md) | Clinical Quality — H&P, DC, LOS, credentials expiring |
| [boards/PEOPLE.md](boards/PEOPLE.md) | People & Pipeline — headcount, open positions, turnover, fill rate |
| [boards/DOCTOR_SCORECARDS.md](boards/DOCTOR_SCORECARDS.md) | Doctor Scorecards (exec-only) — productivity, revenue, documentation |

### Tier 5 — Reference

| Doc | What it answers |
|---|---|
| [GLOSSARY.md](GLOSSARY.md) | Every term — HHA + healthcare + Azure + project-specific |
| [INDEX.md](INDEX.md) | This file. The doc map. |

### Existing docs (already in the repo, not duplicated by this set)

| Doc | What it answers |
|---|---|
| [../CLAUDE.md](../CLAUDE.md) | **The contract.** Coding conventions, HIPAA rules, prod state, commit cadence. Every session reads this first. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 14-section technical architecture deep-dive (ASCII diagrams). Pair with [DIAGRAMS.md](DIAGRAMS.md) for visual versions. |
| [ONBOARDING.md](ONBOARDING.md) | Day-1 checklist for a new developer. |
| [../QUICKSTART.md](../QUICKSTART.md) | Local dev setup in 5 commands. |
| [RUNBOOK.md](RUNBOOK.md) | On-call ops guide — health checks, incident playbooks, secret rotation, restore drill. |
| [ENTRA_SETUP.md](ENTRA_SETUP.md) | One-time Entra app-registration setup. |
| [PHASE_1_CENSUS_PORTAL.md](PHASE_1_CENSUS_PORTAL.md) | Census portal contract and threat model. |
| [PROJECT_STATE_AUDIT.md](PROJECT_STATE_AUDIT.md) | Forensic audit of what's actually built vs documented. |
| [SPONSOR_DEPLOY_ONE_PAGER.md](SPONSOR_DEPLOY_ONE_PAGER.md) | Pre-deploy executive brief. |

### Architecture Decision Records (ADRs)

| ADR | Decision |
|---|---|
| [adr/001-hipaa-data-classification.md](adr/001-hipaa-data-classification.md) | Column-level `data_class` tagging. No PHI in Postgres. |
| [adr/002-rbac-model.md](adr/002-rbac-model.md) | Entra groups, `comp_viewer` additive flag, census portal threat model. |
| [adr/003-audit-chain.md](adr/003-audit-chain.md) | PG triggers (not ORM listeners) for audit. Session-scoped `audit.upn` GUC. |
| [adr/004-backup-and-disaster-recovery.md](adr/004-backup-and-disaster-recovery.md) | Managed Postgres PITR + custom pg_dump → Blob with WORM. |
| [adr/005-fl-tx-scope-split.md](adr/005-fl-tx-scope-split.md) | Ventra services Florida only; Texas is manual-only. `source_system` invariant. |

### Vendor / integration docs

| Doc | About |
|---|---|
| [VENTRA_DATA_REQUIREMENTS.md](VENTRA_DATA_REQUIREMENTS.md) | The doc we sent Ventra — what HHA needs from them |
| [VENTRA_SCRIPT_30MIN.md](VENTRA_SCRIPT_30MIN.md) | Speaking script for vendor meetings |
| [VENTRA_QUESTIONS.md](VENTRA_QUESTIONS.md) | Deeper question bank |
| [VENTRA_FOLLOWUP_EMAIL.md](VENTRA_FOLLOWUP_EMAIL.md) | Follow-up email draft |

## Where the source of truth lives

| Question | Source of truth |
|---|---|
| Prod state | [../CLAUDE.md](../CLAUDE.md) § "Prod deploy state" |
| Architecture decisions | [adr/](adr/) (locked, dated) |
| Live system status | `https://app-hha-api-prod.azurewebsites.net/ready` |
| Roadmap | [ROADMAP.md](ROADMAP.md) (mirrors `DASHBOARD_PLAN.md` in OneDrive) |
| Cost | [COST_AND_CAPACITY.md](COST_AND_CAPACITY.md) |
| HIPAA classification | [adr/001-hipaa-data-classification.md](adr/001-hipaa-data-classification.md) |
| What the dashboard shows | [boards/](boards/) (per-board specs) |
| What's in the database | [DATA_MODEL.md](DATA_MODEL.md) |
| Glossary of terms | [GLOSSARY.md](GLOSSARY.md) |

## How to use this in SharePoint

If you're uploading to SharePoint for leadership review:

1. **Easiest path** — upload the `.md` files. SharePoint stores them; readers open them in any text viewer (or VS Code if installed). Diagrams in `DIAGRAMS.md` won't render visually but the text is readable.
2. **Best path** — run [scripts/export-to-pdf.sh](scripts/export-to-pdf.sh) (in this folder) to convert every `.md` to PDF with diagrams rendered. Upload the PDFs.
3. **Hybrid** — upload `EXECUTIVE_OVERVIEW.pdf`, `ROADMAP.pdf`, and `COST_AND_CAPACITY.pdf` for leadership; let developers reference the repo directly.

---

*Last updated: 2026-05-11 · Maintained by: Akhil Reddy (IT Director). When you change anything in this folder, update INDEX.md if a new doc is added or an old one is moved.*
