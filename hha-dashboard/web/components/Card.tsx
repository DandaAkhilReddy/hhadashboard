import type { ReactNode } from "react";
import { cn } from "@/lib/format";

export function Card({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-slate-200 bg-white p-5 shadow-sm",
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
    <div className="mb-3 flex items-start justify-between gap-4">
      <div>
        <h2 className="text-base font-bold text-slate-900">{title}</h2>
        {owner ? <div className="mt-0.5 text-xs text-slate-500">{owner}</div> : null}
      </div>
      {right}
    </div>
  );
}
