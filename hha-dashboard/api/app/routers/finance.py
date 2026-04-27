from typing import Any

from fastapi import APIRouter

from ..deps import DBDep, UserDep
from ..schemas.finance import ArAging, ArBuckets, FinanceKpis, FinanceToday, MonthRevenue
from ..services import fake_data

router = APIRouter(prefix="/api/v1/finance", tags=["finance"])


@router.get("/today", response_model=FinanceToday)
async def finance_today(db: DBDep, user: UserDep) -> dict[str, Any]:
    _ = user
    return await fake_data.get_finance_today(db)


def _buckets_to_schema(buckets: dict) -> ArBuckets:
    return ArBuckets(
        bucket_0_30=buckets["0-30"],
        bucket_31_60=buckets["31-60"],
        bucket_61_90=buckets["61-90"],
        bucket_91_120=buckets["91-120"],
        bucket_over_120=buckets[">120"],
    )


@router.get("/ar-aging", response_model=ArAging)
async def ar_aging(db: DBDep, user: UserDep) -> ArAging:
    _ = user
    raw = await fake_data.get_ar_aging(db)
    return ArAging(
        fl_total_usd=raw["fl_total_usd"],
        fl_buckets=_buckets_to_schema(raw["fl_buckets"]),
        fl_over_120_pct=raw["fl_over_120_pct"],
        fl_source_system=raw["fl_source_system"],
        tx_total_usd=raw["tx_total_usd"],
        tx_buckets=_buckets_to_schema(raw["tx_buckets"]),
        tx_over_120_pct=raw["tx_over_120_pct"],
        tx_source_system=raw["tx_source_system"],
    )


@router.get("/kpis", response_model=FinanceKpis)
async def finance_kpis(db: DBDep, user: UserDep) -> dict[str, Any]:
    _ = user
    return await fake_data.get_finance_kpis(db)


@router.get("/monthly-trend", response_model=list[MonthRevenue])
async def monthly_trend(user: UserDep) -> list[dict[str, Any]]:
    _ = user
    return fake_data.get_monthly_revenue_trend()
