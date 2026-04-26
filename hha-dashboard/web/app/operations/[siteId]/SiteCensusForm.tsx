"use client";

import { toast } from "@/components/Toast";
import { api } from "@/lib/api-client";
import { cn } from "@/lib/format";
import { useRouter } from "next/navigation";
import { useState } from "react";

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function SiteCensusForm({
  siteId,
  initialCensus,
  initialOpenShifts,
  initialNotes,
}: {
  siteId: number;
  initialCensus: number;
  initialOpenShifts: number;
  initialNotes: string | null;
}) {
  const router = useRouter();
  const [census, setCensus] = useState(String(initialCensus));
  const [openShifts, setOpenShifts] = useState(String(initialOpenShifts));
  const [notes, setNotes] = useState(initialNotes ?? "");
  const [saving, setSaving] = useState(false);

  const onSave = async (): Promise<void> => {
    const censusNum = Number.parseInt(census, 10);
    const shiftsNum = openShifts.trim() === "" ? 0 : Number.parseInt(openShifts, 10);

    if (!Number.isFinite(censusNum) || censusNum < 0 || censusNum > 2000) {
      toast("Census must be between 0 and 2000", "error");
      return;
    }
    if (!Number.isFinite(shiftsNum) || shiftsNum < 0 || shiftsNum > 50) {
      toast("Open shifts must be between 0 and 50", "error");
      return;
    }

    setSaving(true);
    try {
      await api.saveDailyCensus({
        entry_date: today(),
        rows: [
          {
            site_id: siteId,
            census: censusNum,
            open_shifts: shiftsNum,
            notes: notes.trim() || null,
          },
        ],
      });
      toast("Saved.", "success");
      router.refresh();
    } catch (err) {
      toast(`Save failed: ${(err as Error).message}`, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid gap-3 md:grid-cols-[1fr_1fr_2fr_auto] md:items-end">
      <label className="block">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">
          Census today
        </div>
        <input
          type="number"
          min={0}
          max={2000}
          inputMode="numeric"
          value={census}
          onChange={(e) => setCensus(e.target.value)}
          disabled={saving}
          className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-base font-semibold tabular-nums"
        />
      </label>

      <label className="block">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">
          Open shifts
        </div>
        <input
          type="number"
          min={0}
          max={50}
          inputMode="numeric"
          value={openShifts}
          onChange={(e) => setOpenShifts(e.target.value)}
          disabled={saving}
          className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-base tabular-nums"
        />
      </label>

      <label className="block">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">
          Notes (optional)
        </div>
        <input
          type="text"
          maxLength={500}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          disabled={saving}
          className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          placeholder="e.g. surge unit closed for cleaning"
        />
      </label>

      <button
        type="button"
        onClick={onSave}
        disabled={saving}
        className={cn(
          "rounded-md px-5 py-2 text-sm font-semibold text-white transition-colors h-[42px]",
          saving ? "bg-slate-300 cursor-not-allowed" : "bg-slate-900 hover:bg-slate-800",
        )}
      >
        {saving ? "Saving..." : "Save"}
      </button>
    </div>
  );
}
