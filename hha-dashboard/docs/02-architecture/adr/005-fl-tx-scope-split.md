# ADR-005: Florida vs Texas Scope Split

- **Status:** Accepted
- **Date:** 2026-04-26
- **Deciders:** CEO + CFO co-sponsors (per scope decision 2026-04-23); Akhil Reddy implementing
- **Supersedes:** None

## Context

HHA's hospital book has 11 contracts: 7 in Florida and 4 in Texas. The two states have **different RCM relationships** that produce different data automation profiles, and we have to encode that in code rather than treat the two states as interchangeable.

- **Florida** — Ventra is HHA's RCM provider. Ventra has access to Athenahealth (the underlying PM system); Ventra ingests claims, denies, posts, follows up. We get **monthly aggregates** from Ventra.
- **Texas** — HHA does not have a Ventra contract for TX. RCM is handled by a different provider (out of scope for this dashboard) or directly by hospital partners. We get **manual entry from Sandy/Maribel** — they read the TX RCM provider's monthly statement and type the numbers in.

This is not a temporary state. There is no plan to extend Ventra to TX. There is no plan to build a TX-specific automation layer. **TX is manual-only, indefinitely.**

This ADR locks two invariants:

1. **Every finance row carries `source_system`** — never mix the two books.
2. **Ventra ingestion only fetches FL data.** A bug that lets Ventra read TX = incident.

## Decision

### Part 1 — `source_system` is required on every aggregate finance row

Tables affected: `entries.monthly_finance_manual`, `facts.fact_collections_daily`, `facts.fact_ar_snapshot` (when they land), `facts.fact_revenue_by_physician_mo`.

Schema:

```sql
source_system varchar(32) not null check (source_system in (
  'VENTRA_FL_ATHENA',     -- automated FL ingestion (when Ventra delivery confirmed)
  'VENTRA_FL_FALLBACK',   -- manual FL entry while Ventra integration is pending
  'HHA_TX_MANUAL'         -- TX manual entry (always)
))
```

Migration `0006_ventra_athena_source.py` already enforces the check. Service code (`api/app/routers/entries.py::_source_for_state`) maps state → tag at write time.

### Part 2 — UI labels every tile

Finance board tiles must show their provenance. Examples:

```
Collections (FL · Ventra)        $44.2M MTD
Collections (TX · manual)        $18.6M MTD
AR over 120 (FL · Ventra)        24%
AR over 120 (TX · manual)        31%
```

This is not garnish. The two numbers come from different processes with different latencies, different reconciliation cadence, and different definitions of "collected." A user looking at a single roll-up that adds them together is being misled. **Source label is part of the data; not a tooltip.**

### Part 3 — Ventra ingestion is FL-only by construction

`jobs/ventra_ingest/parser.py` rejects any row where the data shape (when Ventra confirms it) implies a TX site. The forbidden-column check in the parser already rejects unexpected columns; we extend it on first delivery to also reject rows mapping to TX `site_id`.

If a future contract change brings TX into Ventra's scope, that's a **new ADR + new ingestion path** (`HHA_TX_VENTRA` or similar source_system value), not a mutation of the existing one.

### Part 4 — Other boards are NOT split

The split applies only to **financial/billing data,** because that's the only thing Ventra owns. Operations / Clinical / People / Doctor Scorecards cover all 11 sites equally:

- **Operations** — daily census, open shifts, MD vacancy. Both states. Uniform source (Crystal types both via `/daily-census`).
- **Clinical** — H&P/DC compliance, LOS. Both states. Uniform source (Aneja/Reddy enter weekly).
- **People** — headcount, turnover, open positions. Both states, same source — **Paycom** (when API access lands; manual via Andrea until then). HHA's payroll runs through Paycom for ALL physicians regardless of state.
- **Doctor Scorecards** — comp + RVU. Both states, Paycom for workforce data, Athena (via Ventra, FL only) for revenue per FTE — but the Scorecards tile labels reflect that the revenue side is FL-only by note.

**Only Finance has the split.** Don't accidentally generalize.

## Consequences

### Code-level invariants

| Invariant | Where enforced |
|---|---|
| No row in `monthly_finance_manual` lacks `source_system` | DB CHECK constraint + Pydantic schema required field |
| Ventra ingestion never produces a row with `state='TX'` | `parser.py` validates |
| Finance UI labels every aggregated tile | `web/app/finance/page.tsx` (per-tile component contracts) |
| TX automation = scope creep | This ADR + CLAUDE.md scope-out list |

### When asked to "consolidate" the FL and TX numbers

**Don't.** A combined "Collections (HHA-wide)" tile is a real exec ask, but it's a *derived* aggregate that must show "FL: Ventra; TX: manual" provenance underneath. Implementation: render the combined number with a small footnote chip, never as a single source-less roll-up.

### When TX manual-entry diverges from Ventra-FL methodology

This will happen. Sandy will report TX collections via cash-receipts; FL via Ventra's posted-claims. The numbers don't reconcile to the same definition. **That's fine — they're tagged differently.** The exec read should be "FL collections (cash basis as posted by Ventra) vs TX collections (cash basis as reported by partner)" — provenance makes the difference legible.

### When auditing finance entries

- Filter by `source_system` to scope: `WHERE source_system LIKE 'VENTRA_FL%'` or `WHERE source_system = 'HHA_TX_MANUAL'`.
- The audit log captures the `source_system` value in every diff (it's a column on the underlying row).

### What this ADR explicitly REJECTS

- **A unified "RCM pipeline" abstraction** that handles FL and TX with a config switch. Speculative; YAGNI; encourages exactly the kind of mixing this ADR forbids.
- **Pulling TX from Athena directly.** HHA's TX hospitals are on different PM systems; Athena is FL-only here.
- **Backfilling the column on existing rows from "TX context."** If we ever discover an unsourced row, fix it forward (manual UPDATE with explicit `source_system`) rather than infer.

## Verification

- `tests/test_monthly_finance_router.py` — POST without `source_system` → 422.
- DB CHECK constraint — manual `INSERT ... source_system='UNKNOWN'` → integrity error.
- `tests/test_ventra_parser.py` — when given a TX-flagged row, the parser raises (forbidden-column path).
- Manual: load `/finance` and verify every tile shows `(FL · …)` or `(TX · manual)` label.

## References

- [api/alembic/versions/0006_ventra_athena_source.py](../../../api/alembic/versions/0006_ventra_athena_source.py)
- [api/app/models/entries_finance.py](../../../api/app/models/entries_finance.py) — `MonthlyFinanceManual`
- [api/app/routers/entries.py](../../../api/app/routers/entries.py) — `_source_for_state`
- [jobs/ventra_ingest/parser.py](../../../jobs/ventra_ingest/parser.py) — forbidden-column rejection
- [CLAUDE.md](../../../CLAUDE.md) — § "FL vs TX data sources" enforcement contract
