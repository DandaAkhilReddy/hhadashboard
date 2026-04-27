import { cn } from "@/lib/format";
import type { ReactNode } from "react";

export function Card({
  children,
  className,
  interactive,
}: {
  children: ReactNode;
  className?: string;
  interactive?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-slate-200 bg-white p-6 shadow-sm ring-1 ring-slate-900/[0.02] transition-shadow",
        interactive && "hover:-translate-y-0.5 hover:shadow-md transition-transform",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  owner,
  right,
}: {
  title: string;
  owner?: string;
  right?: ReactNode;
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-4 border-b border-slate-100 pb-3">
      <div>
        <h2 className="text-base font-bold tracking-tight text-slate-900">{title}</h2>
        {owner ? (
          <div className="mt-0.5 text-[11px] font-medium text-slate-500">{owner}</div>
        ) : null}
      </div>
      {right ? <div className="shrink-0">{right}</div> : null}
    </div>
  );
}
