# Operations Board — Product Spec

> **Tile-by-tile spec.** What the Operations board shows, where the data comes from, how it's computed, refresh cadence, RBAC.
>
> Audience: product owners + developers building/maintaining the UI.
>
> Status: **Phase 1 LIVE.** Last updated 2026-05-11.

## What is this board

The Operations board is the **morning check-in** for HHA leadership. It answers:

- How many patients are on census at each site right now?
- Are any sites significantly above or below their 3-month trend?
- Are MD coverage and shifts looking healthy?
- Are any contracts expiring soon?

It is the **most-viewed board** in the dashboard. Execs check it before their first coffee.

## URL + access

- **URL:** `https://app-hha-web-prod.azurewebsites.net/operations`
- **Required role:** `exec` OR `owner_ops`
- **Refresh cadence:** auto-refresh on page load + manual refresh button; no live polling (would burn cache)

## Tiles

The board renders **11 site rows + a state-total row + an overall-total row**. Each row has these tiles:

### Today's census

**What it shows:** The integer census count entered for today at this site.

**Source:** `entries.census_daily` WHERE `entry_date = current_date` AND `site_id = ?`.

**Formula:** N/A — direct read.

**Display:** Large number (e.g., "18"). Color:

- Black if `today_census` is within ±15% of `three_mo_avg`
- Orange if outside ±15%
- Red if outside ±25% OR if no entry exists for today after 10 a.m. CT

