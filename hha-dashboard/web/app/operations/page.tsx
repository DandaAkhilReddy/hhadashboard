import { Badge } from "@/components/Badge";
import { Card, CardHeader } from "@/components/Card";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api-client";
import { dateShort, num, pct, signed, usd } from "@/lib/format";
import Link from "next/link";

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
          <div className="flex items-center gap-3">
            <span className="text-[11px] text-slate-500">
              {summary.facilities_reported > 0
                ? `${summary.facilities_reported} of ${summary.facilities_reported + summary.facilities_missing} reported · last update ${
                    summary.last_updated_at
                      ? new Date(summary.last_updated_at).toLocaleTimeString(undefined, {
                          hour: "numeric",
                          minute: "2-digit",
                        })
                      : "—"
                  }`
                : "No census submitted yet today"}
            </span>
            <Link
              href="/daily-census"
              className="rounded-md bg-slate-900 px-3.5 py-2 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-slate-800"
            >
              + Enter Today&apos;s Data
            </Link>
          </div>
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
        <CardHeader
          title="Florida Sites — Daily Detail"
          owner="Crystal Anderson · owner_ops"
          right={
            <Badge variant="blue" dot>
              {fl.length} sites
            </Badge>
          }
        />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr className="text-left text-[10.5px] uppercase tracking-wider text-slate-500">
                <th className="rounded-l-md px-3 py-2.5 font-semibold">Site</th>
                <th className="px-3 py-2.5 font-semibold">Medical Director</th>
                <th className="px-3 py-2.5 font-semibold">Liaison</th>
                <th className="px-3 py-2.5 text-center font-semibold">Census</th>
                <th className="px-3 py-2.5 text-center font-semibold">3-Mo</th>
                <th className="px-3 py-2.5 text-center font-semibold">MTD</th>
                <th className="px-3 py-2.5 text-center font-semibold">Var</th>
                <th className="px-3 py-2.5 text-center font-semibold">Open Shifts</th>
                <th className="px-3 py-2.5 font-semibold">Contract Thru</th>
                <th className="px-3 py-2.5 font-semibold">Subsidy</th>
                <th className="rounded-r-md px-3 py-2.5 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {fl.map((s) => {
                // Phase 1: variance/open_shifts can be null. The frontend renders
                // "—" everywhere a null arrives; tone classes fall back to neutral.
                const tone =
                  s.variance_pct === null
                    ? "text-slate-400"
                    : s.variance_pct < -15
                      ? "text-red-600"
                      : s.variance_pct < 0
                        ? "text-amber-600"
                        : "text-emerald-600";
                const shiftsTone =
                  s.open_shifts === null
                    ? "text-slate-400"
                    : s.open_shifts === 0
                      ? "text-emerald-600"
                      : s.open_shifts >= 3
                        ? "text-red-600"
                        : "text-amber-600";
                return (
                  <tr key={s.name} className="group transition-colors hover:bg-indigo-50/40">
                    <td className="px-3 py-3 font-semibold text-slate-900">
                      <Link
                        href={`/operations/${s.id}`}
                        className="inline-flex items-center gap-1 transition-colors hover:text-indigo-600"
                      >
                        {s.name}
                        <span className="opacity-0 transition-opacity group-hover:opacity-60">
                          →
                        </span>
                      </Link>
                    </td>
                    <td className="px-3 py-3 text-xs">
                      {s.medical_director ? (
                        <span className="text-slate-700">
                          {s.medical_director}
                          {s.md_status === "PIP" ? (
                            <span className="ml-1 font-semibold text-red-600">(PIP)</span>
                          ) : null}
                        </span>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-xs text-slate-500">{s.liaison ?? "—"}</td>
                    <td
                      className={`px-3 py-3 text-center text-base font-bold tabular-nums ${tone}`}
                    >
                      {s.census_today ?? "—"}
                    </td>
                    <td className="px-3 py-3 text-center tabular-nums text-slate-500">
                      {s.census_3mo_avg ?? "—"}
                    </td>
                    <td className="px-3 py-3 text-center tabular-nums text-slate-400">
                      {s.mtd_avg === null ? "—" : s.mtd_avg.toFixed(1)}
                    </td>
                    <td className={`px-3 py-3 text-center font-semibold tabular-nums ${tone}`}>
                      {s.variance_pct === null ? "—" : pct(s.variance_pct)}
                    </td>
                    <td className={`px-3 py-3 text-center font-bold tabular-nums ${shiftsTone}`}>
                      {s.open_shifts ?? "—"}
                    </td>
                    <td className="px-3 py-3 text-xs text-slate-500 tabular-nums">
                      {s.contract_end ? dateShort(s.contract_end) : "—"}
                    </td>
                    <td className="px-3 py-3 text-xs font-semibold text-slate-600 tabular-nums">
                      {usd(s.annual_subsidy_usd, true)}
                    </td>
                    <td className="px-3 py-3">
                      {s.md_status === null ? (
                        <span className="text-slate-400">—</span>
                      ) : s.md_status === "VACANT" ? (
                        <Badge variant="bad" dot>
                          VACANT
                        </Badge>
                      ) : s.md_status === "PIP" ? (
                        <Badge variant="warn" dot>
                          PIP
                        </Badge>
                      ) : (
                        <Badge variant="good" dot>
                          Active
                        </Badge>
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
        <CardHeader
          title="Texas Sites"
          owner="Dr. Veena Reddy · owner_clinical"
          right={
            <Badge variant="blue" dot>
              {tx.length} sites
            </Badge>
          }
        />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr className="text-left text-[10.5px] uppercase tracking-wider text-slate-500">
                <th className="rounded-l-md px-3 py-2.5 font-semibold">Site</th>
                <th className="px-3 py-2.5 font-semibold">Medical Director</th>
                <th className="px-3 py-2.5 font-semibold">Liaison</th>
                <th className="px-3 py-2.5 text-center font-semibold">Census</th>
                <th className="rounded-r-md px-3 py-2.5 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tx.map((s) => (
                <tr key={s.name} className="group transition-colors hover:bg-indigo-50/40">
                  <td className="px-3 py-3 font-semibold text-slate-900">
                    <Link
                      href={`/operations/${s.id}`}
                      className="inline-flex items-center gap-1 transition-colors hover:text-indigo-600"
                    >
                      {s.name}
                      <span className="opacity-0 transition-opacity group-hover:opacity-60">→</span>
                    </Link>
                  </td>
                  <td className="px-3 py-3 text-xs text-slate-700">
                    {s.medical_director ?? <span className="text-slate-400">—</span>}
                  </td>
                  <td className="px-3 py-3 text-xs text-slate-500">{s.liaison ?? "—"}</td>
                  <td className="px-3 py-3 text-center text-base font-bold tabular-nums">
                    {s.census_today ?? "—"}
                  </td>
                  <td className="px-3 py-3">
                    {s.md_status === null ? (
                      <span className="text-slate-400">—</span>
                    ) : s.md_status === "VACANT" ? (
                      <Badge variant="gray" dot>
                        No MD
                      </Badge>
                    ) : (
                      <Badge variant="good" dot>
                        Active
                      </Badge>
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
