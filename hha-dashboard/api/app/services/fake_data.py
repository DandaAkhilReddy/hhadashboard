"""Deterministic fake-data generators.

Until the real `entries` / `facts` schemas + ingestion jobs land (Sessions 3+, P2+),
every dashboard endpoint reads from here. The generators are **deterministic**
(seeded by date), so the same day's refresh shows consistent numbers across tabs.

When real data arrives, swap each `get_*` function body with a SQLAlchemy query
and the routers + Pydantic schemas don't change.

Numbers mirror the pain points in DASHBOARD_PLAN.md and UI_MOCKUP_v5.html:
FL collections below target, Westside vacant, Woodmont PIP, 61 below-FMV, etc.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ----- Deterministic helpers -----


def _seed(*parts: object) -> float:
    """Hash parts → float in [0, 1)."""
    key = "|".join(str(p) for p in parts).encode()
    h = hashlib.sha256(key).digest()
    return int.from_bytes(h[:8], "big") / (1 << 64)


def _noise(seed_key: tuple, amplitude: float) -> float:
    """Return a deterministic pseudo-random offset in [-amplitude, +amplitude]."""
    return (_seed(*seed_key) - 0.5) * 2 * amplitude


# ----- Site constants (matches the HTML + seed_sites.py) -----


@dataclass(frozen=True)
class SiteSpec:
    name: str
    state: Literal["FL", "TX"]
    avg_census: int
    mar_mtd: float
    contract_end: date
    subsidy_usd: int
    md_name: str | None
    md_status: str
    liaison: str | None


FL_SITES: tuple[SiteSpec, ...] = (
    SiteSpec("Westside Regional", "FL", 265, 204.6, date(2027, 12, 31), 2_061_326,
             None, "VACANT", "Farzana Choudhry"),
    SiteSpec("Woodmont Hospital", "FL", 169, 135.7, date(2027, 12, 31), 2_208_849,
             "Dr. Franklyn", "PIP", "Larissa Carvalho"),
    SiteSpec("JFK Main Med Ctr", "FL", 262, 202.5, date(2027, 8, 31), 3_024_261,
             "Dr. Susan Hanson", "ACTIVE", "Claudia Chirino"),
    SiteSpec("JFK North Med Ctr", "FL", 84, 88.9, date(2027, 8, 31), 1_131_138,
             "Dr. Dario Martinez", "ACTIVE", None),
    SiteSpec("Palms West Hospital", "FL", 202, 138.5, date(2027, 8, 31), 1_190_175,
             "Dr. Thomas Abraham", "ACTIVE", "Alexandra Oliva"),
    SiteSpec("University Hospital", "FL", 72, 54.0, date(2027, 12, 31), 1_055_488,
             "Dr. Ashkan Jafarbay", "ACTIVE", None),
    SiteSpec("Jackson Memorial", "FL", 126, 128.3, date(2027, 4, 4), 971_328,
             "Dr. Esam Khalifa", "ACTIVE", "Nemesis Nieves"),
)

TX_SITES: tuple[SiteSpec, ...] = (
    SiteSpec("Bay", "TX", 9, 9, date(2028, 12, 31), 0,
             "Dr. Manzoor Bevinal", "ACTIVE", None),
    SiteSpec("Doctors", "TX", 11, 11, date(2028, 12, 31), 0,
             "Dr. Manzoor Bevinal", "ACTIVE", None),
    SiteSpec("Huntsville", "TX", 6, 6, date(2028, 12, 31), 0,
             "Dr. Manzoor Bevinal", "ACTIVE", "Christina Perez"),
    SiteSpec("Corpus", "TX", 2, 2, date(2028, 12, 31), 0,
             None, "VACANT", "Sage Turner"),
)

ALL_SITES = FL_SITES + TX_SITES

FL_DAILY_TARGET = 147_727
TX_DAILY_TARGET = 22_500
FL_MTD_TARGET = 3_250_000


# ----- Operations -----


def _fake_site_row(s: SiteSpec, today: date) -> tuple[int, int]:
    """Deterministic (census, open_shifts) fallback when no DB entry exists."""
    if s.state == "FL":
        offset = _noise(("census", s.name, today.isoformat()), 0.15)
        census = round(s.avg_census * (1 + offset) * 0.85)  # bias slightly low
        # Hand-pinned per UI_MOCKUP_v5.html pain points
        if s.name == "Westside Regional":
            open_shifts = 3
        elif s.name == "Palms West Hospital":
            open_shifts = 2
        elif s.name in ("University Hospital", "Jackson Memorial"):
            open_shifts = 1
        else:
            open_shifts = 0
    else:
        census = s.avg_census + int(_noise(("census", s.name, today.isoformat()), 2))
        open_shifts = 0
    return census, open_shifts


def _build_site_row(s: SiteSpec, site_id: int, census: int, open_shifts: int) -> dict:
    """Compose a SiteToday-shaped dict from a SiteSpec + today's numbers."""
    variance_pct = ((census - s.avg_census) / s.avg_census * 100) if s.avg_census else 0
    return {
        "id": site_id,
        "name": s.name,
        "state": s.state,
        "medical_director": s.md_name,
        "md_status": s.md_status,
        "liaison": s.liaison,
        "census_today": census,
        "census_3mo_avg": s.avg_census,
        "mtd_avg": s.mar_mtd,
        "variance_pct": round(variance_pct, 1),
        "open_shifts": open_shifts,
        "contract_end": s.contract_end.isoformat(),
        "annual_subsidy_usd": s.subsidy_usd,
    }


