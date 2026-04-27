import { SourceTag } from "@/components/Badge";
import { Card, CardHeader } from "@/components/Card";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { type ArBuckets, api } from "@/lib/api-client";
import { pct, usd } from "@/lib/format";

const BUCKET_LABELS: Array<[keyof ArBuckets, string]> = [
  ["bucket_0_30", "0-30"],
  ["bucket_31_60", "31-60"],
  ["bucket_61_90", "61-90"],
  ["bucket_91_120", "91-120"],
  ["bucket_over_120", ">120"],
];
const BUCKET_COLORS = [
  "bg-emerald-500",
  "bg-emerald-400",
  "bg-amber-400",
  "bg-amber-500",
  "bg-red-500",
];
const BUCKET_HEIGHTS_PX = [64, 48, 36, 28, 56];

export default async function FinancePage() {
  const [today, aging, kpis, trend] = await Promise.all([
    api.financeToday(),
    api.arAging(),
    api.financeKpis(),
    api.monthlyTrend(),
  ]);

  const trendMax = Math.max(...trend.map((m) => m.revenue_usd));

  return (
    <>
      <PageHeader
        title="Finance · HHA Top-Line"
        subtitle={
          <>
            Revenue in + AR aging · <strong>No denial analytics — Ventra&apos;s scope</strong>
          </>
        }
      />

      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard
          label="FL Daily Collections"
          value={usd(today.fl_daily_actual)}
          source={<SourceTag source={today.fl_source_system} />}
          sub={
            <span className="flex items-center gap-1 font-semibold text-red-600">
              ▼ {usd(Math.abs(today.fl_daily_delta))} below {usd(today.fl_daily_target, true)}
            </span>
          }
          tone="bad"
        />
        <MetricCard
          label="TX Daily Collections"
          value={usd(today.tx_daily_actual)}
          source={<SourceTag source={today.tx_source_system} />}
          sub={
            <span className="font-semibold text-emerald-600">
              ▲ {usd(Math.abs(today.tx_daily_delta))} above {usd(today.tx_daily_target, true)}
            </span>
          }
          tone="good"
        />
        <MetricCard
          label="FL MTD"
          value={usd(today.fl_mtd_actual, true)}
          source={<SourceTag source={today.fl_source_system} />}
          sub={`vs ${usd(today.fl_mtd_target, true)} target · ${pct(today.fl_mtd_pct)}`}
          tone="warn"
        />
        <MetricCard
          label="Ventra Fee (5%)"
          value={usd(today.ventra_fee_mtd, true)}
          source={<SourceTag source={today.fl_source_system} />}
          sub="MTD · auto-computed from FL collections"
        />
      </div>

      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="AR Aging — 5-bucket by state"
            owner="Maribel Reyes"
            right={<SourceTag source={aging.fl_source_system} />}
          />

          <BucketChart
            label="FLORIDA"
            buckets={aging.fl_buckets}
            over120Pct={aging.fl_over_120_pct}
          />
          <div className="mt-4 flex items-center gap-2">
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
              TEXAS
            </span>
            <SourceTag source={aging.tx_source_system} />
          </div>
          <BucketChart
            label=""
            buckets={aging.tx_buckets}
            over120Pct={aging.tx_over_120_pct}
            compact
          />
        </Card>

        <Card>
          <CardHeader title="Top-line Finance Metrics" />
          <Row
            label="Days in A/R — Florida"
            sub={`Target <${kpis.days_in_ar_target}`}
            source={<SourceTag source={today.fl_source_system} />}
            tone="good"
          >
            {kpis.fl_days_in_ar}
          </Row>
          <Row
            label="Days in A/R — Texas"
            sub={`Target <${kpis.days_in_ar_target}`}
            source={<SourceTag source={today.tx_source_system} />}
            tone="good"
          >
            {kpis.tx_days_in_ar}
          </Row>
          <Row
            label="Net Collection Rate — FL"
            sub={kpis.ncr_billed_at}
            source={<SourceTag source={today.fl_source_system} />}
            tone="warn"
          >
            {pct(kpis.fl_ncr_pct, 0)}
          </Row>
          <Row
            label="Net Collection Rate — TX"
            sub={kpis.ncr_billed_at}
            source={<SourceTag source={today.tx_source_system} />}
            tone="warn"
          >
            {pct(kpis.tx_ncr_pct, 0)}
          </Row>
          <div className="mt-5">
            <div className="mb-2 flex items-center justify-between">
              <div className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
                Monthly revenue trend · 12 months
              </div>
              <div className="flex items-center gap-1.5 text-[10px] text-slate-500">
                <SourceTag source={today.fl_source_system} />
                <SourceTag source={today.tx_source_system} />
              </div>
            </div>
            <div className="flex items-end gap-1" style={{ height: 80 }}>
              {trend.map((m) => {
                const h = Math.max(4, Math.round((m.revenue_usd / trendMax) * 72));
                const isCurrent = m === trend[trend.length - 1];
                return (
                  <div
                    key={m.month}
                    className="flex-1 text-center"
                    title={`${m.month}: ${usd(m.revenue_usd)}`}
                  >
                    <div
                      className={`mx-auto rounded ${isCurrent ? "bg-red-500" : "bg-indigo-500"}`}
                      style={{ height: `${h}px` }}
                    />
                  </div>
                );
              })}
            </div>
            <div className="mt-2 flex justify-between text-[10px] text-slate-400">
              <span>{trend[0]?.month}</span>
              <span>{trend[trend.length - 1]?.month} (MTD)</span>
            </div>
            <div className="mt-1 text-[10px] italic text-slate-400">
              HHA-wide (FL + TX). Provenance per source above. Combined for trend visualization;
              each state still tagged at the row level upstream.
            </div>
          </div>
        </Card>
      </div>

      <Card className="bg-slate-50">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-slate-200 text-xs text-slate-700">
            i
          </div>
          <div className="text-sm text-slate-600">
            <strong>Denial analytics are out of scope.</strong> HHA contracted the full RCM cycle to
            Ventra. Claim-level data, denial categories, appeals workflow, coding accuracy, timely
            filing, charge lag, clean claim rate — all live in Ventra&apos;s portal. This dashboard
            only surfaces HHA&apos;s top-line: money coming in, AR owed.
          </div>
        </div>
      </Card>
    </>
  );
}

