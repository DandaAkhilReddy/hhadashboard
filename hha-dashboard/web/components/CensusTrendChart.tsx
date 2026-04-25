import { cn } from "@/lib/format";

type DayPoint = {
  date: string; // ISO YYYY-MM-DD
  census: number | null;
  isToday: boolean;
};

/**
 * Pure-CSS 14-bar sparkline. Renders one bar per day in `points`, scaled to
 * `max`. Today's bar is darker. Days with `census = null` show a thin dashed
 * placeholder so gaps are visually obvious.
 */
export function CensusTrendChart({
  points,
  avg,
}: {
  points: DayPoint[];
  avg: number;
}) {
  const max = Math.max(avg * 1.2, ...points.map((p) => p.census ?? 0)) || 1;
  const avgPct = (avg / max) * 100;

  return (
    <div className="relative">
      {/* 3-mo avg dashed line */}
      <div
        className="absolute left-0 right-0 border-t border-dashed border-slate-300"
        style={{ bottom: `${avgPct}%` }}
        aria-hidden
      />
      <div className="absolute right-0 -top-4 text-[10px] text-slate-400">
        3-mo avg {avg}
      </div>

      <div className="flex items-end gap-1 h-32 pt-4">
        {points.map((p) => {
          const heightPct = p.census !== null ? Math.max((p.census / max) * 100, 2) : 0;
          return (
            <div key={p.date} className="flex-1 flex flex-col items-center gap-1">
              <div className="flex-1 w-full flex items-end">
                {p.census !== null ? (
                  <div
                    className={cn(
                      "w-full rounded-t",
                      p.isToday ? "bg-slate-900" : "bg-slate-300",
                    )}
                    style={{ height: `${heightPct}%` }}
                    title={`${p.date}: ${p.census}`}
                  />
                ) : (
                  <div className="w-full h-full border-l border-dashed border-slate-200" title={`${p.date}: no entry`} />
                )}
              </div>
              <div
                className={cn(
                  "text-[9px] tabular-nums",
                  p.isToday ? "font-semibold text-slate-900" : "text-slate-400",
                )}
              >
                {p.date.slice(8)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Build a 14-day series ending today, filling gaps from `entries` (newest-first).
 */
export function buildTrendPoints(
  entries: { entry_date: string; census: number }[],
  today: Date = new Date(),
  days = 14,
): DayPoint[] {
  const byDate = new Map(entries.map((e) => [e.entry_date, e.census]));
  const points: DayPoint[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const iso = d.toISOString().slice(0, 10);
    points.push({
      date: iso,
      census: byDate.get(iso) ?? null,
      isToday: i === 0,
    });
  }
  return points;
}