async def get_sites_today(
    db: AsyncSession | None = None, today: date | None = None
) -> list[dict]:
    """Operations board row set for a given date.

    Prefers real manual/PDF entries from `entries.daily_entries` over the fake
    deterministic values. Sites with no entry for today fall back to fake.

    `db` is optional. When `db` is None, ids fall back to a deterministic
    1-based positional index (only matters for legacy non-DB paths).
    """
    today = today or date.today()

    # Pull today's real entries + real site ids
    name_to_id: dict[str, int] = {}
    by_site_name: dict[str, tuple[int, int]] = {}
    if db is not None:
        from ..models.entries import DailyEntry
        from ..models.masters import Site

        site_rows = (await db.execute(select(Site.id, Site.name))).all()
        for sid, name in site_rows:
            name_to_id[name] = sid

        stmt = (
            select(Site.name, DailyEntry.census, DailyEntry.open_shifts)
            .join(DailyEntry, DailyEntry.site_id == Site.id)
            .where(DailyEntry.entry_date == today)
        )
        result = await db.execute(stmt)
        for name, census, open_shifts in result.all():
            by_site_name[name] = (int(census), int(open_shifts or 0))

    rows = []
    for i, s in enumerate(ALL_SITES, start=1):
        if s.name in by_site_name:
            census, open_shifts = by_site_name[s.name]
        else:
            census, open_shifts = _fake_site_row(s, today)
        site_id = name_to_id.get(s.name, i)
        rows.append(_build_site_row(s, site_id, census, open_shifts))
    return rows


async def get_site_today(
    db: AsyncSession, site_id: int, today: date | None = None
) -> dict | None:
    """Single-site variant of `get_sites_today`. Returns None if no such site."""
    today = today or date.today()

    from ..models.entries import DailyEntry
    from ..models.masters import Site

    site = (await db.execute(select(Site).where(Site.id == site_id))).scalar_one_or_none()
    if site is None:
        return None

    spec = next((s for s in ALL_SITES if s.name == site.name), None)
    if spec is None:
        # Site exists in DB but has no SiteSpec (newly added site, not seeded into ALL_SITES).
        # Build a minimal spec on the fly to avoid a hard failure.
        spec = SiteSpec(
            name=site.name,
            state="FL" if site.state == "FL" else "TX",
            avg_census=0,
            mar_mtd=0.0,
            contract_end=date.today(),
            subsidy_usd=0,
            md_name=None,
            md_status="ACTIVE",
            liaison=None,
        )

    entry = (
        await db.execute(
            select(DailyEntry.census, DailyEntry.open_shifts).where(
                DailyEntry.site_id == site_id, DailyEntry.entry_date == today
            )
        )
    ).first()
    if entry is not None:
        census, open_shifts = int(entry[0]), int(entry[1] or 0)
    else:
        census, open_shifts = _fake_site_row(spec, today)

    return _build_site_row(spec, site.id, census, open_shifts)


