"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export interface PortalSite {
  site_id: number;
  site_name: string;
  state: string;
  census: number | null;
  open_shifts: number;
  /**
   * ISO-8601 timestamp of the row's last save today, or null if the row
   * has never been entered. Drives the locked-with-Edit row state below:
   * non-null → row renders as `✓ N · entered HH:MM · [Edit]`;
   * null → row renders as editable inputs with a [Save] button.
   */
  entered_at: string | null;
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
  /** Live editable value while in editMode. */
  census: string;
  open_shifts: string;
  /** Last-persisted census (null if never saved today). Used to render the
   * locked summary and to revert from a Cancel. */
  savedCensus: number | null;
  savedOpenShifts: number;
  /** Last-saved timestamp from the server. Drives the lock state. */
  enteredAt: string | null;
  /** Per-row edit toggle. True for never-entered rows; false for already-saved
   * rows (until the user clicks Edit). */
  editMode: boolean;
  /** Per-row save state — keeps each save independent so a slow Westside
   * save doesn't grey-out Woodmont's Save button. */
  saving: boolean;
  /** Per-row last error or save success label, cleared when the user starts
   * editing again. */
  feedback: { kind: "ok" | "error"; message: string } | null;
}

function toRow(site: PortalSite): RowState {
  return {
    site_id: site.site_id,
    site_name: site.site_name,
    state: site.state,
    census: site.census === null ? "" : String(site.census),
    open_shifts: String(site.open_shifts),
    savedCensus: site.census,
    savedOpenShifts: site.open_shifts,
    enteredAt: site.entered_at,
    // Already-entered rows start LOCKED. Never-entered rows start EDITABLE.
    editMode: site.entered_at === null,
    saving: false,
    feedback: null,
  };
}

function formatTime(iso: string | null): string {
  if (iso === null) return "";
  // The backend emits UTC; the user reads local time. toLocaleTimeString
  // handles the conversion automatically.
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export function CensusEntryForm({ initialDate, initialSites, apiBase }: CensusEntryFormProps) {
  const router = useRouter();
  const [rows, setRows] = useState<RowState[]>(() => initialSites.map(toRow));

  function patchRow(siteId: number, patch: Partial<RowState>): void {
    setRows((current) => current.map((r) => (r.site_id === siteId ? { ...r, ...patch } : r)));
  }

  function onEdit(siteId: number): void {
    // Snapshot current saved values into the editable fields and unlock.
    setRows((current) =>
      current.map((r) =>
        r.site_id === siteId
          ? {
              ...r,
              editMode: true,
              feedback: null,
              // Reset the input to the persisted value (in case a half-typed
              // edit was abandoned earlier in this session).
              census: r.savedCensus === null ? "" : String(r.savedCensus),
              open_shifts: String(r.savedOpenShifts),
            }
          : r,
      ),
    );
  }

  function onCancel(siteId: number): void {
    // Revert inputs to last-saved values and re-lock.
    setRows((current) =>
      current.map((r) =>
        r.site_id === siteId
          ? {
              ...r,
              editMode: false,
              feedback: null,
              census: r.savedCensus === null ? "" : String(r.savedCensus),
              open_shifts: String(r.savedOpenShifts),
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
    const openShiftsNum = Number.parseInt(row.open_shifts || "0", 10);

    patchRow(row.site_id, { saving: true, feedback: null });

    try {
      const res = await fetch(`${apiBase}/api/v1/census-portal/daily-census`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          entry_date: initialDate,
          rows: [
            {
              site_id: row.site_id,
              census: censusNum,
              open_shifts: openShiftsNum,
            },
          ],
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
        open_shifts: number;
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

      patchRow(row.site_id, {
        saving: false,
        editMode: false,
        savedCensus: saved.census,
        savedOpenShifts: saved.open_shifts,
        enteredAt: saved.entered_at,
        census: String(saved.census),
        open_shifts: String(saved.open_shifts),
        feedback: { kind: "ok", message: `Saved at ${formatTime(saved.entered_at)}.` },
      });
      // Keep the dashboard read-side fresh on a snappy refresh after multiple
      // edits — cheap because Next streams diffs.
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

  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-slate-600">
            <tr>
              <th className="px-4 py-2 text-left font-medium">Facility</th>
              <th className="w-16 px-4 py-2 text-left font-medium">State</th>
              <th className="px-4 py-2 text-left font-medium">Today</th>
              <th className="w-44 px-4 py-2 text-right font-medium">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const locked = !row.editMode;
              return (
                <tr
                  key={row.site_id}
                  className={`border-t border-slate-100 ${locked ? "bg-emerald-50/30" : ""}`}
                >
                  <td className="px-4 py-3 font-medium text-slate-900">{row.site_name}</td>
                  <td className="px-4 py-3 text-slate-500">{row.state}</td>

                  {locked ? (
                    <td className="px-4 py-3">
                      <div className="flex items-baseline gap-3 text-slate-700">
                        <span
                          className="inline-flex items-center gap-1 text-emerald-700"
                          aria-label="Saved for today"
                        >
                          <span aria-hidden>✓</span>
                          <span className="font-semibold tabular-nums">
                            {row.savedCensus} census
                          </span>
                        </span>
                        <span className="text-slate-400">·</span>
                        <span className="tabular-nums text-slate-600">
                          {row.savedOpenShifts} open shifts
                        </span>
                        <span className="text-slate-400">·</span>
                        <span className="text-xs text-slate-500">
                          entered {formatTime(row.enteredAt)}
                        </span>
                      </div>
                      {row.feedback?.kind === "ok" ? (
                        <div className="mt-1 text-xs text-emerald-700">{row.feedback.message}</div>
                      ) : null}
                    </td>
                  ) : (
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <label className="flex items-center gap-1 text-xs text-slate-600">
                          Census
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
                            className="w-24 rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                          />
                        </label>
                        <label className="flex items-center gap-1 text-xs text-slate-600">
                          Open shifts
                          <input
                            type="number"
                            inputMode="numeric"
                            min={0}
                            max={50}
                            value={row.open_shifts}
                            onChange={(e) =>
                              patchRow(row.site_id, {
                                open_shifts: e.target.value,
                                feedback: null,
                              })
                            }
                            aria-label={`${row.site_name} open shifts`}
                            className="w-20 rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                          />
                        </label>
                      </div>
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
                        Edit
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
