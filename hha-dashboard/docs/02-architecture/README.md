# 02 — Architecture

> **Audience:** Software engineers, architects, technical reviewers, auditors.
> **Start here:** [ARCHITECTURE.md](ARCHITECTURE.md) — the canonical narrative deep-dive. Then [DIAGRAMS.md](DIAGRAMS.md) for visual versions of the same content.

System design, data model, and locked architectural decisions.

## Contents

- [ARCHITECTURE.md](ARCHITECTURE.md) — 14-section narrative deep-dive: invariants, the 5 planes, component details, data flows, HIPAA posture, CI/CD, observability, disaster recovery, cost model
- [DIAGRAMS.md](DIAGRAMS.md) — 10 Mermaid diagrams: system context (C4 L1), container (C4 L2), deployment, auth flows, ingestion, HIPAA firewall, audit chain, schema ERD, Gantt timeline
- [DATA_MODEL.md](DATA_MODEL.md) — every schema, table, column, with HIPAA `data_class` tag
- [adr/](adr/) — Architecture Decision Records (5 locked decisions)

## Related folders

- [../01-leadership/COMPLIANCE_POSTURE.md](../01-leadership/COMPLIANCE_POSTURE.md) — the leadership-friendly version of the HIPAA story (cross-references ADR-001)
- [../03-engineering/](../03-engineering/) — for "how do I build this" rather than "what does it look like"
- [../04-operations/](../04-operations/) — for "what does on-call do when X breaks"

---

*Back to [docs/README.md](../README.md) for the full doc map.*
