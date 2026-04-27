"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export interface PortalSite {
  site_id: number;
  site_name: string;
  state: string;
  census: number | null;
  /** Phase 1 portal does not display open_shifts; the field arrives in the
   * payload for compatibility with the existing API shape but is unused
   * in this form. */
  open_shifts: number;
  /** ISO-8601 of the row's last save for this date, null if never entered. */
  entered_at: string | null;
}

export interface PortalSummary {
  entry_date: string;
  total_census: number;
  facilities_reported: number;
  facilities_missing: number;
  last_updated_at: string | null;
}

interface CensusEntryFormProps {
  initialDate: string;
  initialSites: PortalSite[];
  initialSummary: PortalSummary;
  apiBase: string;
}

interface RowState {
  site_id: number;
  site_name: string;
  state: string;
  /** Live editable value while in editMode. */
  census: string;
  /** Last-persisted census (null if never entered for this date). */
  savedCensus: number | null;
  /** Last-saved timestamp from the server. Drives the lock state. */
  enteredAt: string | null;
  /** Per-row edit toggle. True for never-entered rows. */
  editMode: boolean;
  saving: boolean;
  feedback: { kind: "ok" | "error"; message: string } | null;
}

function toRow(site: PortalSite): RowState {
  return {
    site_id: site.site_id,
    site_name: site.site_name,
    state: site.state,
    census: site.census === null ? "" : String(site.census),
    savedCensus: site.census,
    enteredAt: site.entered_at,
    editMode: site.entered_at === null,
    saving: false,
    feedback: null,
  };
}

