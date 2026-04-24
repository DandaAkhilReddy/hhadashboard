import { Badge } from "@/components/Badge";
import { Card, CardHeader } from "@/components/Card";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api-client";
import { num, pct } from "@/lib/format";

export default async function PeoplePage() {
  const [summary, byState] = await Promise.all([
    api.peopleSummary(),
    api.openPositionsBySite(),
  ]);

  return (
    <>
      <PageHeader
        title="People & Pipeline"
        subtitle="Headcount · Turnover · Open positions · Below-FMV"
      />

      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard label="Headcount · W-2" value={num(summary.headcount_w2)} sub="Salaried full-time" />
        <MetricCard label="Headcount · 1099" value={num(summary.headcount_1099)} sub="Per-diem + RVU" />
        <MetricCard
          label="Turnover 90d"
          value={pct(summary.turnover_90d_pct)}
          sub="Rolling · Paycom (P1+)"
        />
        <MetricCard
          label="Open Positions"
          value={num(summary.open_positions_total)}
          sub="Across 11 sites"
          tone="warn"
        />
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader title="Open positions by site" owner="Andrea Simon" />
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-500">
                <th className="py-2 font-semibold">Site</th>
                <th className="py-2 font-semibold">State</th>
                <th className="py-2 text-center font-semibold">Count</th>
              </tr>
            </thead>
            <tbody>
              {byState.map((p) => {
                const tone =
                  p.severity === "high"
                    ? "text-red-600"
                    : p.severity === "medium"
                      ? "text-amber-600"
                      : "text-emerald-600";
                return (
                  <tr key={p.site} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    <td className="py-2.5 font-semibold text-slate-900">{p.site}</td>
                    <td className="py-2.5 text-xs text-slate-500">{p.state}</td>
                    <td className={`py-2.5 text-center font-bold tabular-nums ${tone}`}>{p.count}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>

        <Card className="border-dashed">
          <div className="mb-3 flex items-center gap-2">
            <h2 className="text-base font-bold text-slate-900">Providers below FMV</h2>
            <Badge variant="gray">🔒 comp_viewer only</Badge>
          </div>
          <div className="mb-3 text-5xl font-bold text-red-600 tabular-nums">
            {summary.below_fmv_count}
          </div>
          <p className="mb-4 text-sm text-slate-600">
            Count derived from <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">comp_agreements.effective_comp</code>{" "}
            vs MGMA Internal Medicine hospitalist 50th percentile.
          </p>
          <button className="w-full rounded-md bg-slate-900 py-2 text-sm font-semibold text-white hover:bg-slate-800">
            View detail (CEO/CFO only)
          </button>
          <div className="mt-3 text-xs text-slate-500">
            Individual comp names hidden from non-comp_viewer roles. Audit log records every view.
          </div>
        </Card>
      </div>
    </>
  );
}
