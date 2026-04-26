import type { Alert } from "@/lib/api-client";
import { cn } from "@/lib/format";

const STYLES = {
  red: "border-red-200 bg-red-50 text-red-900 [&_.dot]:bg-red-500",
  yellow: "border-amber-200 bg-amber-50 text-amber-900 [&_.dot]:bg-amber-500",
  blue: "border-blue-200 bg-blue-50 text-blue-900 [&_.dot]:bg-blue-500",
} as const;

export function AlertBanner({ alerts }: { alerts: Alert[] }) {
  if (!alerts.length) return null;
  return (
    <div className="mb-6 grid gap-3 md:grid-cols-3">
      {alerts.map((a) => (
        <div
          key={a.id}
          className={cn("flex items-start gap-3 rounded-xl border p-4", STYLES[a.severity])}
        >
          <span className="dot mt-1.5 inline-block h-2.5 w-2.5 shrink-0 rounded-full" />
          <div className="min-w-0 flex-1">
            <div className="text-[10px] font-bold uppercase tracking-wider opacity-80">
              {a.category} · {a.owner}
            </div>
            <div className="mt-0.5 text-sm font-semibold">{a.title}</div>
            <div className="mt-1 text-xs leading-relaxed opacity-90">{a.detail}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
