import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api-client";
import { WeeklyHrForm } from "./WeeklyHrForm";

function lastSunday(): string {
  const d = new Date();
  d.setDate(d.getDate() - d.getDay()); // Sun=0 → 0 days back; otherwise back to Sun
  return d.toISOString().slice(0, 10);
}

export default async function WeeklyHrPage({
  searchParams,
}: {
  searchParams: Promise<{ week_ending?: string }>;
}) {
  const params = await searchParams;
  const weekEnding = params.week_ending ?? lastSunday();
  const initial = await api.getWeeklyHr(weekEnding).catch(() => null);

  return (
    <>
      <PageHeader
        title="Weekly HR Snapshot"
        subtitle={
          <>
            Andrea — owner_hr.
            <br />
            <span className="text-xs text-slate-500">
              Headcount, open positions, 90-day terminations, below-FMV count. HHA-wide (not split
              by state). Re-saving overwrites in place. People board updates immediately.
            </span>
          </>
        }
      />
      <WeeklyHrForm initialWeekEnding={weekEnding} initial={initial} />
    </>
  );
}