**Empty state:** "— (not yet entered)" with a tooltip saying who is expected to enter (site lead's email).

### 3-month average

**What it shows:** Average daily census over the last 90 days at this site.

**Source:** `entries.census_daily` WHERE `site_id = ?` AND `entry_date BETWEEN current_date - 90 AND current_date - 1`.

**Formula:** `AVG(census_count)`, rounded to 1 decimal.

**Display:** Smaller, gray, below today's census.

### MTD (Month-to-date)

**What it shows:** Average daily census so far this month at this site.

**Source:** `entries.census_daily` WHERE `site_id = ?` AND `date_trunc('month', entry_date) = date_trunc('month', current_date)` AND `entry_date < current_date`.

**Formula:** `AVG(census_count)`, rounded to 1 decimal.

**Display:** Smaller, gray, next to 3-month avg.

### Variance

**What it shows:** Percent difference between today's census and 3-month average.

**Formula:** `((today_census - three_mo_avg) / three_mo_avg) * 100`. Rounded to 1 decimal.

**Display:** Signed percentage (e.g., `+9.8%`, `-23.1%`). Color:

- Green if within ±10%
- Yellow if 10–20%
- Red if > 20% in either direction

**Empty state:** "—" if either today_census or three_mo_avg is null.

### Open shifts

**What it shows:** Number of open clinical shifts at this site.

**Source:** `entries.open_positions` filtered to clinical roles, status='open' (Phase 1: manual entry via Admin → People form; Phase 4: auto-populated from Paycom).

**Display:** Integer. Red if > 2.

### Contract thru

**What it shows:** Earliest contract end date at this site.

**Source:** `masters.contracts` WHERE `site_id = ?` AND `end_date IS NOT NULL`.

**Formula:** `MIN(end_date)`.

**Display:** Date in `Mon YYYY` format. Color:

- Black if > 6 months out
- Yellow if 3-6 months out
- Red if < 3 months OR already expired

### Subsidy (Y/N)

**What it shows:** Whether the contract for this site includes a subsidy clause.

**Source:** `masters.contracts` boolean column `has_subsidy` (Phase 1 manual entry).

**Display:** Yes / No tag. Yes is informational only — not a coloring trigger.

### MD status

**What it shows:** Coverage status for today.

**Source:** Currently computed; long-term from real MD schedule (Phase 2+).

**Phase 1 implementation:** Color-coded label based on a fixed rule (presence of any open clinical shift makes status = `partial`; else `covered`).

**Display:** Pill: green `Covered` / yellow `Partial` / red `Uncovered`.

## State totals row

Below the per-site rows, two summary rows: **FL Total** and **TX Total**.

| Tile | Formula |
|---|---|
| Today's census | `SUM(today_census)` across all sites in that state |
| 3-mo avg | `AVG(three_mo_avg)` across all sites in that state — straight average, not weighted by census |
| MTD | `AVG(mtd)` similar to above |
| Variance | Recomputed from state totals: `(state_today - state_3mo) / state_3mo * 100` |
| Open shifts | `SUM(open_shifts)` across state |
| Contract thru | `MIN(contract_thru)` — earliest expiring contract |
| MD status | Worst across sites |

## Overall total row

| Tile | Formula |
|---|---|
| Today's census | `SUM(today_census)` across all 11 sites |
| 3-mo avg | `AVG(three_mo_avg)` |
| MTD | `AVG(mtd)` |
| Variance | `(overall_today - overall_3mo) / overall_3mo * 100` |
| Open shifts | `SUM(open_shifts)` |
| Contract thru | `MIN(contract_thru)` |
| MD status | Worst across all sites |

## API endpoint

`GET /api/v1/operations/summary` — returns the entire board's data in one call. Spec in [API_ENDPOINT_CATALOG.md](../../03-engineering/API_ENDPOINT_CATALOG.md) § Operations.

## Data freshness

| Source | Latency |
|---|---|
| Today's census (portal entry) | Real-time — written by site lead, visible on board within seconds |
| 3-mo avg, MTD | Computed at request time from `entries.census_daily` |
| Open shifts | As of last manual entry (Phase 1) or Paycom sync (Phase 4) |
| Contract thru | As of last admin entry |
| MD status | Computed at request time |

## RBAC

| Role | Access |
|---|---|
| `admin` | Full read + can drill into audit log |
| `exec` | Full read |
| `owner_ops` | Full read; can override census via manual entry form |
| `owner_finance` | No access |
| `owner_clinical` | No access |
| `owner_hr` | No access |
| `comp_viewer` | No additional access — orthogonal to this board |

## Alerts

The Operations board triggers these alerts (via `alerts.alert_subscriptions`):

- **Census missing** — site has no entry for the day by 10 a.m. CT → daily digest "missing entries"
- **Variance > 25%** — any site outside ±25% vs 3-mo avg → daily digest
- **Contract expiring 30/60/90d** — checked nightly, surfaces in digest
- **Open shifts > 3 at any site** — daily digest

Alerts route per [DATA_MODEL.md](../../02-architecture/DATA_MODEL.md) § `alerts.alert_subscriptions`.

## Phase 2+ enhancements

| Item | Phase |
|---|---|
| Live MD schedule integration (no more "computed" status) | Phase 4 |
| Sparkline trend per site | Phase 3 |
| Drill-down into 30-day timeline | Phase 3 |
| Mobile responsiveness pass | Phase 3 |

## Backend implementation notes

- The summary endpoint executes 4 parallel queries via `asyncio.gather`: today's census, 3-mo avg, open shifts, contracts. Total query time < 100ms in B1ms.
- Result is **not cached** at the API layer (cheap enough to compute on each request).
- If census data is missing for a site for today, the response includes `today_census: null` rather than failing.

## UI implementation notes

- **Server component by default** — initial render hits the API via the server fetcher.
- **Manual-refresh button** triggers a client-side `useEffect` revalidate (no full page reload).
- **Empty state** for a brand-new day (no entries yet): show all sites with `—` and a banner reminding site leads.
- Color thresholds defined in `web/lib/theme.ts` so they're consistent with Finance board variance coloring.

## Testing

| Test | Where |
|---|---|
| Unit test for summary formula edge cases (zero divisor, null entries) | `api/tests/test_operations_summary.py` |
| Integration test against real DB | `api/tests/integration/test_operations.py` |
| Playwright E2E — sign in, view board, see expected sites | `web/e2e/operations.spec.ts` |

## Known limitations / open items

| Item | Owner | Priority |
|---|---|---|
| MD status is heuristic, not real schedule | Phase 4 | Low |
| No drill-down on tile click yet | Phase 3 | Medium |
| No mobile-optimized layout yet | Phase 3 | Medium |

---

**Next read:** [boards/FINANCE.md](FINANCE.md) — the second-most-viewed board.
