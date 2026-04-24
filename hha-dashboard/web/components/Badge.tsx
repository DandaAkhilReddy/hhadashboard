import type { ReactNode } from "react";
import { cn } from "@/lib/format";

type Variant = "good" | "warn" | "bad" | "blue" | "gray";

const CLASSES: Record<Variant, string> = {
  good: "bg-emerald-100 text-emerald-800",
  warn: "bg-amber-100 text-amber-800",
  bad: "bg-red-100 text-red-800",
  blue: "bg-blue-100 text-blue-800",
  gray: "bg-slate-100 text-slate-700",
};

export function Badge({ variant = "gray", children }: { variant?: Variant; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold",
        CLASSES[variant],
      )}
    >
      {children}
    </span>
  );
}

export function SourceTag({ source }: { source: string }) {
  const label = source.includes("VENTRA")
    ? "FL · Ventra"
    : source.includes("HHA_TX_MANUAL")
      ? "TX · manual"
      : source;
  const variant: Variant = source.includes("VENTRA") ? "blue" : "gray";
  return <Badge variant={variant}>{label}</Badge>;
}
