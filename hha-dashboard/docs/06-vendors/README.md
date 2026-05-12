# 06 — Vendors

> **Audience:** Engineers + leadership working with external data partners.

Each vendor gets its own subfolder with:

- A README (vendor overview, BAA status, integration shape)
- Data requirements (what we need from them)
- Question banks for vendor meetings
- Email drafts
- Meeting scripts and recaps

## Vendors

| Vendor | Folder | Scope | BAA |
|---|---|---|---|
| **Ventra Health** | [ventra/](ventra/) | RCM for Florida hospitals only | 🟡 Pending written confirmation |

Texas RCM has no vendor today — data is manual entry per [adr/005-fl-tx-scope-split.md](../02-architecture/adr/005-fl-tx-scope-split.md).

## Future vendors

If/when these are added (per [01-leadership/ROADMAP.md](../01-leadership/ROADMAP.md)):

| Future vendor | Phase | Folder (when added) |
|---|---|---|
| Paycom (HR / payroll) | Phase 4 | `paycom/` |
| Athenahealth (direct, instead of via Ventra) | Phase 4 contingency | `athenahealth/` |

Each new vendor folder follows the same template as `ventra/`.

## Related folders

- [../03-engineering/INGESTION_VENTRA.md](../03-engineering/INGESTION_VENTRA.md) — implementation of the Ventra data pipeline
- [../01-leadership/COMPLIANCE_POSTURE.md](../01-leadership/COMPLIANCE_POSTURE.md) — BAA inventory

---

*Back to [docs/README.md](../README.md) for the full doc map.*
