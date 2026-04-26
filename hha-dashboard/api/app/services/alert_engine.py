"""Alert engine — pure functions that compute today's variance flags from DB rows.

Reads from `entries.monthly_finance_manual`, `entries.weekly_clinical`,
`entries.weekly_hr_manual`, and `entries.daily_entries` to surface variance
flags. Returns a typed list of `AlertCandidate` — does NOT persist or send.
The cron jobs (alert_digest, cred_scan) decide what to do with the result.

Thresholds are hard-coded in v1. Per-site / per-org overrides are deferred
until ops requests it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entries_clinical import WeeklyClinical
from app.models.entries_finance import MonthlyFinanceManual
from app.models.entries_hr import WeeklyHrManual

Severity = Literal["red", "yellow", "blue"]
Category = Literal["finance", "operations", "clinical", "people"]


@dataclass(frozen=True)
class AlertCandidate:
    """One variance flag.

    `id` is a stable string key — same logical alert always uses the same id
    so the cron's idempotency check (alert_log lookup on `(id, target_date)`)
    works correctly.
    """

    id: str
    severity: Severity
    category: Category
    title: str
    detail: str
    owner: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "detail": self.detail,
            "owner": self.owner,
        }


# -- Thresholds ---------------------------------------------------------------

FL_MONTHLY_COLLECTIONS_TARGET_USD = Decimal("2_500_000")
TX_MONTHLY_COLLECTIONS_TARGET_USD = Decimal("800_000")
AR_OVER_120_PCT_THRESHOLD = Decimal("20")  # over-120 buckets above 20% of total = flag
NCR_FLOOR_PCT = Decimal("90")  # NCR below 90% is a flag
HP_24H_FLOOR_PCT = Decimal("90")
DC_48H_FLOOR_PCT = Decimal("90")
LOS_CEILING_DAYS = Decimal("5.0")
BELOW_FMV_COUNT_THRESHOLD = 5
OPEN_POSITIONS_THRESHOLD = 8


# -- Engine -------------------------------------------------------------------


async def compute_alerts_for_date(
    db: AsyncSession, target_date: date | None = None
) -> list[AlertCandidate]:
    """Compute alerts as of `target_date` (default: today UTC).

    Pure read — never writes. Returns an empty list when there's no data to
    evaluate (e.g., empty DB). Caller decides whether to fall back to fakes
    or skip the digest entirely.
    """
    target = target_date or datetime.now(UTC).date()

    alerts: list[AlertCandidate] = []
    alerts.extend(await _finance_alerts(db, target))
    alerts.extend(await _clinical_alerts(db, target))
    alerts.extend(await _hr_alerts(db, target))
    return alerts


async def _finance_alerts(
    db: AsyncSession, target: date
) -> list[AlertCandidate]:
    """Most-recent-month rows for each state. Flags collections-vs-target,
    AR over-120 share, and net collection rate floor."""
    rows = (
        await db.execute(
            select(MonthlyFinanceManual)
            .where(MonthlyFinanceManual.period_first <= target)
            .order_by(desc(MonthlyFinanceManual.period_first))
            .limit(8)
        )
    ).scalars().all()

    if not rows:
        return []

    # Take the most recent (year, month) pair across all states.
    latest_year = rows[0].year
    latest_month = rows[0].month
    latest_rows = [r for r in rows if r.year == latest_year and r.month == latest_month]

    alerts: list[AlertCandidate] = []
    for row in latest_rows:
        target_collections = (
            FL_MONTHLY_COLLECTIONS_TARGET_USD
            if row.state == "FL"
            else TX_MONTHLY_COLLECTIONS_TARGET_USD
        )
        if row.collections_usd < target_collections:
            shortfall = target_collections - row.collections_usd
            alerts.append(
                AlertCandidate(
                    id=f"{row.state.lower()}-collections-below-target-{row.year}-{row.month:02d}",
                    severity="red",
                    category="finance",
                    title=f"{row.state} collections below target",
                    detail=(
                        f"{row.year}-{row.month:02d}: ${row.collections_usd:,.0f} "
                        f"vs ${target_collections:,.0f} target — "
                        f"shortfall ${shortfall:,.0f}"
                    ),
                    owner="Sandy Collins · Maribel Reyes",
                )
            )

        if row.ar_total_usd and row.ar_total_usd > 0:
            over_120_pct = (row.ar_over_120_usd / row.ar_total_usd) * Decimal("100")
            if over_120_pct > AR_OVER_120_PCT_THRESHOLD:
                alerts.append(
                    AlertCandidate(
                        id=f"{row.state.lower()}-ar-over-120-{row.year}-{row.month:02d}",
                        severity="yellow",
                        category="finance",
                        title=f"{row.state} AR over 120 days elevated",
                        detail=(
                            f"{over_120_pct:.1f}% of AR is over 120 days "
                            f"(${row.ar_over_120_usd:,.0f} / ${row.ar_total_usd:,.0f}) — "
                            f"threshold {AR_OVER_120_PCT_THRESHOLD}%"
                        ),
                        owner="Sandy Collins · Maribel Reyes",
                    )
                )

        if row.net_collection_rate_pct < NCR_FLOOR_PCT:
            alerts.append(
                AlertCandidate(
                    id=f"{row.state.lower()}-ncr-below-floor-{row.year}-{row.month:02d}",
                    severity="yellow",
                    category="finance",
                    title=f"{row.state} net collection rate below floor",
                    detail=(
                        f"NCR {row.net_collection_rate_pct}% < floor {NCR_FLOOR_PCT}%"
                    ),
                    owner="Sandy Collins · Maribel Reyes",
                )
            )
    return alerts


async def _clinical_alerts(
    db: AsyncSession, target: date
) -> list[AlertCandidate]:
    """Most recent weekly_clinical row per state. Flags H&P/DC compliance
    floors and LOS ceiling."""
    rows = (
        await db.execute(
            select(WeeklyClinical)
            .where(WeeklyClinical.week_ending <= target)
            .order_by(desc(WeeklyClinical.week_ending))
            .limit(4)
        )
    ).scalars().all()

    if not rows:
        return []

    latest_week = rows[0].week_ending
    latest_rows = [r for r in rows if r.week_ending == latest_week]

    alerts: list[AlertCandidate] = []
    for row in latest_rows:
        if row.hp_24h_pct < HP_24H_FLOOR_PCT:
            alerts.append(
                AlertCandidate(
                    id=f"{row.state.lower()}-hp24h-below-floor-{row.week_ending}",
                    severity="yellow",
                    category="clinical",
                    title=f"{row.state} H&P-within-24h below target",
                    detail=(
                        f"Week ending {row.week_ending}: {row.hp_24h_pct}% "
                        f"vs floor {HP_24H_FLOOR_PCT}%"
                    ),
                    owner="Dr. Aneja · Dr. Reddy",
                )
            )
        if row.dc_48h_pct < DC_48H_FLOOR_PCT:
            alerts.append(
                AlertCandidate(
                    id=f"{row.state.lower()}-dc48h-below-floor-{row.week_ending}",
                    severity="yellow",
                    category="clinical",
                    title=f"{row.state} DC-within-48h below target",
                    detail=(
                        f"Week ending {row.week_ending}: {row.dc_48h_pct}% "
                        f"vs floor {DC_48H_FLOOR_PCT}%"
                    ),
                    owner="Dr. Aneja · Dr. Reddy",
                )
            )
        if row.avg_los_days > LOS_CEILING_DAYS:
            alerts.append(
                AlertCandidate(
                    id=f"{row.state.lower()}-los-above-ceiling-{row.week_ending}",
                    severity="yellow",
                    category="clinical",
                    title=f"{row.state} LOS above ceiling",
                    detail=(
                        f"Week ending {row.week_ending}: {row.avg_los_days} days "
                        f"vs ceiling {LOS_CEILING_DAYS}"
                    ),
                    owner="Dr. Aneja · Dr. Reddy",
                )
            )
    return alerts


async def _hr_alerts(
    db: AsyncSession, target: date
) -> list[AlertCandidate]:
    """Most recent weekly_hr_manual row. Flags below-FMV cluster and high
    open-positions count."""
    row = (
        await db.execute(
            select(WeeklyHrManual)
            .where(WeeklyHrManual.week_ending <= target)
            .order_by(desc(WeeklyHrManual.week_ending))
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return []

    alerts: list[AlertCandidate] = []
    if row.below_fmv_count >= BELOW_FMV_COUNT_THRESHOLD:
        alerts.append(
            AlertCandidate(
                id=f"below-fmv-cluster-{row.week_ending}",
                severity="yellow",
                category="people",
                title="Physicians paid below FMV",
                detail=(
                    f"{row.below_fmv_count} physicians below FMV "
                    f"as of week ending {row.week_ending}"
                ),
                owner="Andrea Davis",
            )
        )
    if row.open_positions_total >= OPEN_POSITIONS_THRESHOLD:
        alerts.append(
            AlertCandidate(
                id=f"open-positions-elevated-{row.week_ending}",
                severity="yellow",
                category="people",
                title="Open positions elevated",
                detail=(
                    f"{row.open_positions_total} open positions "
                    f"as of week ending {row.week_ending}"
                ),
                owner="Andrea Davis",
            )
        )
    return alerts


__all__ = [
    "AR_OVER_120_PCT_THRESHOLD",
    "BELOW_FMV_COUNT_THRESHOLD",
    "DC_48H_FLOOR_PCT",
    "FL_MONTHLY_COLLECTIONS_TARGET_USD",
    "HP_24H_FLOOR_PCT",
    "LOS_CEILING_DAYS",
    "NCR_FLOOR_PCT",
    "OPEN_POSITIONS_THRESHOLD",
    "TX_MONTHLY_COLLECTIONS_TARGET_USD",
    "AlertCandidate",
    "compute_alerts_for_date",
]
