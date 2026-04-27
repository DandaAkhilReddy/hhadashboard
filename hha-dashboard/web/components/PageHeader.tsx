import type { ReactNode } from "react";

function todayLabel(): string {
  return new Date().toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function PageHeader({
  title,
  subtitle,
  right,
  hideDate = false,
}: {
  title: string;
  subtitle?: ReactNode;
  right?: ReactNode;
  hideDate?: boolean;
}) {
  return (
    <div className="mb-6 border-b border-slate-200 pb-5">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">{title}</h1>
          {subtitle ? <p className="mt-1.5 max-w-3xl text-sm text-slate-600">{subtitle}</p> : null}
        </div>
        <div className="flex items-center gap-3">
          {!hideDate ? (
            <div className="hidden text-right md:block">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                As of
              </div>
              <div className="text-sm font-semibold tabular-nums text-slate-700">
                {todayLabel()}
              </div>
            </div>
          ) : null}
          {right ? <div className="flex items-center gap-2">{right}</div> : null}
        </div>
      </div>
    </div>
  );
}
