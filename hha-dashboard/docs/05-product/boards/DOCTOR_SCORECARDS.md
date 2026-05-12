# Doctor Scorecards — Product Spec

> **Tile-by-tile spec.** What the Doctor Scorecards page shows, source, formulas, refresh cadence, RBAC.
>
> Audience: product owners + developers.
>
> Status: **Exec-only. Paycom-sourced tiles work in Phase 1; Ventra-sourced tiles light up in Phase 2.** Last updated 2026-05-11.

## ⚠ Sensitivity warning

This is the **most politically sensitive deliverable** in the entire dashboard. A misclassified physician number leaking outside the exec team could damage HHA's culture and physician relationships permanently.

**Two hard rules** (per ADR-002):

1. **Doctors never see their own rank or peers'.** No physician login can see this page. Period.
2. **`exec` role only.** Not `comp_viewer`. Not `admin`. Not any owner role. Only `exec`.

If a future product request asks "can we let doctors see this?", the answer is **no** unless both co-sponsors (CEO + CFO) approve in writing per the OUT-of-scope clause in CLAUDE.md.

## URL + access

- **URL:** `/scorecards`
- **Required role:** `exec` (and only `exec`)
- **Audit:** every read is logged in `audit.audit_log` with `actor_upn` for traceability

## What this board shows

A table or grid, one row per physician, with these columns:

### Identity columns

| Column | Source |
|---|---|
| Name | `masters.physicians.first_name + last_name` |
| Employment type | `masters.physicians.employment_type` (W2 / 1099 / Locum) |
| Primary site | `masters.physicians.primary_site_id` |
| Comp model | `masters.comp_agreements` (latest active row's `comp_model`) |
| Status | `masters.physicians.is_active` |

### Productivity columns

| Column | Source | Phase |
|---|---|---|
| RVU Generated | `facts.rvu_paycheck` aggregated to current month | Phase 1 (manual) / Phase 4 (Paycom) |
| Revenue per FTE | `facts.revenue_by_physician_mo` / FTE | Phase 2 |
| Encounters/day | `facts.revenue_by_physician_mo.encounters_count / days_in_month` | Phase 2 |

### Quality columns

| Column | Source | Phase |
|---|---|---|
| Documentation Score | `facts.revenue_by_physician_mo.chart_turnaround_median_hours` (provisional) | Phase 2 (if Ventra provides) |
| Chart Turnaround | Same source — median hours | Phase 2 (if Ventra provides) |

### Composite

| Column | Source | Phase |
|---|---|---|
| Overall Rank score | Computed — see formula below | Phase 2 |

In Phase 1, only RVU + identity columns show real numbers. Phase 2 lights up the Ventra-sourced quality columns. Until Phase 2, Ventra-sourced cells show "—" with tooltip "coming soon."

## Overall Rank composite (Phase 2)

The Overall Rank is a **composite score** for each physician relative to their peer band (employment_type × specialty × FTE band).

**Formula** (subject to refinement once Ventra data is real):

```python
def overall_rank_score(physician_id: int, month: date) -> float:
    """
    Score 0-100, higher is better.
    Quartile-based per peer band (W-2 hospitalist with similar FTE).
    """
    productivity = quartile_score(rvu_pct_of_peer_median(physician_id, month))
    revenue     = quartile_score(revenue_per_fte_pct_of_peer_median(physician_id, month))
    encounters  = quartile_score(encounters_per_day_pct_of_peer_median(physician_id, month))
    quality     = quartile_score(chart_turnaround_median_inverted(physician_id, month))

    # Weighted average — weights from comp agreement (RVU vs salaried different)
    weights = comp_model_weights(physician_id)
    return (
        weights.productivity * productivity +
        weights.revenue * revenue +
        weights.encounters * encounters +
        weights.quality * quality
    )
```

`quartile_score()` returns 25, 50, 75, or 100 based on the physician's quartile in their peer band. Avoids exposing raw rank position.

**Why quartile, not rank?** Quartiles abstract away specific peer-to-peer comparisons. An exec asking "is Dr. X above or below the median in their peer group?" is the answerable question. "Is Dr. X #3 out of 12?" is not — it invites the politics we're avoiding.

## Display

**Table layout** (default for Phase 1):

| Name | Type | Site | Comp | Status | RVU | Rev/FTE | Enc/day | Doc | Rank |
|---|---|---|---|---|---|---|---|---|---|

Sort by Rank (descending) by default. Color-code Rank: top quartile green, second yellow, third light-red, bottom red.

**Drill-through:** click a physician name → individual scorecard with 12-month trend per metric.

## API endpoints

| Endpoint | Use |
|---|---|
| `GET /api/v1/scorecards/list` | Full table |
| `GET /api/v1/scorecards/physician/{npi}` | Individual detail + trend |
| `GET /api/v1/scorecards/rank` | Just the rank composite |

All require `exec` role.

## Data freshness

| Source | Latency |
|---|---|
| Identity columns | Real-time |
| RVU Generated (Phase 1) | Whatever frequency Paycom manual entry happens (monthly) |
| Phase 2 metrics | Daily after Ventra ingest |
| Rank composite | Materialized nightly into `facts.scorecard_snapshot`; recomputed on Ventra ingest completion |

## RBAC

| Role | Access |
|---|---|
| `exec` | Full read |
| `admin` | **No access** (this is intentional — admins can read audit log but not scorecards) |
| `comp_viewer` | **No access** (comp_viewer is for comp_agreements visibility on People board, NOT scorecards) |
| All others | No access |

## Alerts

- **None.** Scorecards are an exec review tool, not an alerting trigger. Sensitive numbers should never auto-page anyone.

## Materialization

`facts.scorecard_snapshot` is materialized nightly by a job (or on-demand after Ventra ingest). This means:

- Listing /scorecards is fast (single table read)
- The Rank composite is consistent within a day (no race conditions)
- Recomputing the formula requires re-running the materialization job — controlled, not on every page load

## Phase 1 limitations

- Quality metrics (chart turnaround, doc score) show "—" with a tooltip
- Rank composite uses only productivity + identity dimensions (lower weights on quality)
- No drill-through to per-encounter detail (and never will, per HIPAA firewall)

## Privacy controls

- **Audit log every read** — `GET /api/v1/scorecards/list` logs `(actor_upn, occurred_at)` to a dedicated audit table
- **Watermark** the page with the viewer's UPN — discourages screenshots
- **No CSV export from the UI** — exec users who need data should request from Akhil
- **`/scorecards/raw-export` endpoint** does exist for admin debugging but requires both `admin` AND `exec` AND IP from HHA network (defense in depth)

## What we will NEVER do

- Show a physician their own rank
- Show physicians their peer ranks
- Email rank to physicians
- Publish in any non-exec context (board meetings: yes — written into the agenda. Hospital-wide town halls: no.)
- Compute "physician of the month" or any award based on this

## Open items

| Item | Owner | Status |
|---|---|---|
| Confirm Ventra attribution rule (rendering vs supervising) | Akhil (post-meeting) | Pending |
| Confirm Ventra can provide documentation timestamps | Akhil (post-meeting) | Pending |
| Lock the Overall Rank weights with sponsor sign-off | Akhil + CMO | Before Phase 2 launch |

---

**Next read:** [GLOSSARY.md](../GLOSSARY.md) — definitions of every term used.
