import Link from "next/link";
import { Badge } from "@/components/Badge";
import { Card, CardHeader } from "@/components/Card";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api-client";
import { dateShort, num, pct, signed, usd } from "@/lib/format";

export default async function OperationsPage() {
  const [summary, sites] = await Promise.all([api.operationsSummary(), api.sitesToday()]);
  const fl = sites.filter((s) => s.state === "FL");
  const tx = sites.filter((s) => s.state === "TX");

  return (
    <>
      <PageHeader
        title="Operations Board"
        subtitle="11 sites · FL (7) + TX (4) · Daily census, coverage, contracts"
        right={
          <>
            <button className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">
              Export CSV
            </button>
            <button className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800">
              + Enter Today&apos;s Data
            </button>
          </>
        }
      />

      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard
          label="Total FL Census"
          value={num(summary.total_fl_census)}
          sub={
            <span className="font-semibold text-red-600">
              {signed(summary.census_variance_vs_avg)} vs 3-mo avg
            </span>
          }
          tone="bad"
        />
        <MetricCard
          label="Total TX Census"
          value={num(summary.total_tx_census)}
          sub={`${summary.tx_site_count} sites`}
          tone="neutral"
        />
        <MetricCard
          label="Open Shifts (all sites)"
          value={num(summary.open_shifts_total)}
          sub="most at Westside"
          tone={summary.open_shifts_total > 5 ? "warn" : "neutral"}
        />
        <MetricCard
          label="Sites below 3-mo avg"
          value={num(summary.sites_below_avg)}
          sub={`of ${summary.fl_site_count} FL sites`}
          tone="bad"
        />
      </div>

      <Card className="mb-6">
        <CardHeader title="Florida Sites — Daily Detail" owner="Crystal Anderson" />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-500">
                <th className="py-2 font-semibold">Site</th>
                <th className="py-2 font-semibold">Medical Director</th>
                <th className="py-2 font-semibold">Liaison</th>
                <th className="py-2 text-center font-semibold">Census</th>
                <th className="py-2 text-center font-semibold">3-Mo</th>
                <th className="py-2 text-center font-semibold">MTD</th>
                <th className="py-2 text-center font-semibold">Var</th>
                <th className="py-2 text-center font-semibold">Open Shifts</th>
                <th className="py-2 font-semibold">Contract Thru</th>
                <th className="py-2 font-semibold">Subsidy</th>
                <th className="py-2 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {fl.map((s) => {
                const tone =
                  s.variance_pct < -15
                    ? "text-red-600"
                    : s.variance_pct < 0
                      ? "text-amber-600"
                      : "text-emerald-600";
                const shiftsTone =
                  s.open_shifts === 0
                    ? "text-emerald-600"
                    : s.open_shifts >= 3
                      ? "text-red-600"
                      : "text-amber-600";
                return (
                  <tr key={s.name} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    <td className="py-2.5 font-semibold text-slate-900">
                      <Link href={`/operations/${s.id}`} className="hover:text-indigo-600 hover:underline">
                        {s.name}
                      </Link>
                    </td>
                    <td className="py-2.5 text-xs">
                      {s.medical_director ? (
                        <span className="text-slate-700">
                          {s.medical_director}
                          {s.md_status === "PIP" ? (
                            <span className="ml-1 text-red-600">(PIP)</span>
                          ) : null}
                        </span>
                      ) : (
                        <span className="font-semibold text-red-600">VACANT</span>
                      )}
                    </td>
                    <td className="py-2.5 text-xs text-slate-500">{s.liaison ?? "—"}</td>
                    <td className={`py-2.5 text-center font-bold tabular-nums ${tone}`}>{s.census_today}</td>
                    <td className="py-2.5 text-center tabular-nums text-slate-500">{s.census_3mo_avg}</td>
                    <td className="py-2.5 text-center tabular-nums text-slate-400">{s.mtd_avg.toFixed(1)}</td>
                    <td className={`py-2.5 text-center tabular-nums ${tone}`}>{pct(s.variance_pct)}</td>
                    <td className={`py-2.5 text-center font-bold tabular-nums ${shiftsTone}`}>{s.open_shifts}</td>
                    <td className="py-2.5 text-xs text-slate-500">{dateShort(s.contract_end)}</td>
                    <td className="py-2.5 text-xs text-slate-500">{usd(s.annual_subsidy_usd, true)}</td>
                    <td className="py-2.5">
                      {s.md_status === "VACANT" ? (
                        <Badge variant="bad">VACANT ⚠</Badge>
                      ) : s.md_status === "PIP" ? (
                        <Badge variant="bad">PIP Active</Badge>
                      ) : (
                        <Badge variant="good">Active</Badge>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <CardHeader title="Texas Sites" owner="Dr. Veena Reddy" />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-500">
                <th className="py-2 font-semibold">Site</th>
                <th className="py-2 font-semibold">Medical Director</th>
                <th className="py-2 font-semibold">Liaison</th>
                <th className="py-2 text-center font-semibold">Census</th>
                <th className="py-2 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {tx.map((s) => (
                <tr key={s.name} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                  <td className="py-2.5 font-semibold text-slate-900">
                    <Link href={`/operations/${s.id}`} className="hover:text-indigo-600 hover:underline">
                      {s.name}
                    </Link>
                  </td>
                  <td className="py-2.5 text-xs text-slate-700">
                    {s.medical_director ?? <span className="text-slate-400">—</span>}
                  </td>
                  <td className="py-2.5 text-xs text-slate-500">{s.liaison ?? "—"}</td>
                  <td className="py-2.5 text-center font-bold tabular-nums">{s.census_today}</td>
                  <td className="py-2.5">
                    {s.md_status === "VACANT" ? (
                      <Badge variant="gray">No MD</Badge>
                    ) : (
                      <Badge variant="blue">Active</Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
