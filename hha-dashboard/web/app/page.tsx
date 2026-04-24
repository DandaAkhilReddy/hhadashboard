import { AlertBanner } from "@/components/AlertBanner";
import { Badge, SourceTag } from "@/components/Badge";
import { Card, CardHeader } from "@/components/Card";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api-client";
import { dateFull, num, pct, signed, usd } from "@/lib/format";

export default async function OverviewPage() {
  const [ops, fin, ar, clin, people, alerts, sites] = await Promise.all([
    api.operationsSummary(),
    api.financeToday(),
    api.arAging(),
    api.clinicalSummary(),
    api.peopleSummary(),
    api.alerts(),
    api.sitesToday(),
  ]);

  const fl = sites.filter((s) => s.state === "FL");

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle={`${dateFull()} · all 4 boards at a glance · refreshed 6 AM ET`}
        right={
          <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-800">
            ● API live
          </span>
        }
      />

      <AlertBanner alerts={alerts} />

      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard
          label="Total FL Census Today"
          value={num(ops.total_fl_census)}
          sub={<span className="text-red-600 font-semibold">{signed(ops.census_variance_vs_avg)} vs 3-mo avg</span>}
          tone={ops.census_variance_vs_avg < 0 ? "bad" : "good"}
        />
        <MetricCard
          label="FL MTD Collections"
          value={usd(fin.fl_mtd_actual, true)}
          sub={`${pct(fin.fl_mtd_pct)} of $${(fin.fl_mtd_target / 1_000_000).toFixed(2)}M target`}
          tone="bad"
        />
        <MetricCard
          label="Open Positions"
          value={num(people.open_positions_total)}
          sub="across 11 sites"
          tone="warn"
        />
        <MetricCard
          label="Active Alerts"
          value={num(alerts.length)}
          sub="urgent attention needed"
          tone={alerts.some((a) => a.severity === "red") ? "bad" : "warn"}
        />
      </div>

      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Operations · Today's Census"
            owner="Crystal Anderson"
            right={<Badge variant="blue">Board 1</Badge>}
          />
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
                <th className="pb-2 font-semibold">Site</th>
                <th className="pb-2 text-right font-semibold">Census</th>
                <th className="pb-2 text-right font-semibold">3-Mo</th>
                <th className="pb-2 text-right font-semibold">Var</th>
              </tr>
            </thead>
            <tbody>
              {fl.map((s) => {
                const tone =
                  s.variance_pct < -15 ? "text-red-600" : s.variance_pct < 0 ? "text-amber-600" : "text-emerald-600";
                return (
                  <tr key={s.name} className="border-t border-slate-100">
                    <td className="py-2 font-semibold text-slate-800">{s.name}</td>
                    <td className={`py-2 text-right font-bold tabular-nums ${tone}`}>{s.census_today}</td>
                    <td className="py-2 text-right tabular-nums text-slate-500">{s.census_3mo_avg}</td>
                    <td className={`py-2 text-right tabular-nums ${tone}`}>{pct(s.variance_pct)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>

        <Card>
          <CardHeader
            title="Finance · Collections vs Target"
            owner="Sandy Collins · Maribel Reyes"
            right={<Badge variant="blue">Board 2</Badge>}
          />
          <div className="space-y-3">
            <ProgressRow
              label="FL Daily"
              actual={fin.fl_daily_actual}
              target={fin.fl_daily_target}
              source={fin.fl_source_system}
            />
            <ProgressRow
              label="TX Daily"
              actual={fin.tx_daily_actual}
              target={fin.tx_daily_target}
              source={fin.tx_source_system}
            />
            <ProgressRow
              label="FL MTD"
              actual={fin.fl_mtd_actual}
              target={fin.fl_mtd_target}
              source={fin.fl_source_system}
              compact
            />
          </div>

          <div className="mt-5 border-t border-slate-100 pt-4">
            <div className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">
              AR aging — FL top-band
            </div>
            <div className="flex items-end gap-1.5">
              {[
                { label: "0-30", value: ar.fl_buckets.bucket_0_30, color: "bg-emerald-500", h: 64 },
                { label: "31-60", value: ar.fl_buckets.bucket_31_60, color: "bg-emerald-400", h: 48 },
                { label: "61-90", value: ar.fl_buckets.bucket_61_90, color: "bg-amber-400", h: 36 },
                { label: "91-120", value: ar.fl_buckets.bucket_91_120, color: "bg-amber-500", h: 28 },
                { label: ">120", value: ar.fl_buckets.bucket_over_120, color: "bg-red-500", h: 56 },
              ].map((b) => (
                <div key={b.label} className="flex-1 text-center">
                  <div className="mb-1 text-[10px] text-slate-500">{b.label}</div>
                  <div className={`${b.color} rounded`} style={{ height: `${b.h}px` }} />
                  <div className="mt-1 text-[10px] font-bold tabular-nums">{usd(b.value, true)}</div>
                </div>
              ))}
            </div>
            <div className="mt-2 text-xs text-slate-500">
              FL &gt;120d <span className="font-bold text-red-600">{pct(ar.fl_over_120_pct)}</span> ·
              TX &gt;120d <span className="font-bold text-red-600">{pct(ar.tx_over_120_pct)}</span> ·
              target &lt;15%
            </div>
          </div>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Clinical Quality" owner="Dr. Aneja · Dr. Reddy" right={<Badge variant="blue">Board 3</Badge>} />
          <Row label="H&P within 24h" target={`Target ≥${clin.hp_24h_target}%`}>
            <span className={clin.hp_24h_pct >= clin.hp_24h_target ? "text-emerald-600" : "text-amber-600"}>
              {pct(clin.hp_24h_pct)}
            </span>
          </Row>
          <Row label="DC Summary within 48h" target={`Target ≥${clin.dc_48h_target}%`}>
            <span className={clin.dc_48h_pct >= clin.dc_48h_target ? "text-emerald-600" : "text-amber-600"}>
              {pct(clin.dc_48h_pct)}
            </span>
          </Row>
          <Row label="Avg LOS · FL" target={`Woodmont watch: ${clin.los_woodmont_watch_days}d`}>
            <span>{clin.los_fl_days}d</span>
          </Row>
          <Row label="Credentials expiring <30d" target="Crystal to action">
            <span className={clin.credentials_expiring_30d > 0 ? "text-red-600" : "text-emerald-600"}>
              {clin.credentials_expiring_30d}
            </span>
          </Row>
        </Card>

        <Card>
          <CardHeader title="People & Pipeline" owner="Andrea Simon" right={<Badge variant="blue">Board 4</Badge>} />
          <div className="grid grid-cols-2 gap-3">
            <MiniStat label="W-2" value={people.headcount_w2} />
            <MiniStat label="1099" value={people.headcount_1099} />
            <MiniStat label="Open Positions" value={people.open_positions_total} tone="warn" />
            <MiniStat label="Turnover 90d" value={pct(people.turnover_90d_pct)} />
          </div>
          <div className="mt-4 border-t border-slate-100 pt-3">
            <Row
              label="Providers below FMV"
              target={
                <>
                  Visible only to <strong>comp_viewer</strong> (CEO, CFO)
                </>
              }
            >
              <span className="text-red-600">{people.below_fmv_count}</span>
            </Row>
          </div>
        </Card>
      </div>

      <footer className="mt-10 flex items-center justify-between border-t border-slate-200 pt-4 text-[11px] text-slate-400">
        <span>
          Server component · fetched 7 endpoints from FastAPI · fake_data deterministic by date
        </span>
        <span>Real Paycom (P1) + Ventra FL (P2) ingestion replaces fake_data when live.</span>
      </footer>
    </>
  );
}

/* ---------------- small bits ---------------- */

function ProgressRow({
  label,
  actual,
  target,
  source,
  compact,
}: {
  label: string;
  actual: number;
  target: number;
  source: string;
  compact?: boolean;
}) {
  const pctOf = Math.min(100, Math.round((actual / target) * 100));
  const tone = pctOf >= 100 ? "bg-emerald-500" : pctOf >= 90 ? "bg-amber-500" : "bg-red-500";
  const textTone = pctOf >= 100 ? "text-emerald-700" : pctOf >= 90 ? "text-amber-700" : "text-red-700";
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="flex items-center gap-2">
          <span className="font-medium text-slate-700">{label}</span>
          <SourceTag source={source} />
        </span>
        <span className={`font-bold tabular-nums ${textTone}`}>
          {compact ? `${usd(actual, true)} / ${usd(target, true)}` : `${usd(actual)} / ${usd(target)}`}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full ${tone}`} style={{ width: `${pctOf}%` }} />
      </div>
    </div>
  );
}

function Row({
  label,
  target,
  children,
}: {
  label: string;
  target: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between border-b border-slate-100 py-2.5 last:border-0">
      <div>
        <div className="text-sm text-slate-700">{label}</div>
        <div className="mt-0.5 text-[11px] text-slate-500">{target}</div>
      </div>
      <div className="text-xl font-bold tabular-nums">{children}</div>
    </div>
  );
}

function MiniStat({ label, value, tone }: { label: string; value: number | string; tone?: "warn" }) {
  return (
    <div>
      <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-0.5 text-2xl font-bold tabular-nums ${tone === "warn" ? "text-amber-600" : ""}`}>{value}</div>
    </div>
  );
}
