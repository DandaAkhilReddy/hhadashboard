# Clinical Quality Board — Product Spec

> **Tile-by-tile spec.** What the Clinical Quality board shows, source, formulas, refresh cadence, RBAC.
>
> Audience: product owners + developers.
>
> Status: **Phase 1 manual entry; Phase 2 adds Ventra-sourced documentation metrics.** Last updated 2026-05-11.

## What is this board

Clinical operational quality (NOT clinical care decisions). Answers:

- Are H&Ps and discharges being documented on time?
- What's our average length of stay, and is any site (especially Woodmont) drifting?
- Are any provider credentials about to expire?

This is a **process-quality** dashboard, not a clinical-outcomes one. Out-of-scope: patient satisfaction, HCAHPS, infections, readmissions.

## URL + access

- **URL:** `/clinical`
- **Required role:** `exec` OR `owner_clinical`

## Tiles

### H&P within 24h compliance

**What it shows:** Percent of admitted patients whose H&P (History & Physical) was signed within 24 hours of admission.

**Formula:** `COUNT(*) WHERE hp_signed_at <= admission_at + 24h / COUNT(*)`

**Source:**

- Phase 1: monthly manual entry by Dr. Aneja (numerator + denominator per site per month)
- Phase 2: Ventra's documentation timestamps (if provided — see [INGESTION_VENTRA.md](../INGESTION_VENTRA.md) § provisional fields)

**Display:** Per-site bar chart + state averages. Color: green ≥ 95%, yellow 85-95%, red < 85%.

### Discharge summary within 48h

**What it shows:** Percent of discharges whose discharge summary was signed within 48 hours.

**Formula + source:** Same pattern as H&P, with `dc_signed_at` and `discharge_at`.

### Average LOS by state

**What it shows:** Average Length of Stay in days, per state, last 30 days rolling.

**Formula:** `AVG(discharge_date - admission_date)`.

**Source:**

- Phase 1: monthly manual entry
- Phase 2: derived from Ventra's `Invoice.DischargeDate` minus admission

**Display:** Number with one decimal. Trend sparkline (12 months).

### Woodmont LOS watch

**What it shows:** Dedicated tile for the Woodmont site (per ops history, has run high LOS). Shows current LOS, 3-month average, and variance.

**Source:** Same as state LOS but filtered to Woodmont.

**Display:** Larger tile. Red border if current > 110% of 3-mo avg. Drill-through to per-month Woodmont LOS trend.

### Credentials expiring 30/60/90 days

**What it shows:** Count of physician credentials expiring within each window.

**Source:** `entries.credentials_expiring` (manual entry, Andrea owns).

**Formula:**

```sql
SELECT
  SUM(CASE WHEN expiry_date BETWEEN now() AND now() + 30 days THEN 1 ELSE 0 END) AS exp_30,
  SUM(CASE WHEN expiry_date BETWEEN now() + 30 days AND now() + 60 days THEN 1 ELSE 0 END) AS exp_60,
  SUM(CASE WHEN expiry_date BETWEEN now() + 60 days AND now() + 90 days THEN 1 ELSE 0 END) AS exp_90
FROM entries.credentials_expiring;
```

**Display:** Three count tiles (30 / 60 / 90). Color:

- 30: red if > 0
- 60: yellow if > 0
- 90: black

Drill-through to per-physician list.

## API endpoints

| Endpoint | Tile |
|---|---|
| `GET /api/v1/clinical/hp-compliance` | H&P |
| `GET /api/v1/clinical/dc-compliance` | DC summary |
| `GET /api/v1/clinical/los` | LOS by state + Woodmont |
| `GET /api/v1/clinical/credentials/expiring` | Credentials |

## Data freshness

| Tile | Latency |
|---|---|
| H&P / DC (Phase 1) | Monthly when Aneja enters |
| H&P / DC (Phase 2, if Ventra provides) | Daily |
| LOS | Same as above |
| Credentials | Whenever Andrea updates; manual |

## RBAC

| Role | Access |
|---|---|
| `exec`, `owner_clinical`, `admin` | Full read |
| Others | No access |

## Alerts

- **Credential expiring within 30 days** → daily digest to owner_clinical + exec
- **H&P compliance < 90% for any site** → monthly digest
- **Woodmont LOS > 110% of 3-mo avg for 2 weeks** → weekly digest

## Phase 2+ enhancements

| Item | Phase |
|---|---|
| Per-physician compliance breakout | Phase 2 (with Ventra data) |
| Real-time documentation timestamps | Phase 2 if Ventra provides; else Phase 4 with direct Athena |
| Trend overlays per metric | Phase 3 |

---

**Next read:** [boards/PEOPLE.md](PEOPLE.md)
