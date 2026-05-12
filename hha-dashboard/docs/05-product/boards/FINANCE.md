# Finance Board — Product Spec

> **Tile-by-tile spec.** What the Finance board shows, source, formulas, refresh cadence, RBAC.
>
> Audience: product owners + developers.
>
> Status: **Phase 1 live (manual entry only); Phase 2 will populate from Ventra (FL).** Last updated 2026-05-11.

## What is this board

Top-level financial health of HHA's book at HHA-level (no per-site margin — that's intentionally out of scope per ADR-005). It answers:

- Are collections on pace this month?
- Is AR aging in healthy buckets?
- Is the net collection rate (cash / charges) trending the right way?
- How much is HHA paying Ventra (the 5% fee)?

**State split is critical.** Florida = Ventra automated. Texas = manual entry. Every tile labels its source explicitly so execs always know what's automated vs not.

## URL + access

- **URL:** `https://app-hha-web-prod.azurewebsites.net/finance`
- **Required role:** `exec` OR `owner_finance`
- **Refresh cadence:** auto on load + manual

## Tiles

### Daily / MTD collections vs target (by state)

**What it shows:** Two side-by-side cards (FL · TX). Each card has:

- Yesterday's collections $
- MTD collections $
- MTD target $
- % of target hit

**Source:**

- FL: `facts.collections_daily` WHERE `state = 'FL'` (Phase 2 from Ventra)
- TX: `entries.monthly_finance_manual` WHERE `state = 'TX'` (Phase 1 manual)

**Formulas:**

```sql
-- Yesterday
SUM(payments_received) WHERE posting_date = current_date - 1 AND state = ?

-- MTD
SUM(payments_received) WHERE date_trunc('month', posting_date) = date_trunc('month', current_date) AND state = ?

-- MTD target
SUM(monthly_target_amount) WHERE state = ? AND month = current month
-- (target stored in masters.monthly_targets — admin-managed)

-- % of target
mtd_collections / (target * day_of_month / days_in_month)
```

**Display:**

- Large $ amount with thousands-comma formatting
- Below: `[FL · Ventra]` or `[TX · manual]` source tag
- Progress bar against MTD target
- Color: green if ≥ 100%, yellow 90-100%, red < 90%

### AR aging 5-bucket (by state)

**What it shows:** Horizontal stacked bar per state. Buckets: 0-30, 31-60, 61-90, 91-120, 120+, credit.

**Source:**

- FL: `facts.ar_snapshot` WHERE `snapshot_date = latest available` AND `state = 'FL'`
- TX: `entries.monthly_finance_manual` — manual end-of-month AR balance (no per-bucket detail in TX until Ventra-equivalent vendor selected)

**Formula:**

```sql
SELECT aging_bucket, SUM(outstanding_amount)
FROM facts.ar_snapshot
WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM facts.ar_snapshot WHERE state = 'FL')
  AND state = 'FL'
GROUP BY aging_bucket
ORDER BY aging_bucket;
```

**Display:** Stacked horizontal bar with $ amounts. Hover for percentage. Aging > 120d shows red overlay.

### Days in A/R

**What it shows:** Rolling 90-day Days-in-AR.

**Formula:**

```
days_in_AR = total_AR / (rolling_90_day_charges / 90)
```

Where:

- `total_AR` = sum of all aging buckets (excl `credit`) at latest snapshot
- `rolling_90_day_charges` = SUM(gross_charges) over last 90 days

**Display:** Number of days. Color: green < 45, yellow 45-60, red > 60.

### Net collection rate

**What it shows:** Top-line net collection rate (cash collected / net revenue) for the last 12 months as a trend chart.

**Formula:**

```
net_collection_rate_month = SUM(payments_received) / SUM(net_revenue)
```

Trended monthly. Color: green > 95%, yellow 90-95%, red < 90%.

### Ventra fee (5%)

**What it shows:** Estimated fee paid to Ventra for the month.

**Source:** Calculated, not stored.

**Formula:**

```
fee = SUM(collections) * 0.05 WHERE source_system = 'VENTRA_FL_ATHENA' AND month = current
```

Note: actual fee is per Ventra contract; 5% is the documented rate. Use this for sanity-check; don't accrue against this number for accounting.

**Display:** $ amount. Informational only.

### Monthly revenue trend

**What it shows:** Last 12 months' net revenue, by state, as a stacked area chart.

**Source:** `facts.collections_daily` aggregated to month.

## API endpoints

| Endpoint | Tile |
|---|---|
| `GET /api/v1/finance/collections/daily` | Collections tiles |
| `GET /api/v1/finance/ar/aging` | AR aging bar |
| `GET /api/v1/finance/days-in-ar` | Days in AR |
| `GET /api/v1/finance/net-collection-rate` | NCR trend |

See [API_ENDPOINT_CATALOG.md](../API_ENDPOINT_CATALOG.md) § Finance.

## Data freshness

| Source | Latency |
|---|---|
| FL collections (Phase 2) | Daily — 7 a.m. CT after Ventra delivery |
| TX collections (Phase 1) | Monthly — when Sandy enters |
| AR snapshot (Phase 2 FL) | Daily preferred; month-end fallback per [INGESTION_VENTRA.md](../INGESTION_VENTRA.md) |
| AR snapshot (Phase 1 TX) | Monthly |

## RBAC

| Role | Access |
|---|---|
| `admin` | Full read + admin entry form |
| `exec` | Full read |
| `owner_finance` | Full read; manual entry for TX |
| Others | No access |
| `comp_viewer` | No additional Finance access (this flag is for scorecards only) |

## Alerts

- **MTD collections < 80% of target by mid-month** → daily digest
- **Days in A/R > 60** → daily digest
- **120+ bucket > 5% of total AR** → weekly digest
- **NCR < 90% for 2 consecutive months** → daily digest

## Phase 2 cutover

When Phase 2 ships:

1. **Shadow mode** — write Ventra data to `facts.collections_daily_staging` for 2 weeks
2. **Reconcile** — Akhil + HHA finance compare staging vs Ventra monthly report; target ≤$1K/site variance
3. **Cutover** — swap UI to read from `facts.collections_daily` (live table)
4. **Retire manual FL entry** — TX-only manual entry continues; Sandy notified

## Phase 3+ enhancements

| Item | Phase |
|---|---|
| Drill-down to per-payer-class breakdown | Phase 3 |
| Per-site margin (currently out of scope; needs sponsor approval) | Phase 4+ |
| Cash forecast (90-day projection) | Phase 4 |
| Power BI export | Phase 4 (if sponsor asks) |

---

**Next read:** [boards/CLINICAL.md](CLINICAL.md)
