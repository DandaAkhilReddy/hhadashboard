"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useMemo, useState } from "react";

export interface PortalSite {
  site_id: number;
  site_name: string;
  state: string;
  census: number | null;
  open_shifts: number;
}

interface CensusEntryFormProps {
  initialDate: string;
  initialSites: PortalSite[];
  apiBase: string;
}

interface RowState {
  site_id: number;
  site_name: string;
  state: string;
  census: string;
  open_shifts: string;
}

function toRow(site: PortalSite): RowState {
  return {
    site_id: site.site_id,
    site_name: site.site_name,
    state: site.state,
    census: site.census === null ? "" : String(site.census),
    open_shifts: String(site.open_shifts),
  };
}

export function CensusEntryForm({
  initialDate,
  initialSites,
  apiBase,
}: CensusEntryFormProps) {
  const router = useRouter();
  const [rows, setRows] = useState<RowState[]>(() => initialSites.map(toRow));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const ready = useMemo(
    () => rows.some((r) => r.census.trim().length > 0),
    [rows],
  );

  function updateRow(index: number, patch: Partial<RowState>): void {
    setRows((current) =>
      current.map((r, i) => (i === index ? { ...r, ...patch } : r)),
    );
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setSavedAt(null);

    const payloadRows = rows
      .filter((r) => r.census.trim().length > 0)
      .map((r) => ({
        site_id: r.site_id,
        census: Number.parseInt(r.census, 10),
        open_shifts: Number.parseInt(r.open_shifts || "0", 10),
      }));

    if (payloadRows.length === 0) {
      setError("Enter a census number for at least one facility.");
      setSubmitting(false);
      return;
    }

    try {
      const res = await fetch(`${apiBase}/api/v1/census-portal/daily-census`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          entry_date: initialDate,
          rows: payloadRows,
        }),
      });
      if (res.status === 401) {
        router.replace("/census/login");
        return;
      }
      if (!res.ok) {
        const detail = await res.text();
        setError(`Save failed (${res.status}): ${detail}`);
        return;
      }
      setSavedAt(new Date().toISOString());
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Network error");
    } finally {
      setSubmitting(false);
    }
  }

  async function onLogout(): Promise<void> {
    await fetch(`${apiBase}/api/v1/census-portal/logout`, {
      method: "POST",
      credentials: "include",
    });
    router.replace("/census/login");
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-slate-600">
            <tr>
              <th className="px-4 py-2 text-left font-medium">Facility</th>
              <th className="w-16 px-4 py-2 text-left font-medium">State</th>
              <th className="w-32 px-4 py-2 text-left font-medium">Census</th>
              <th className="w-32 px-4 py-2 text-left font-medium">Open shifts</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr key={row.site_id} className="border-t border-slate-100">
                <td className="px-4 py-2 font-medium text-slate-900">
                  {row.site_name}
                </td>
                <td className="px-4 py-2 text-slate-500">{row.state}</td>
                <td className="px-4 py-2">
                  <input
                    type="number"
                    inputMode="numeric"
                    min={0}
                    max={2000}
                    value={row.census}
                    onChange={(e) => updateRow(idx, { census: e.target.value })}
                    aria-label={`${row.site_name} census`}
                    className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </td>
                <td className="px-4 py-2">
                  <input
                    type="number"
                    inputMode="numeric"
                    min={0}
                    max={50}
                    value={row.open_shifts}
                    onChange={(e) =>
                      updateRow(idx, { open_shifts: e.target.value })
                    }
                    aria-label={`${row.site_name} open shifts`}
                    className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {error ? (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {error}
        </div>
      ) : null}
      {savedAt ? (
        <div
          role="status"
          className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700"
        >
          Saved at {new Date(savedAt).toLocaleTimeString()}.
        </div>
      ) : null}

      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={onLogout}
          className="text-sm text-slate-500 underline-offset-2 hover:underline"
        >
          Sign out
        </button>
        <button
          type="submit"
          disabled={!ready || submitting}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {submitting ? "Saving…" : "Save all"}
        </button>
      </div>
    </form>
  );
}
