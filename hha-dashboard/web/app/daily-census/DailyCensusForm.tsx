"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Card, CardHeader } from "@/components/Card";
import { toast } from "@/components/Toast";
import { useApiBrowser, type DailyEntryOut } from "@/lib/api-browser";
import { cn } from "@/lib/format";

type Draft = {
  site_id: number;
  site_name: string;
  state: string;
  census: string; // string so user can clear the field
  open_shifts: string;
  notes: string;
  source: string | null; // 'manual' | 'pdf_extract' | null
  updated_at: string | null;
};

function toDraft(row: DailyEntryOut): Draft {
  return {
    site_id: row.site_id,
    site_name: row.site_name,
    state: row.state,
    census: row.census === null ? "" : String(row.census),
    open_shifts: String(row.open_shifts ?? 0),
    notes: row.notes ?? "",
    source: row.source,
    updated_at: row.updated_at,
  };
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function DailyCensusForm({ initialRows }: { initialRows: DailyEntryOut[] }) {
  const router = useRouter();
  const api = useApiBrowser();
  const [drafts, setDrafts] = useState<Draft[]>(initialRows.map(toDraft));
  const [saving, setSaving] = useState(false);

  // If the server returned nothing (API down, etc.), render a hint instead of an empty table.
  const hasAnyRows = drafts.length > 0;

  const enteredCount = useMemo(
    () => drafts.filter((d) => d.census.trim() !== "").length,
    [drafts],
  );

  const updateDraft = (site_id: number, patch: Partial<Draft>): void => {
    setDrafts((prev) =>
      prev.map((d) => (d.site_id === site_id ? { ...d, ...patch } : d)),
    );
  };

  const onSave = async (): Promise<void> => {
    // Only submit rows where the user actually entered a census value
    const rows = drafts
      .filter((d) => d.census.trim() !== "")
      .map((d) => ({
        site_id: d.site_id,
        census: Number.parseInt(d.census, 10),
        open_shifts: d.open_shifts.trim() === "" ? 0 : Number.parseInt(d.open_shifts, 10),
        notes: d.notes.trim() || null,
      }));

    // Basic client-side sanity (server revalidates)
    for (const r of rows) {
      if (!Number.isFinite(r.census) || r.census < 0 || r.census > 2000) {
        toast(`Invalid census value for site ${r.site_id}`, "error");
        return;
      }
    }

    if (rows.length === 0) {
      toast("Nothing to save — enter at least one census number.", "error");
      return;
    }

    setSaving(true);
    try {
      const saved = await api.saveDailyCensus({ entry_date: today(), rows });
      // Merge server response back into drafts so source/updated_at reflect the save
      const byId = new Map(saved.map((s) => [s.site_id, s]));
      setDrafts((prev) =>
        prev.map((d) => {
          const s = byId.get(d.site_id);
          return s ? toDraft(s) : d;
        }),
      );
      toast(`Saved ${saved.length} site${saved.length === 1 ? "" : "s"}.`, "success");
      // Refresh server components so /operations picks up the new values.
      router.refresh();
    } catch (err) {
      toast(`Save failed: ${(err as Error).message}`, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title={`${today()} · ${enteredCount} of ${drafts.length} sites entered`}
        owner="Crystal Anderson · owner_ops"
        right={
          <button
            type="button"
            onClick={onSave}
            disabled={saving || !hasAnyRows}
            className={cn(
              "rounded-md px-4 py-2 text-sm font-semibold text-white transition-colors",
              saving || !hasAnyRows
                ? "bg-slate-300 cursor-not-allowed"
                : "bg-slate-900 hover:bg-slate-800",
            )}
          >
            {saving ? "Saving..." : "Save"}
          </button>
        }
      />

      {!hasAnyRows ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          Could not load site list. Is the API running at{" "}
          <code className="text-xs">localhost:8000</code>? The backend feeds this page from{" "}
          <code className="text-xs">masters.sites</code>.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-500">
                <th className="py-2 font-semibold">Site</th>
                <th className="py-2 font-semibold w-12">State</th>
                <th className="py-2 font-semibold">Census today</th>
                <th className="py-2 font-semibold">Open shifts</th>
                <th className="py-2 font-semibold">Notes</th>
                <th className="py-2 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {drafts.map((d) => {
                const filled = d.census.trim() !== "";
                return (
                  <tr
                    key={d.site_id}
                    className="border-b border-slate-100 last:border-0 hover:bg-slate-50"
                  >
                    <td className="py-2.5 font-medium text-slate-900">{d.site_name}</td>
                    <td className="py-2.5 text-xs text-slate-500">{d.state}</td>
                    <td className="py-2.5">
                      <input
                        type="number"
                        min={0}
                        max={2000}
                        inputMode="numeric"
                        value={d.census}
                        onChange={(e) => updateDraft(d.site_id, { census: e.target.value })}
                        className={cn(
                          "w-28 rounded-md border px-2 py-1 text-sm tabular-nums",
                          filled
                            ? "border-emerald-300 bg-emerald-50"
                            : "border-slate-300 bg-white",
                        )}
                        placeholder="—"
                        disabled={saving}
                      />
                    </td>
                    <td className="py-2.5">
                      <input
                        type="number"
                        min={0}
                        max={50}
                        inputMode="numeric"
                        value={d.open_shifts}
                        onChange={(e) =>
                          updateDraft(d.site_id, { open_shifts: e.target.value })
                        }
                        className="w-20 rounded-md border border-slate-300 bg-white px-2 py-1 text-sm tabular-nums"
                        disabled={saving}
                      />
                    </td>
                    <td className="py-2.5">
                      <input
                        type="text"
                        maxLength={500}
                        value={d.notes}
                        onChange={(e) => updateDraft(d.site_id, { notes: e.target.value })}
                        className="w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
                        placeholder="Optional"
                        disabled={saving}
                      />
                    </td>
                    <td className="py-2.5 text-xs text-slate-500">
                      {d.source === "manual" ? (
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-700">
                          ✓ Manual
                        </span>
                      ) : d.source === "pdf_extract" ? (
                        <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[11px] font-semibold text-blue-800">
                          PDF
                        </span>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
