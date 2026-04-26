"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useUser } from "@/lib/auth/use-user";
import { cn } from "@/lib/format";

const TABS = [
  { href: "/", label: "Overview" },
  { href: "/operations", label: "Operations" },
  { href: "/finance", label: "Finance" },
  { href: "/clinical", label: "Clinical" },
  { href: "/people", label: "People" },
  { href: "/scorecards", label: "Doctor Scorecards", badge: "exec-only" },
  { href: "/daily-census", label: "Enter Census", badge: "owners" },
  { href: "/monthly-finance", label: "Enter Finance", badge: "owners" },
  { href: "/weekly-clinical", label: "Enter Clinical", badge: "owners" },
  { href: "/weekly-hr", label: "Enter HR", badge: "owners" },
  { href: "/uploads", label: "Upload Files", badge: "owners" },
];

function userDisplay(name: string): { label: string; initials: string } {
  const trimmed = name.trim();
  if (!trimmed) return { label: "—", initials: "?" };
  const parts = trimmed.split(/[\s@.]+/).filter(Boolean);
  const initials = parts
    .slice(0, 2)
    .map((p) => p.charAt(0).toUpperCase())
    .join("");
  return { label: trimmed, initials: initials || "?" };
}

export function TopNav() {
  const pathname = usePathname();
  const { user } = useUser();

  const displayName =
    user?.authenticated === true
      ? user.name || user.upn
      : user?.mode === "dev"
        ? "dev-default@local"
        : "—";
  const subtext =
    user?.authenticated === true
      ? user.roles.length > 0
        ? user.roles.join(" · ")
        : "no roles"
      : user?.mode === "dev"
        ? "admin · dev"
        : "signed out";
  const { initials } = userDisplay(displayName);

  return (
    <header className="sticky top-0 z-40 bg-slate-900 text-white shadow-sm">
      <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-6 px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-indigo-700 font-extrabold">
            H
          </div>
          <div>
            <div className="text-sm font-bold">HHA Medicine</div>
            <div className="text-[11px] text-slate-400">Operations Dashboard · Exec Leadership</div>
          </div>
        </div>

        <nav className="flex items-center gap-1">
          {TABS.map((t) => {
            const active = pathname === t.href || (t.href !== "/" && pathname.startsWith(t.href));
            return (
              <Link
                key={t.href}
                href={t.href}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors",
                  active
                    ? "bg-indigo-500 text-white"
                    : "text-slate-300 hover:bg-slate-800 hover:text-white",
                )}
              >
                {t.label}
                {t.badge ? (
                  <span className="rounded bg-white/20 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider">
                    {t.badge}
                  </span>
                ) : null}
              </Link>
            );
          })}
        </nav>

        <div className="flex items-center gap-3">
          <div className="hidden text-right text-[11px] text-slate-300 sm:block">
            <div className="font-medium text-slate-200">{displayName}</div>
            <div className="text-slate-500">{subtext}</div>
          </div>
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-700 text-xs font-bold">
            {initials}
          </div>
        </div>
      </div>
    </header>
  );
}
