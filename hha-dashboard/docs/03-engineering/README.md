# 03 — Engineering

> **Audience:** Developers building or extending the system.
> **Start here:** [ONBOARDING.md](ONBOARDING.md) — Day-1 setup if you're new. Then [API_ENDPOINT_CATALOG.md](API_ENDPOINT_CATALOG.md) and [INGESTION_VENTRA.md](INGESTION_VENTRA.md).

Builder docs. Assumes you've read [../../CLAUDE.md](../../CLAUDE.md) and [../02-architecture/ARCHITECTURE.md](../02-architecture/ARCHITECTURE.md) first.

## Contents

- [ONBOARDING.md](ONBOARDING.md) — Day-1 checklist for a new contributor
- [ENTRA_SETUP.md](ENTRA_SETUP.md) — One-time Entra app registration setup (auth)
- [API_ENDPOINT_CATALOG.md](API_ENDPOINT_CATALOG.md) — Every FastAPI route, grouped by domain
- [INGESTION_VENTRA.md](INGESTION_VENTRA.md) — Phase 2 ingestion architecture (SFTP → Blob → Container Job → Postgres). The HIPAA firewall code pattern.

## Related folders

- [../../QUICKSTART.md](../../QUICKSTART.md) — fastest local dev setup (in the repo root, not this folder)
- [../02-architecture/](../02-architecture/) — for the "why" before the "how"
- [../04-operations/](../04-operations/) — runbooks and troubleshooting once you've shipped
- [../06-vendors/ventra/](../06-vendors/ventra/) — Ventra spec details that pair with INGESTION_VENTRA.md

---

*Back to [docs/README.md](../README.md) for the full doc map.*