function BucketChart({
  label,
  buckets,
  over120Pct,
  compact,
}: {
  label: string;
  buckets: ArBuckets;
  over120Pct: number;
  compact?: boolean;
}) {
  return (
    <div>
      {label ? (
        <div className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">
          {label}
        </div>
      ) : null}
      <div className="grid grid-cols-5 gap-1.5">
        {BUCKET_LABELS.map(([key, human], i) => (
          <div key={key} className="text-center">
            <div className="mb-1 text-[10px] text-slate-500">{human}</div>
            <div
              className={`${BUCKET_COLORS[i]} rounded`}
              style={{ height: `${compact ? BUCKET_HEIGHTS_PX[i] - 8 : BUCKET_HEIGHTS_PX[i]}px` }}
            />
            <div className="mt-1 text-[10px] font-bold tabular-nums">{usd(buckets[key], true)}</div>
          </div>
        ))}
      </div>
      <div className="mt-2 text-xs text-slate-500">
        &gt;120d = <span className="font-bold text-red-600">{pct(over120Pct)}</span> · target
        &lt;15%
      </div>
    </div>
  );
}

function Row({
  label,
  sub,
  source,
  tone,
  children,
}: {
  label: string;
  sub: string;
  source?: React.ReactNode;
  tone: "good" | "warn" | "bad";
  children: React.ReactNode;
}) {
  const toneClass = { good: "text-emerald-600", warn: "text-amber-600", bad: "text-red-600" }[tone];
  return (
    <div className="flex items-center justify-between border-b border-slate-100 py-2.5 last:border-0">
      <div>
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-slate-700">{label}</span>
          {source}
        </div>
        <div className="text-[11px] text-slate-500">{sub}</div>
      </div>
      <div className={`text-2xl font-bold tabular-nums ${toneClass}`}>{children}</div>
    </div>
  );
}
