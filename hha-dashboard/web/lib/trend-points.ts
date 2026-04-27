/**
 * Build a 14-day trend series ending today.
 *
 * Pure server-renderable utility. The matching chart component
 * (`@/components/CensusTrendChart`) is a `"use client"` Recharts
 * wrapper — keep this file out of that boundary so server components
 * can import it directly.
 */

export type DayPoint = {
  date: string; // ISO YYYY-MM-DD
  census: number | null;
  isToday: boolean;
};

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
