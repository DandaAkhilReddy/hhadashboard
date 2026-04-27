import { cn } from "@/lib/format";
import type { ReactNode } from "react";

type Variant = "good" | "warn" | "bad" | "blue" | "gray";

const CLASSES: Record<Variant, string> = {
  good: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-600/20",
  warn: "bg-amber-50 text-amber-800 ring-1 ring-amber-600/20",
  bad: "bg-red-50 text-red-700 ring-1 ring-red-600/20",
  blue: "bg-blue-50 text-blue-700 ring-1 ring-blue-600/20",
  gray: "bg-slate-100 text-slate-700 ring-1 ring-slate-500/10",
};

const DOT_CLASSES: Record<Variant, string> = {
  good: "bg-emerald-500",
  warn: "bg-amber-500",
  bad: "bg-red-500",
  blue: "bg-blue-500",
  gray: "bg-slate-400",
};

export function Badge({
  variant = "gray",
  children,
  dot,
}: {
  variant?: Variant;
  children: ReactNode;
  dot?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold",
        CLASSES[variant],
      )}
    >
      {dot ? (
        <span className={cn("h-1.5 w-1.5 rounded-full", DOT_CLASSES[variant])} aria-hidden />
      ) : null}
      {children}
    </span>
  );
}

export function SourceTag({ source }: { source: string }) {
  // Distinguish auto-ingested Ventra rows from Sandy's manual fallback so
  // execs know whether the number came from the SFTP cron or a person typing.
  const label =
    source === "VENTRA_FL_ATHENA"
      ? "FL · Ventra ✓ auto"
      : source === "VENTRA_FL_FALLBACK"
        ? "FL · Ventra (manual)"
        : source === "HHA_TX_MANUAL"
          ? "TX · manual"
          : source;
  const variant: Variant =
    source === "VENTRA_FL_ATHENA" ? "good" : source === "VENTRA_FL_FALLBACK" ? "warn" : "gray";
  return (
    <Badge variant={variant} dot>
      {label}
    </Badge>
  );
}
