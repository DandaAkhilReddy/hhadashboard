import type { ReactNode } from "react";
import { cn } from "@/lib/format";

type MetricCardProps = {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "neutral" | "good" | "warn" | "bad";
  accent?: boolean;
};

const TONE_CLASS = {
  neutral: "text-slate-900",
  good: "text-emerald-600",
  warn: "text-amber-600",
  bad: "text-red-600",
} as const;

export function MetricCard({ label, value, sub, tone = "neutral", accent }: MetricCardProps) {
  return (
    <div
      className={cn(
        "rounded-xl border p-5 shadow-sm",
        accent ? "border-indigo-200 bg-indigo-50" : "border-slate-200 bg-white",
      )}
    >
      <div className="text-[10.5px] font-bold uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className={cn("mt-1 text-3xl font-bold tabular-nums", TONE_CLASS[tone])}>{value}</div>
      {sub ? <div className="mt-1 text-xs text-slate-500">{sub}</div> : null}
    </div>
  );
}
