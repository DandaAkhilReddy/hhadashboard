# People & Pipeline Board — Product Spec

> **Tile-by-tile spec.** What the People board shows, source, formulas, refresh cadence, RBAC.
>
> Audience: product owners + developers.
>
> Status: **Phase 1 manual entry; Phase 4 may add Paycom automation.** Last updated 2026-05-11.

## What is this board

Workforce health across all 11 HHA sites (FL + TX equally — Paycom serves both). Answers:

- How many W-2 vs 1099 providers do we have?
- How many positions are open and where?
- Is turnover rising or stable?
- What's the coverage fill rate?
- Are any compensation agreements below fair-market-value (FMV)?

## URL + access

- **URL:** `/people`
- **Required role:** `exec` OR `owner_hr`

## Tiles

### Headcount W-2 vs 1099

**What it shows:** Two side-by-side counts. W-2 vs 1099 providers.

**Source:**

- Phase 1: `masters.physicians` filtered by `employment_type`
- Phase 4: `facts.headcount_daily` (Paycom-sourced, daily snapshot)

**Formula:**

```sql
SELECT employment_type, COUNT(*) FROM masters.physicians WHERE is_active GROUP BY 1;
```

**Display:** Two big numbers with a ratio bar. Stack labels by site optionally.

### Total open positions

**What it shows:** Total open positions across all sites.

**Source:** `entries.open_positions` WHERE `status = 'open'`.

**Display:** Big number. Color: red if > 5.

### Open positions by site

**What it shows:** Bar chart, one bar per site, height = open positions count.

**Source:** Same as above, grouped by `site_id`.

**Display:** Horizontal bar chart, sorted descending. Sites with 0 open show "—".

### 90-day rolling turnover

**What it shows:** Percent of headcount that departed in the last 90 days.

**Formula:**

```sql
SELECT
  COUNT(t.id)::float / NULLIF(COUNT(DISTINCT p.id), 0) AS turnover_pct
FROM masters.physicians p
LEFT JOIN facts.terminations t ON t.physician_id = p.id
  AND t.termination_date BETWEEN now() - interval '90 days' AND now()
WHERE p.is_active OR t.id IS NOT NULL;
```

**Display:** Percent. Trend sparkline 12 months. Color: green < 10%, yellow 10-15%, red > 15%.

### Below-FMV count

**What it shows:** Number of physicians whose effective compensation is below the fair-market-value (FMV) band for their role/region.

**Source:** Computed by `services/comp.py:effective_comp` against per-role FMV reference tables.

**Formula:** Custom service — joins `masters.physicians` × `masters.comp_agreements` × `dims.fmv_bands`.

**Display:** Count. **Visible only to `comp_viewer` group** (per ADR-002). Other roles see "—".

### Coverage fill rate

**What it shows:** Percent of scheduled clinical shifts that were filled in the last 30 days.

**Source:**

- Phase 1: monthly manual entry
- Phase 4: from a scheduling system (TBD; out of scope until Phase 4)

**Formula:** `filled_shifts / scheduled_shifts`.

**Display:** Percent. Green > 95%, yellow 90-95%, red < 90%.

## API endpoints

| Endpoint | Tile |
|---|---|
| `GET /api/v1/people/headcount` | Headcount W-2/1099 |
| `GET /api/v1/people/open-positions` | Open positions total + by site |
| `GET /api/v1/people/turnover` | Turnover |
| `GET /api/v1/people/fill-rate` | Fill rate |
| `POST /api/v1/people/positions` | Add new open position |

## Data freshness

| Tile | Latency |
|---|---|
| Headcount | Real-time (Phase 1); daily (Phase 4 Paycom) |
| Open positions | Real-time as manual entries land |
| Turnover | Daily |
| Below-FMV | Daily |
| Fill rate | Monthly manual; daily (Phase 4) |

## RBAC

| Role | Access |
|---|---|
| `exec`, `owner_hr`, `admin` | Full read |
| `comp_viewer` | Sees Below-FMV tile (others can't) |
| Others | No access |

## Alerts

- **Open positions > 5 at any site** → weekly digest
- **Turnover > 15%** → weekly digest
- **Below-FMV count > 0** → monthly digest (sensitive — only to `comp_viewer`+`exec`)
- **Coverage fill rate < 90%** → weekly digest

## Phase 4 enhancement — Paycom integration

If/when Paycom API access is approved:

1. Build `jobs/paycom_sync` (similar pattern to Ventra ingest)
2. Nightly pull → `facts.headcount_daily`, `facts.rvu_paycheck`, `facts.terminations`
3. Retire most manual entry (only fill rate stays manual until scheduling system selected)

Until then: this board is heavier on manual entry than the others.

---

**Next read:** [boards/DOCTOR_SCORECARDS.md](DOCTOR_SCORECARDS.md)
