import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api-client";
import { WeeklyClinicalForm } from "./WeeklyClinicalForm";

function lastSunday(): string {
  const d = new Date();
  // (weekday + 1) % 7 — Sun=0..Sat=6 → 0,6,5,4,3,2,1
  const offset = (d.getDay() + 0) % 7; // d.getDay() Sun=0
  d.setDate(d.getDate() - offset);
  return d.toISOString().slice(0, 10);
}

export default async function WeeklyClinicalPage({
  searchParams,
}: {
  searchParams: Promise<{ week_ending?: string }>;
}) {
  const params = await searchParams;
  const weekEnding = params.week_ending ?? lastSunday();
  const rows = await api.getWeeklyClinical(weekEnding).catch(() => []);

  return (
    <>
      <PageHeader
        title="Weekly Clinical Audit"
        subtitle={
          <>
            Dr. Aneja / Dr. Reddy &mdash; owner_clinical.
            <br />
            <span className="text-xs text-slate-500">
              Enter H&amp;P 24h compliance, DC 48h compliance, average LOS, and chart-audit
              volume for FL and TX. Re-saving overwrites in place. Clinical board reflects
              immediately.
            </span>
          </>
        }
      />
      <WeeklyClinicalForm initialWeekEnding={weekEnding} initialRows={rows} />
    </>
  );
}