function formatTime(iso: string | null): string {
  if (iso === null) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function formatDateTime(iso: string | null): string {
  if (iso === null) return "—";
  const d = new Date(iso);
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  })}`;
}

function todayIso(): string {
  // Local-time YYYY-MM-DD so the date picker default matches the user's clock.
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export function CensusEntryForm({
  initialDate,
  initialSites,
  initialSummary,
  apiBase,
}: CensusEntryFormProps) {
  const router = useRouter();
  const [rows, setRows] = useState<RowState[]>(() => initialSites.map(toRow));
  // Server renders the summary for the initial date; per-row Save responses
  // refresh the affected row, and `router.refresh()` re-fetches on next nav.
  // We keep a local copy so totals update inline without waiting on the round-trip.
  const [summary, setSummary] = useState(initialSummary);

  function patchRow(siteId: number, patch: Partial<RowState>): void {
    setRows((current) => current.map((r) => (r.site_id === siteId ? { ...r, ...patch } : r)));
  }

  function recomputeSummary(updated: RowState[]): typeof summary {
    const reported = updated.filter((r) => r.savedCensus !== null);
    const total = reported.reduce((sum, r) => sum + (r.savedCensus ?? 0), 0);
    const isos = reported.map((r) => r.enteredAt).filter((s): s is string => s !== null);
    const lastUpdated =
      isos.length === 0 ? null : isos.reduce((max, cur) => (cur > max ? cur : max), isos[0]);
    return {
      entry_date: summary.entry_date,
      total_census: total,
      facilities_reported: reported.length,
      facilities_missing: Math.max(0, updated.length - reported.length),
      last_updated_at: lastUpdated,
    };
  }

  function onDateChange(newDate: string): void {
    router.push(`/census/entry?date=${encodeURIComponent(newDate)}`);
  }

  function onEdit(siteId: number): void {
    setRows((current) =>
      current.map((r) =>
        r.site_id === siteId
          ? {
              ...r,
              editMode: true,
              feedback: null,
              census: r.savedCensus === null ? "" : String(r.savedCensus),
            }
          : r,
      ),
    );
  }

  function onCancel(siteId: number): void {
    setRows((current) =>
      current.map((r) =>
        r.site_id === siteId
          ? {
              ...r,
              editMode: false,
              feedback: null,
              census: r.savedCensus === null ? "" : String(r.savedCensus),
            }
          : r,
      ),
    );
  }

  async function onSaveRow(row: RowState): Promise<void> {
    const censusStr = row.census.trim();
    if (censusStr === "") {
      patchRow(row.site_id, {
        feedback: { kind: "error", message: "Enter a census number." },
      });
      return;
    }
    const censusNum = Number.parseInt(censusStr, 10);
    if (Number.isNaN(censusNum) || censusNum < 0 || censusNum > 2000) {
      patchRow(row.site_id, {
        feedback: { kind: "error", message: "Census must be 0–2000." },
      });
      return;
    }

    patchRow(row.site_id, { saving: true, feedback: null });

    try {
      const res = await fetch(`${apiBase}/api/v1/census-portal/daily-census`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          entry_date: initialDate,
          rows: [{ site_id: row.site_id, census: censusNum }],
        }),
      });

      if (res.status === 401) {
        router.replace("/census/login");
        return;
      }

      if (!res.ok) {
        const detail = await res.text();
        patchRow(row.site_id, {
          saving: false,
          feedback: { kind: "error", message: `Save failed (${res.status}): ${detail}` },
        });
        return;
      }

      const body = (await res.json()) as Array<{
        site_id: number;
        census: number;
        entered_at: string;
      }>;
      const saved = body.find((r) => r.site_id === row.site_id);
      if (!saved) {
        patchRow(row.site_id, {
          saving: false,
          feedback: {
            kind: "error",
            message: "Server response missing this row — refresh and retry.",
          },
        });
        return;
      }

      const next = rows.map((r) =>
        r.site_id === row.site_id
          ? {
              ...r,
              saving: false,
              editMode: false,
              savedCensus: saved.census,
              enteredAt: saved.entered_at,
              census: String(saved.census),
              feedback: {
                kind: "ok" as const,
                message: `Saved at ${formatTime(saved.entered_at)}.`,
              },
            }
          : r,
      );
      setRows(next);
      setSummary(recomputeSummary(next));
      router.refresh();
    } catch (err) {
      patchRow(row.site_id, {
        saving: false,
        feedback: {
          kind: "error",
          message: err instanceof Error ? err.message : "Network error",
        },
      });
    }
  }

  async function onLogout(): Promise<void> {
    await fetch(`${apiBase}/api/v1/census-portal/logout`, {
      method: "POST",
      credentials: "include",
    });
    router.replace("/census/login");
  }

  const isToday = initialDate === todayIso();
  const allMissing = summary.facilities_reported === 0;

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
            Date
            <input
              type="date"
              value={initialDate}
              max={todayIso()}
              onChange={(e) => onDateChange(e.target.value)}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm"
            />
          </label>
          <span className="text-xs text-slate-500">
            {isToday ? "Today's census" : `Census for ${initialDate}`}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <SummaryCard
            label="Total Census"
            value={String(summary.total_census)}
            tone={summary.total_census > 0 ? "ok" : "muted"}
          />
          <SummaryCard
            label="Facilities Reported"
            value={`${summary.facilities_reported} / ${summary.facilities_reported + summary.facilities_missing}`}
            tone="ok"
          />
          <SummaryCard
            label="Facilities Missing"
            value={String(summary.facilities_missing)}
            tone={summary.facilities_missing === 0 ? "ok" : "warn"}
          />
          <SummaryCard label="Last Updated" value={formatDateTime(summary.last_updated_at)} />
        </div>
      </div>

      {allMissing ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50/50 p-6 text-center text-sm text-slate-500">
          No census submitted for this date yet.
        </div>
      ) : null}

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-slate-600">
            <tr>
              <th className="px-4 py-2 text-left font-medium">Facility</th>
              <th className="w-16 px-4 py-2 text-left font-medium">State</th>
              <th className="px-4 py-2 text-left font-medium">Census</th>
              <th className="w-44 px-4 py-2 text-right font-medium">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const locked = !row.editMode;
              return (
                <tr
                  key={row.site_id}
                  className={`border-t border-slate-100 ${
                    locked && row.savedCensus !== null ? "bg-emerald-50/30" : ""
                  }`}
                >
                  <td className="px-4 py-3 font-medium text-slate-900">{row.site_name}</td>
                  <td className="px-4 py-3 text-slate-500">{row.state}</td>

                  {locked ? (
                    <td className="px-4 py-3">
                      {row.savedCensus !== null ? (
                        <div className="flex items-baseline gap-3 text-slate-700">
                          <span
                            className="inline-flex items-center gap-1 text-emerald-700"
                            aria-label="Saved for this date"
                          >
                            <span aria-hidden>✓</span>
                            <span className="font-semibold tabular-nums">{row.savedCensus}</span>
                          </span>
                          <span className="text-slate-400">·</span>
                          <span className="text-xs text-slate-500">
                            entered {formatTime(row.enteredAt)}
                          </span>
                        </div>
                      ) : (
                        <span className="text-xs italic text-slate-400">not entered yet</span>
                      )}
                      {row.feedback?.kind === "ok" ? (
                        <div className="mt-1 text-xs text-emerald-700">{row.feedback.message}</div>
                      ) : null}
                    </td>
                  ) : (
                    <td className="px-4 py-3">
                      <input
                        type="number"
                        inputMode="numeric"
                        min={0}
                        max={2000}
                        value={row.census}
                        onChange={(e) =>
                          patchRow(row.site_id, { census: e.target.value, feedback: null })
                        }
                        aria-label={`${row.site_name} census`}
                        className="w-28 rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                        placeholder="0"
                      />
                      {row.feedback?.kind === "error" ? (
                        <div className="mt-1 text-xs text-red-700">{row.feedback.message}</div>
                      ) : null}
                    </td>
                  )}

                  <td className="px-4 py-3 text-right">
                    {locked ? (
                      <button
                        type="button"
                        onClick={() => onEdit(row.site_id)}
                        className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:border-indigo-400 hover:text-indigo-700"
                      >
                        {row.savedCensus === null ? "Enter" : "Edit"}
                      </button>
                    ) : (
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => onSaveRow(row)}
                          disabled={row.saving}
                          className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                        >
                          {row.saving ? "Saving…" : "Save"}
                        </button>
                        {row.savedCensus !== null ? (
                          <button
                            type="button"
                            onClick={() => onCancel(row.site_id)}
                            disabled={row.saving}
                            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:border-slate-400 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            Cancel
                          </button>
                        ) : null}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-sm">
        <button
          type="button"
          onClick={onLogout}
          className="text-slate-500 underline-offset-2 hover:underline"
        >
          Sign out
        </button>
        <span className="text-xs text-slate-400">
          Each row saves independently. Already-saved rows show in green.
        </span>
      </div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "ok" | "warn" | "muted" | "neutral";
}) {
  const accent =
    tone === "ok"
      ? "text-emerald-700"
      : tone === "warn"
        ? "text-amber-700"
        : tone === "muted"
          ? "text-slate-400"
          : "text-slate-900";
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 text-xl font-bold tabular-nums ${accent}`}>{value}</div>
    </div>
  );
}
