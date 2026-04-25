import Link from "next/link";
import { notFound } from "next/navigation";
import { Badge } from "@/components/Badge";
import { Card, CardHeader } from "@/components/Card";
import { CensusTrendChart, buildTrendPoints } from "@/components/CensusTrendChart";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api-client";
import { dateShort, num, pct, signed, usd } from "@/lib/format";
import { SiteCensusForm } from "./SiteCensusForm";

export default async function SiteDetailPage({
  params,
}: {
  params: Promise<{ siteId: string }>;
}) {
  const { siteId: siteIdRaw } = await params;
  const siteId = Number.parseInt(siteIdRaw, 10);
  if (!Number.isFinite(siteId) || siteId <= 0) {
    notFound();
  }

  let site;
  try {
    site = await api.siteDetail(siteId);
  } catch {
    notFound();
  }

  const varianceTone =
    site.variance_pct < -15 ? "bad" : site.variance_pct < 0 ? "warn" : "good";
  const shiftsTone =
    site.open_shifts === 0 ? "good" : site.open_shifts >= 3 ? "bad" : "warn";

  const trendPoints = buildTrendPoints(
    site.recent_entries.map((e) => ({ entry_date: e.entry_date, census: e.census })),
  );

  return (
    <>
      <div className="mb-3 text-sm">
        <Link href="/operations" className="text-slate-500 hover:text-slate-900">
          ← Back to Operations Board
        </Link>
      </div>

      <PageHeader
        title={site.name}
        subtitle={
          <span className="flex items-center gap-2">
            <Badge variant={site.state === "FL" ? "blue" : "gray"}>{site.state}</Badge>
            {site.md_status === "VACANT" ? (
              <Badge variant="bad">MD VACANT ⚠</Badge>
            ) : site.md_status === "PIP" ? (
              <Badge variant="bad">PIP Active</Badge>
            ) : (
              <Badge variant="good">Active</Badge>
            )}
            {site.entered_today ? (
              <Badge variant="good">✓ Entered today</Badge>
            ) : (
              <Badge variant="gray">Not entered today</Badge>
            )}
          </span>
        }
      />

      {/* Top metric strip */}
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard
          label="Census today"
          value={num(site.census_today)}
          sub={
            <span className={varianceTone === "bad" ? "text-red-600" : "text-slate-500"}>
              {signed(site.census_today - site.census_3mo_avg)} vs 3-mo avg
            </span>
          }
          tone={varianceTone}
          accent
        />
        <MetricCard label="3-mo average" value={num(site.census_3mo_avg)} sub="baseline" />
        <MetricCard label="MTD avg" value={site.mtd_avg.toFixed(1)} sub={pct(site.variance_pct)} />
        <MetricCard
          label="Open shifts"
          value={num(site.open_shifts)}
          sub={site.open_shifts === 0 ? "fully covered" : "needs coverage"}
          tone={shiftsTone}
        />
      </div>

      {/* Site facts + trend */}
      <div className="mb-6 grid gap-6 md:grid-cols-[1fr_2fr]">
        <Card>
          <CardHeader title="Facility info" />
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-slate-500">Medical Director</dt>
            <dd className="font-medium text-slate-900">
              {site.medical_director ?? <span className="text-red-600">VACANT</span>}
            </dd>
            <dt className="text-slate-500">Liaison</dt>
            <dd className="text-slate-700">{site.liaison ?? "—"}</dd>
            <dt className="text-slate-500">Contract end</dt>
            <dd className="text-slate-700">{dateShort(site.contract_end)}</dd>
            <dt className="text-slate-500">Annual subsidy</dt>
            <dd className="font-semibold text-slate-900 tabular-nums">
              {usd(site.annual_subsidy_usd, true)}
            </dd>
          </dl>
        </Card>

        <Card>
          <CardHeader title="14-day census trend" owner={`Today highlighted · 3-mo avg ${site.census_3mo_avg}`} />
          <CensusTrendChart points={trendPoints} avg={site.census_3mo_avg} />
        </Card>
      </div>

      {/* Inline entry form */}
      <Card className="mb-6">
        <CardHeader
          title="Enter / update today's census"
          owner="Saves immediately · audited · upserts on (site, date)"
        />
        <SiteCensusForm
          siteId={site.id}
          initialCensus={site.census_today}
          initialOpenShifts={site.open_shifts}
          initialNotes={null}
        />
      </Card>

      {/* Recent entries history */}
      <Card>
        <CardHeader
          title="Recent entries"
          owner={`Last ${site.recent_entries.length} entries (read-only)`}
        />
        {site.recent_entries.length === 0 ? (
          <div className="text-sm text-slate-500 py-4">
            No entries yet for this site. Use the form above to enter today's census, or drop a
            census PDF on /uploads.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-500">
                  <th className="py-2 font-semibold">Date</th>
                  <th className="py-2 text-center font-semibold">Census</th>
                  <th className="py-2 text-center font-semibold">Open shifts</th>
                  <th className="py-2 font-semibold">Source</th>
                  <th className="py-2 font-semibold">Entered by</th>
                  <th className="py-2 font-semibold">Notes</th>
                </tr>
              </thead>
              <tbody>
                {site.recent_entries.map((e) => (
                  <tr key={e.entry_date} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    <td className="py-2.5 font-medium tabular-nums text-slate-900">
                      {dateShort(e.entry_date)}
                    </td>
                    <td className="py-2.5 text-center font-bold tabular-nums text-slate-900">
                      {e.census}
                    </td>
                    <td className="py-2.5 text-center tabular-nums text-slate-500">
                      {e.open_shifts}
                    </td>
                    <td className="py-2.5">
                      {e.source === "manual" ? (
                        <Badge variant="gray">Manual</Badge>
                      ) : (
                        <Badge variant="blue">PDF</Badge>
                      )}
                    </td>
                    <td className="py-2.5 text-xs text-slate-500 max-w-[180px] truncate">
                      {e.entered_by_upn}
                    </td>
                    <td className="py-2.5 text-xs text-slate-500 max-w-[260px] truncate" title={e.notes ?? ""}>
                      {e.notes ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