async def get_operations_summary(
    db: AsyncSession | None = None, today: date | None = None
) -> dict:
    today = today or date.today()
    rows = await get_sites_today(db, today)
    fl = [r for r in rows if r["state"] == "FL"]
    tx = [r for r in rows if r["state"] == "TX"]
    total_fl_census = sum(r["census_today"] for r in fl)
    total_tx_census = sum(r["census_today"] for r in tx)
    total_fl_avg = sum(r["census_3mo_avg"] for r in fl)
    below_avg = sum(1 for r in fl if r["census_today"] < r["census_3mo_avg"])
    open_shifts_total = sum(r["open_shifts"] for r in rows)
    return {
        "total_fl_census": total_fl_census,
        "total_tx_census": total_tx_census,
        "total_fl_3mo_avg": total_fl_avg,
        "census_variance_vs_avg": total_fl_census - total_fl_avg,
        "sites_below_avg": below_avg,
        "open_shifts_total": open_shifts_total,
        "fl_site_count": len(fl),
        "tx_site_count": len(tx),
    }


# ----- Finance (FL-first; TX is manual-entry stub) -----


async def _latest_finance_by_state(
    db: AsyncSession, today: date
) -> dict[str, dict]:
    """Return {state: row_dict} for the most recent MonthlyFinanceManual entry
    per state, in or before the current month. Empty dict if no rows.
    """
    from ..models.entries_finance import MonthlyFinanceManual

    stmt = (
        select(MonthlyFinanceManual)
        .where(MonthlyFinanceManual.period_first <= today.replace(day=1))
        .order_by(MonthlyFinanceManual.period_first.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    out: dict[str, dict] = {}
    for r in rows:
        if r.state in out:
            continue  # we already have a newer row for this state
        out[r.state] = {
            "year": r.year,
            "month": r.month,
            "period_first": r.period_first,
            "collections_usd": float(r.collections_usd),
            "ventra_fee_usd": float(r.ventra_fee_usd),
            "ar_total_usd": float(r.ar_total_usd),
            "ar_buckets": {
                "0-30": float(r.ar_0_30_usd),
                "31-60": float(r.ar_31_60_usd),
                "61-90": float(r.ar_61_90_usd),
                "91-120": float(r.ar_91_120_usd),
                ">120": float(r.ar_over_120_usd),
            },
            "ncr_pct": float(r.net_collection_rate_pct),
            "days_in_ar": float(r.days_in_ar),
            "source_system": r.source_system,
        }
    return out


async def get_finance_today(
    db: AsyncSession | None = None, today: date | None = None
) -> dict:
    """Daily collections + MTD totals.

    Daily numbers stay deterministic-fake (we don't capture daily entries).
    MTD totals prefer the most-recent monthly entry when one exists for the
    current month — that's Sandy's authoritative figure for the period.
    """
    today = today or date.today()

    # Deterministic daily slice (no manual daily entry exists)
    fl_today = int(FL_DAILY_TARGET * (0.65 + 0.15 * _seed("fl-coll", today.isoformat())))
    tx_today = int(TX_DAILY_TARGET * (1.05 + 0.15 * _seed("tx-coll", today.isoformat())))

    # MTD fallback (synthetic)
    day_of_month = today.day
    expected_mtd = FL_MTD_TARGET * (day_of_month / 30)
    fl_mtd = int(expected_mtd * (0.65 + 0.1 * _seed("fl-mtd", today.isoformat())))
    ventra_fee_mtd = round(fl_mtd * 0.05)
    fl_source = "VENTRA_FL_FALLBACK"

    # Prefer real entry for the current month if it exists
    if db is not None:
        latest = await _latest_finance_by_state(db, today)
        fl = latest.get("FL")
        if fl and fl["year"] == today.year and fl["month"] == today.month:
            fl_mtd = int(fl["collections_usd"])
            ventra_fee_mtd = int(fl["ventra_fee_usd"])
            fl_source = fl["source_system"]

    return {
        "fl_daily_actual": fl_today,
        "fl_daily_target": FL_DAILY_TARGET,
        "fl_daily_delta": fl_today - FL_DAILY_TARGET,
        "fl_source_system": fl_source,
        "tx_daily_actual": tx_today,
        "tx_daily_target": TX_DAILY_TARGET,
        "tx_daily_delta": tx_today - TX_DAILY_TARGET,
        "tx_source_system": "HHA_TX_MANUAL",
        "fl_mtd_actual": fl_mtd,
        "fl_mtd_target": FL_MTD_TARGET,
        "fl_mtd_pct": round(fl_mtd / FL_MTD_TARGET * 100, 1),
        "ventra_fee_mtd": ventra_fee_mtd,
    }


def _fake_ar(today: date) -> dict:
    fl_total = 5_600_000 + int(_noise(("ar-fl", today.isoformat()), 200_000))
    fl_buckets = {
        "0-30": int(fl_total * 0.28),
        "31-60": int(fl_total * 0.20),
        "61-90": int(fl_total * 0.14),
        "91-120": int(fl_total * 0.13),
        ">120": int(fl_total * 0.25),
    }
    tx_total = 1_240_000 + int(_noise(("ar-tx", today.isoformat()), 50_000))
    tx_buckets = {
        "0-30": int(tx_total * 0.30),
        "31-60": int(tx_total * 0.19),
        "61-90": int(tx_total * 0.13),
        "91-120": int(tx_total * 0.10),
        ">120": int(tx_total * 0.28),
    }
    return {
        "fl_total_usd": fl_total,
        "fl_buckets": fl_buckets,
        "tx_total_usd": tx_total,
        "tx_buckets": tx_buckets,
    }


async def get_ar_aging(
    db: AsyncSession | None = None, today: date | None = None
) -> dict:
    """5-bucket AR aging by state. Prefers DB row when present (per state)."""
    today = today or date.today()
    fake = _fake_ar(today)
    fl_total = fake["fl_total_usd"]
    fl_buckets = fake["fl_buckets"]
    tx_total = fake["tx_total_usd"]
    tx_buckets = fake["tx_buckets"]
    fl_source = "VENTRA_FL_FALLBACK"
    tx_source = "HHA_TX_MANUAL"

    if db is not None:
        latest = await _latest_finance_by_state(db, today)
        if "FL" in latest:
            fl_total = int(latest["FL"]["ar_total_usd"])
            fl_buckets = {k: int(v) for k, v in latest["FL"]["ar_buckets"].items()}
            fl_source = latest["FL"]["source_system"]
        if "TX" in latest:
            tx_total = int(latest["TX"]["ar_total_usd"])
            tx_buckets = {k: int(v) for k, v in latest["TX"]["ar_buckets"].items()}
            tx_source = latest["TX"]["source_system"]

    return {
        "fl_total_usd": fl_total,
        "fl_buckets": fl_buckets,
        "fl_over_120_pct": round(fl_buckets[">120"] / fl_total * 100, 1) if fl_total else 0,
        "fl_source_system": fl_source,
        "tx_total_usd": tx_total,
        "tx_buckets": tx_buckets,
        "tx_over_120_pct": round(tx_buckets[">120"] / tx_total * 100, 1) if tx_total else 0,
        "tx_source_system": tx_source,
    }


async def get_finance_kpis(
    db: AsyncSession | None = None, today: date | None = None
) -> dict:
    """Days-in-AR + NCR per state. Prefers DB when entry exists."""
    today = today or date.today()
    fl_days_in_ar = 39.9
    tx_days_in_ar = 32.3
    fl_ncr = 43
    tx_ncr = 36

    if db is not None:
        latest = await _latest_finance_by_state(db, today)
        if "FL" in latest:
            fl_days_in_ar = round(latest["FL"]["days_in_ar"], 1)
            fl_ncr = round(latest["FL"]["ncr_pct"], 1)
        if "TX" in latest:
            tx_days_in_ar = round(latest["TX"]["days_in_ar"], 1)
            tx_ncr = round(latest["TX"]["ncr_pct"], 1)

    return {
        "fl_days_in_ar": fl_days_in_ar,
        "tx_days_in_ar": tx_days_in_ar,
        "days_in_ar_target": 45,
        "fl_ncr_pct": fl_ncr,
        "tx_ncr_pct": tx_ncr,
        "ncr_billed_at": "200% Medicare",
    }


def get_monthly_revenue_trend() -> list[dict]:
    """12 months of FL monthly revenue — realistic-looking trend."""
    today = date.today()
    months = []
    for i in range(11, -1, -1):
        # Walk back i months
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1
        label = f"{date(year, month, 1):%b %Y}"
        # Base $3M, with seasonal bump in winter + some noise
        season = [0.95, 0.92, 0.98, 1.00, 1.05, 1.02, 0.98, 0.94, 0.96, 1.01, 1.08, 1.10][month - 1]
        base = 3_100_000
        usd = int(base * season * (1 + _noise(("rev", year, month), 0.06)))
        months.append({"month": label, "revenue_usd": usd})
    # Current month: show partial (pain point)
    months[-1]["revenue_usd"] = 2_280_000
    return months


# ----- Clinical -----


async def _latest_clinical_by_state(
    db: AsyncSession, today: date
) -> dict[str, dict]:
    """Return {state: row_dict} for the most recent WeeklyClinical entry per state
    (week_ending on or before today). Empty dict if no rows.
    """
    from ..models.entries_clinical import WeeklyClinical

    stmt = (
        select(WeeklyClinical)
        .where(WeeklyClinical.week_ending <= today)
        .order_by(WeeklyClinical.week_ending.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    out: dict[str, dict] = {}
    for r in rows:
        if r.state in out:
            continue
        out[r.state] = {
            "week_ending": r.week_ending,
            "hp_24h_pct": float(r.hp_24h_pct),
            "dc_48h_pct": float(r.dc_48h_pct),
            "avg_los_days": float(r.avg_los_days),
            "charts_audited_count": r.charts_audited_count,
            "notes": r.notes,
        }
    return out


async def get_clinical_summary(
    db: AsyncSession | None = None, today: date | None = None
) -> dict:
    """Clinical board metrics. Prefers most-recent WeeklyClinical row per state."""
    today = today or date.today()

    # Defaults — synthetic. Both states' H&P / DC averaged for the headline tiles.
    fl_hp = round(94 + _seed("hp-fl", today.isoformat()) * 3, 1)
    fl_dc = round(85 + _seed("dc-fl", today.isoformat()) * 5, 1)
    tx_hp = round(94 + _seed("hp-tx", today.isoformat()) * 3, 1)
    tx_dc = round(85 + _seed("dc-tx", today.isoformat()) * 5, 1)
    los_fl_days: float = 4.2
    los_tx_days: float = 3.9

    if db is not None:
        latest = await _latest_clinical_by_state(db, today)
        if "FL" in latest:
            fl_hp = round(latest["FL"]["hp_24h_pct"], 1)
            fl_dc = round(latest["FL"]["dc_48h_pct"], 1)
            los_fl_days = round(latest["FL"]["avg_los_days"], 2)
        if "TX" in latest:
            tx_hp = round(latest["TX"]["hp_24h_pct"], 1)
            tx_dc = round(latest["TX"]["dc_48h_pct"], 1)
            los_tx_days = round(latest["TX"]["avg_los_days"], 2)

    # Headline tiles average across states (same shape as before)
    hp_pct = round((fl_hp + tx_hp) / 2, 1)
    dc_pct = round((fl_dc + tx_dc) / 2, 1)

    return {
        "hp_24h_pct": hp_pct,
        "hp_24h_target": 95,
        "dc_48h_pct": dc_pct,
        "dc_48h_target": 90,
        "los_fl_days": los_fl_days,
        "los_tx_days": los_tx_days,
        "los_woodmont_watch_days": 5.8,
        "los_woodmont_trend_days": 0.4,  # up over 4 weeks
        "credentials_expiring_30d": 4,
        "credentials_expiring_60d": 3,
        "credentials_expiring_90d": 4,
    }


def get_credentials_expiring() -> list[dict]:
    """Demo list matching the mockup — 4 within 30 days."""
    today = date.today()
    return [
        {"physician": "Dr. Franklyn",  "type": "DEA",              "expires_in_days": 12,
         "expires_on": (today + timedelta(days=12)).isoformat(), "tier": "urgent"},
        {"physician": "Dr. Abraham",   "type": "FL State License", "expires_in_days": 18,
         "expires_on": (today + timedelta(days=18)).isoformat(), "tier": "urgent"},
        {"physician": "Dr. Khalifa",   "type": "Board Cert",       "expires_in_days": 22,
         "expires_on": (today + timedelta(days=22)).isoformat(), "tier": "urgent"},
        {"physician": "Dr. Hanson",    "type": "JFK Privileges",   "expires_in_days": 29,
         "expires_on": (today + timedelta(days=29)).isoformat(), "tier": "urgent"},
        {"physician": "Dr. Martinez",  "type": "DEA",              "expires_in_days": 45,
         "expires_on": (today + timedelta(days=45)).isoformat(), "tier": "warning"},
        {"physician": "Dr. Jafarbay",  "type": "FL State License", "expires_in_days": 52,
         "expires_on": (today + timedelta(days=52)).isoformat(), "tier": "warning"},
        {"physician": "Dr. Bevinal",   "type": "TX State License", "expires_in_days": 58,
         "expires_on": (today + timedelta(days=58)).isoformat(), "tier": "warning"},
    ]


# ----- People & Pipeline -----


async def get_people_summary(
    db: AsyncSession | None = None, today: date | None = None
) -> dict:
    """People board headline tiles. Prefers most-recent WeeklyHrManual row."""
    today = today or date.today()

    # Defaults — synthetic, matching the HTML mockup
    headcount_w2 = 48
    headcount_1099 = 23
    open_positions_total = 12
    terminations_90d = 6
    below_fmv = 61

    if db is not None:
        from ..models.entries_hr import WeeklyHrManual

        stmt = (
            select(WeeklyHrManual)
            .where(WeeklyHrManual.week_ending <= today)
            .order_by(WeeklyHrManual.week_ending.desc())
            .limit(1)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is not None:
            headcount_w2 = row.headcount_w2
            headcount_1099 = row.headcount_1099
            open_positions_total = row.open_positions_total
            terminations_90d = row.terminations_90d_count
            below_fmv = row.below_fmv_count

    headcount_total = headcount_w2 + headcount_1099
    turnover_90d_pct = (
        round(terminations_90d / headcount_total * 100, 1) if headcount_total else 0.0
    )

    return {
        "headcount_w2": headcount_w2,
        "headcount_1099": headcount_1099,
        "headcount_total": headcount_total,
        "open_positions_total": open_positions_total,
        "turnover_90d_pct": turnover_90d_pct,
        "below_fmv_count": below_fmv,
    }


def get_open_positions_by_site() -> list[dict]:
    return [
        {"site": "Westside Regional",  "state": "FL", "count": 3, "severity": "high"},
        {"site": "Palms West Hospital", "state": "FL", "count": 2, "severity": "medium"},
        {"site": "Jackson Memorial",   "state": "FL", "count": 1, "severity": "low"},
        {"site": "University Hospital", "state": "FL", "count": 1, "severity": "low"},
        {"site": "Corpus",             "state": "TX", "count": 2, "severity": "high"},
        {"site": "Huntsville",         "state": "TX", "count": 1, "severity": "low"},
        {"site": "Other / unassigned", "state": "—",  "count": 2, "severity": "low"},
    ]


# ----- Doctor Scorecards (exec-only) -----


@dataclass(frozen=True)
class MDSpec:
    """Demo physician used by the Scorecards page until real comp_agreements
    land in the DB. `effective_comp_usd` here drives the MGMA-band math in
    services/comp.py — change a value to see the band shift."""

    name: str
    site: str
    state: str
    employment_type: Literal["W2", "1099"]
    comp_model: Literal["SALARY", "PER_DIEM", "RVU", "HYBRID"]
    status: str
    rank: int
    rvu_90d: int
    effective_comp_usd: int


# Effective comp values are illustrative — they bracket the MGMA IM
# Hospitalist 25/50/75/90 percentile lines so each band is represented.
SCORECARD_MDS: tuple[MDSpec, ...] = (
    MDSpec("Dr. Susan Hanson",    "JFK Main Med Ctr",    "FL", "W2",   "SALARY",   "ACTIVE", 2,  1247, 410_000),
    MDSpec("Dr. Thomas Abraham",  "Palms West Hospital", "FL", "1099", "PER_DIEM", "ACTIVE", 5,  1102, 360_000),
    MDSpec("Dr. Esam Khalifa",    "Jackson Memorial",    "FL", "1099", "RVU",      "ACTIVE", 7,  1038, 340_000),
    MDSpec("Dr. Dario Martinez",  "JFK North Med Ctr",   "FL", "W2",   "HYBRID",   "ACTIVE", 12, 892,  255_000),
    MDSpec("Dr. Ashkan Jafarbay", "University Hospital", "FL", "W2",   "SALARY",   "ACTIVE", 18, 768,  295_000),
    MDSpec("Dr. Manzoor Bevinal", "Bay / Doctors / Huntsville", "TX", "1099", "PER_DIEM", "ACTIVE", 22, 710, 305_000),
    MDSpec("Dr. Franklyn",        "Woodmont Hospital",   "FL", "W2",   "SALARY",   "PIP",    47, 641,  240_000),
)


def get_scorecards(*, include_comp_detail: bool = False) -> list[dict]:
    """Return the scorecard rows.

    Args:
        include_comp_detail: When True (caller has comp_viewer), include
            dollar-amount fields. Otherwise comp $ is redacted to None and
            the UI shows only the qualitative MGMA band.
    """
    # Local import to avoid a circular: services.comp ↔ services.fake_data
    from .comp import (
        MGMA_SOURCE_NOTE,
        compute_mgma_band,
        is_below_fmv,
        mgma_benchmark_50th_usd,
    )

    rows: list[dict] = []
    p50 = mgma_benchmark_50th_usd()
    for i, md in enumerate(SCORECARD_MDS):
        rows.append({
            "physician_id": i + 1,
            "name": md.name,
            "site": md.site,
            "state": md.state,
            "employment_type": md.employment_type,
            "comp_model": md.comp_model,
            "status": md.status,
            "rank": md.rank,
            "rvu_90d": md.rvu_90d,
            "below_fmv": is_below_fmv(md.effective_comp_usd),
            "mgma_band": compute_mgma_band(md.effective_comp_usd),
            "mgma_p50_usd": p50,
            "effective_comp_usd": md.effective_comp_usd if include_comp_detail else None,
            "fmv_source_note": MGMA_SOURCE_NOTE if include_comp_detail else None,
            # P2+ tiles — null until Athena lands
            "revenue_per_fte_usd": None,
            "encounters_per_day": None,
            "documentation_score_pct": None,
            "chart_turnaround_days": None,
        })
    return rows


# ----- Alerts -----


def get_current_alerts(today: date | None = None) -> list[dict]:
    """Hardcoded fallback alerts. Used by `routers/alerts.py` only when the
    real `services.alert_engine.compute_alerts_for_date` returns empty
    (genuine quiet day OR pre-seed environment). Numbers below are
    illustrative — real values come from the engine when entries land."""
    _ = today  # accepted for API compat with the engine signature
    return [
        {
            "id": "fl-collections-below-target",
            "severity": "red",
            "category": "finance",
            "title": "FL collections below target",
            "detail": (
                f"Demo: shortfall against ${FL_DAILY_TARGET:,}/day target "
                f"(real number lands once engine ingests last month's finance)"
            ),
            "owner": "Sandy Collins · Maribel Reyes",
        },
        {
            "id": "westside-md-vacant",
            "severity": "yellow",
            "category": "operations",
            "title": "Site coverage flag",
            "detail": "Westside Regional has no Medical Director · Woodmont PIP active",
            "owner": "Crystal Anderson",
        },
        {
            "id": "credentials-urgent",
            "severity": "yellow",
            "category": "clinical",
            "title": "Credentials expiring",
            "detail": "4 credentials expire in <30 days · 11 in <90 days",
            "owner": "Crystal Anderson",
        },
    ]


# ----- Meta / refresh -----


def get_meta() -> dict:
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "data_source": "fake_data_service",
        "note": (
            "All numbers are deterministic fake data for Session 1 dashboard build-out. "
            "Replace with Postgres-backed endpoints once entries/facts schemas land (Session 3+) "
            "and real ingestion jobs are wired (Paycom P1, Ventra FL P2)."
        ),
    }
