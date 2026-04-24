import { Badge } from "@/components/Badge";
import { Card } from "@/components/Card";
import { PageHeader } from "@/components/PageHeader";
import { api, type Scorecard } from "@/lib/api-client";
import { num } from "@/lib/format";

export default async function ScorecardsPage() {
  const cards = await api.scorecards();

  return (
    <>
      <PageHeader
        title="Doctor Scorecards"
        subtitle={
          <>
            Per-physician performance · <strong>Exec + comp_viewer only</strong> · Doctors never
            see own rank or peers&apos;
          </>
        }
        right={
          <>
            <select className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs">
              <option>All physicians</option>
              <option>Top 10 rank</option>
              <option>PIP</option>
              <option>Below FMV</option>
            </select>
          </>
        }
      />

      <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 p-4">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-amber-200 text-xs font-bold text-amber-900">
            !
          </div>
          <div className="text-sm text-amber-900">
            <strong>Sensitive data.</strong> Named physician ranks + composite scores. Visibility
            restricted to exec group + comp_viewer flag (CEO, CFO). Rank is never shown to the
            individual doctor. Views audited.
          </div>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {cards.sort((a, b) => a.rank - b.rank).map((md) => (
          <ScorecardCard key={md.physician_id} md={md} />
        ))}
      </div>

      <Card className="mt-6 bg-slate-50">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-slate-200 text-xs text-slate-700">
            i
          </div>
          <div className="text-sm text-slate-600">
            <strong>Grey tiles are P2 deliverables.</strong> RVU + employment + status ship from
            Paycom in P1. Revenue/FTE, Documentation Score, Chart Turnaround come from Athena in
            Phase 2 once Ventra provides FL access — pre-aggregated at ingestion edge (no
            claim-level data persisted per ADR-001).
          </div>
        </div>
      </Card>
    </>
  );
}

function ScorecardCard({ md }: { md: Scorecard }) {
  const rankTone =
    md.rank <= 5 ? "text-emerald-600" : md.rank >= 40 ? "text-red-600" : "text-slate-900";
  const borderTone = md.status === "PIP" ? "border-red-200" : "border-slate-200";

  return (
    <Card className={borderTone}>
      <div className="mb-3 flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <div className="truncate font-bold text-slate-900">{md.name}</div>
          <div className="truncate text-xs text-slate-500">
            {md.site} · {md.state} · {md.employment_type} · {md.comp_model}
          </div>
        </div>
        <div className="text-right">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Rank</div>
          <div className={`text-2xl font-bold tabular-nums ${rankTone}`}>#{md.rank}</div>
        </div>
      </div>

      <div className="mb-3 grid grid-cols-2 gap-2">
        <Tile label="RVU 90d" value={num(md.rvu_90d)} />
        <Tile label="Revenue/FTE" value={md.revenue_per_fte_usd ?? "—"} placeholder={md.revenue_per_fte_usd === null} />
        <Tile label="Doc Score" value={md.documentation_score_pct ?? "—"} placeholder={md.documentation_score_pct === null} />
        <Tile label="Chart Turn" value={md.chart_turnaround_days ?? "—"} placeholder={md.chart_turnaround_days === null} />
      </div>

      <div className="flex items-center justify-between">
        <div className="flex gap-1.5">
          {md.status === "PIP" ? (
            <Badge variant="bad">PIP Active</Badge>
          ) : md.status === "VACANT" ? (
            <Badge variant="bad">VACANT</Badge>
          ) : (
            <Badge variant="good">Active</Badge>
          )}
          {md.below_fmv ? <Badge variant="warn">Below FMV</Badge> : null}
        </div>
        <span className="text-[10px] text-slate-400">P2 fills grey tiles</span>
      </div>
    </Card>
  );
}

function Tile({
  label,
  value,
  placeholder,
}: {
  label: string;
  value: React.ReactNode;
  placeholder?: boolean;
}) {
  return (
    <div className="rounded-lg bg-slate-50 p-2">
      <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-0.5 text-lg font-bold tabular-nums ${placeholder ? "text-slate-300" : "text-slate-900"}`}>
        {value}
      </div>
    </div>
  );
}
