import { Card, CardHeader } from "@/components/Card";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api-client";
import { dateShort, num, pct } from "@/lib/format";

export default async function ClinicalPage() {
  const [summary, expiring] = await Promise.all([
    api.clinicalSummary(),
    api.credentialsExpiring(),
  ]);

  const urgent = expiring.filter((c) => c.tier === "urgent");
  const warning = expiring.filter((c) => c.tier === "warning");

  return (
    <>
      <PageHeader
        title="Clinical Quality"
        subtitle="Documentation timeliness · LOS · Credential lifecycle"
      />

      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard
          label="H&P within 24h"
          value={pct(summary.hp_24h_pct)}
          sub={`Target ≥${summary.hp_24h_target}% · weekly audit`}
          tone={summary.hp_24h_pct >= summary.hp_24h_target ? "good" : "warn"}
        />
        <MetricCard
          label="DC Summary within 48h"
          value={pct(summary.dc_48h_pct)}
          sub={`Target ≥${summary.dc_48h_target}% · 3 sites below`}
          tone={summary.dc_48h_pct >= summary.dc_48h_target ? "good" : "warn"}
        />
        <MetricCard
          label="Avg LOS · FL"
          value={`${summary.los_fl_days}d`}
          sub={
            <span className="text-amber-600">
              Woodmont: {summary.los_woodmont_watch_days}d (watch)
            </span>
          }
        />
        <MetricCard
          label="Avg LOS · TX"
          value={`${summary.los_tx_days}d`}
          sub="Within range"
        />
      </div>

      <div className="mb-6 grid gap-6 md:grid-cols-3">
        <Card className="border-red-200">
          <div className="mb-3 text-[11px] font-bold uppercase tracking-wider text-red-600">
            Credentials expiring &lt;30 days
          </div>
          <div className="mb-3 text-4xl font-bold text-red-600 tabular-nums">
            {summary.credentials_expiring_30d}
          </div>
          <ul className="space-y-2 text-sm">
            {urgent.map((c) => (
              <li key={`${c.physician}-${c.type}`} className="flex justify-between">
                <span>
                  <span className="font-medium text-slate-800">{c.physician}</span>
                  <span className="text-slate-500"> · {c.type}</span>
                </span>
                <span className="text-slate-500">{c.expires_in_days} days</span>
              </li>
            ))}
          </ul>
          <button className="mt-4 w-full rounded-md bg-slate-900 py-2 text-xs font-semibold text-white hover:bg-slate-800">
            Email Crystal now
          </button>
        </Card>

        <Card className="border-amber-200">
          <div className="mb-3 text-[11px] font-bold uppercase tracking-wider text-amber-600">
            Expiring 30-60 days
          </div>
          <div className="mb-3 text-4xl font-bold text-amber-600 tabular-nums">
            {summary.credentials_expiring_60d}
          </div>
          <ul className="space-y-2 text-sm text-slate-700">
            {warning.slice(0, 3).map((c) => (
              <li key={`${c.physician}-${c.type}`} className="flex justify-between">
                <span className="truncate">{c.physician}</span>
                <span className="text-slate-500">{dateShort(c.expires_on)}</span>
              </li>
            ))}
          </ul>
          <div className="mt-3 text-xs text-slate-500">Routine renewal window · auto-email weekly</div>
        </Card>

        <Card>
          <div className="mb-3 text-[11px] font-bold uppercase tracking-wider text-slate-600">
            Expiring 60-90 days
          </div>
          <div className="mb-3 text-4xl font-bold text-slate-900 tabular-nums">
            {summary.credentials_expiring_90d}
          </div>
          <div className="text-sm text-slate-600">Heads-up queue · no action yet</div>
        </Card>
      </div>

      <Card className="border-amber-200 bg-amber-50">
        <CardHeader title="Woodmont LOS Watch" />
        <div className="grid gap-4 text-sm md:grid-cols-3">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-amber-800">
              Current LOS
            </div>
            <div className="mt-1 text-2xl font-bold text-amber-900 tabular-nums">
              {summary.los_woodmont_watch_days}d
            </div>
          </div>
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-amber-800">
              4-week trend
            </div>
            <div className="mt-1 text-2xl font-bold text-amber-900 tabular-nums">
              ▲ +{summary.los_woodmont_trend_days}d
            </div>
          </div>
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-amber-800">Owner</div>
            <div className="mt-1 text-sm text-amber-900">Dr. Aneja · PIP weekly review</div>
          </div>
        </div>
      </Card>
    </>
  );
}
