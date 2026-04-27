"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type Point = { month: string; revenue_usd: number };

function formatMillions(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${Math.round(v / 1_000)}K`;
  return `$${v}`;
}

/**
 * 12-month revenue trend bar chart. Last bar (current MTD) highlighted red.
 * HHA-wide aggregate; provenance footnote shown by the parent component.
 */
export function MonthlyRevenueChart({ trend }: { trend: Point[] }) {
  const data = trend.map((p, i) => ({ ...p, isCurrent: i === trend.length - 1 }));

  return (
    <div className="h-48 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
          <XAxis
            dataKey="month"
            tick={{ fontSize: 10, fill: "#94a3b8" }}
            tickLine={false}
            axisLine={{ stroke: "#e2e8f0" }}
          />
          <YAxis
            tickFormatter={formatMillions}
            tick={{ fontSize: 10, fill: "#94a3b8" }}
            tickLine={false}
            axisLine={false}
            width={48}
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
            formatter={(v: number) => [formatMillions(v), "Revenue"]}
          />
          <Bar dataKey="revenue_usd" radius={[3, 3, 0, 0]}>
            {data.map((d) => (
              <Cell key={d.month} fill={d.isCurrent ? "#dc2626" : "#6366f1"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
