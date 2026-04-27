"use client";

import type { DayPoint } from "@/lib/trend-points";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/**
 * 14-bar census trend with a 3-mo-avg reference line. Built on Recharts.
 * Today's bar is rendered slate-900; previous days slate-300; days with
 * a null census still take a slot but render as 0 height (gap).
 */
export function CensusTrendChart({
  points,
  avg,
}: {
  points: DayPoint[];
  avg: number;
}) {
  const data = points.map((p) => ({
    label: p.date.slice(8),
    date: p.date,
    census: p.census ?? 0,
    isToday: p.isToday,
    hasData: p.census !== null,
  }));

  return (
    <div className="h-44 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 16, right: 8, bottom: 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 10, fill: "#94a3b8" }}
            tickLine={false}
            axisLine={{ stroke: "#e2e8f0" }}
          />
          <YAxis
            tick={{ fontSize: 10, fill: "#94a3b8" }}
            tickLine={false}
            axisLine={false}
            width={28}
          />
          <Tooltip
            cursor={{ fill: "rgba(99,102,241,0.08)" }}
            contentStyle={{
              border: "1px solid #e2e8f0",
              borderRadius: 6,
              fontSize: 12,
              padding: "6px 10px",
              boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
            }}
            formatter={(v: number) => [v === 0 ? "—" : v, "Census"]}
            labelFormatter={(label, payload) => {
              const d = payload?.[0]?.payload?.date as string | undefined;
              return d ? d : String(label);
            }}
          />
          <ReferenceLine
            y={avg}
            stroke="#64748b"
            strokeDasharray="3 3"
            label={{
              value: `3-mo avg ${avg}`,
              position: "right",
              fill: "#64748b",
              fontSize: 10,
            }}
          />
          <Bar dataKey="census" radius={[3, 3, 0, 0]}>
            {data.map((d) => (
              <Cell
                key={d.date}
                fill={d.isToday ? "#0f172a" : d.hasData ? "#cbd5e1" : "transparent"}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// `buildTrendPoints` lives in `@/lib/trend-points` so server components
// can call it directly (this file is "use client" because of Recharts).
