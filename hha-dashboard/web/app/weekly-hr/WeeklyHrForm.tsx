"use client";

import { Card, CardHeader } from "@/components/Card";
import { toast } from "@/components/Toast";
import { type WeeklyHrOut, useApiBrowser } from "@/lib/api-browser";
import { cn } from "@/lib/format";
import { useRouter } from "next/navigation";
import { useState } from "react";

type Draft = {
  headcount_w2: string;
  headcount_1099: string;
  open_positions_total: string;
  terminations_90d_count: string;
  below_fmv_count: string;
  notes: string;
  updated_at: string | null;
};

function fromOut(row: WeeklyHrOut | null): Draft {
  if (!row) {
    return {
      headcount_w2: "",
      headcount_1099: "",
      open_positions_total: "",
      terminations_90d_count: "",
      below_fmv_count: "",
      notes: "",
      updated_at: null,
    };
  }
  return {
    headcount_w2: String(row.headcount_w2),
    headcount_1099: String(row.headcount_1099),
    open_positions_total: String(row.open_positions_total),
    terminations_90d_count: String(row.terminations_90d_count),
    below_fmv_count: String(row.below_fmv_count),
    notes: row.notes ?? "",
    updated_at: row.updated_at,
  };
}

function NumField({
  label,
  value,
  onChange,
  disabled,
  hint,
  max,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
  hint?: string;
  max?: number;
}) {
  return (
    <label className="block">
      <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <input
        type="number"
        min={0}
        max={max}
        step={1}
        inputMode="numeric"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-base font-semibold tabular-nums"
        placeholder="0"
      />
      {hint ? <div className="mt-1 text-[10px] text-slate-500">{hint}</div> : null}
    </label>
  );
}

export function WeeklyHrForm({
  initialWeekEnding,
  initial,
}: {
  initialWeekEnding: string;
  initial: WeeklyHrOut | null;
}) {
  const router = useRouter();
  const api = useApiBrowser();
  const [weekEnding, setWeekEnding] = useState(initialWeekEnding);
  const [draft, setDraft] = useState<Draft>(fromOut(initial));
  const [saving, setSaving] = useState(false);

  const onWeekChange = (newWeek: string): void => {
    setWeekEnding(newWeek);
    router.push(`/weekly-hr?week_ending=${newWeek}`);
  };

  const update = (patch: Partial<Draft>): void => {
    setDraft((prev) => ({ ...prev, ...patch }));
  };

  const w2 = Number.parseInt(draft.headcount_w2, 10) || 0;
  const c1099 = Number.parseInt(draft.headcount_1099, 10) || 0;
  const total = w2 + c1099;
  const terms = Number.parseInt(draft.terminations_90d_count, 10) || 0;
  const turnoverPct = total > 0 ? ((terms / total) * 100).toFixed(1) : "—";

  const onSave = async (): Promise<void> => {
    if (draft.headcount_w2.trim() === "" && draft.headcount_1099.trim() === "") {
      toast("Enter at least one headcount value.", "error");
      return;
    }
    const d = new Date(`${weekEnding}T00:00:00`);
    if (d.getDay() !== 0) {
      toast("Week ending must be a Sunday.", "error");
      return;
    }

    setSaving(true);
    try {
      const saved = await api.saveWeeklyHr({
        week_ending: weekEnding,
        headcount_w2: w2,
        headcount_1099: c1099,
        open_positions_total: Number.parseInt(draft.open_positions_total, 10) || 0,
        terminations_90d_count: terms,
        below_fmv_count: Number.parseInt(draft.below_fmv_count, 10) || 0,
        notes: draft.notes.trim() || null,
      });
      setDraft(fromOut(saved));
      toast("Saved.", "success");
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
        title={`Week ending ${new Date(`${weekEnding}T00:00:00`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" })}`}
        owner="Andrea · owner_hr"
        right={
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={weekEnding}
              onChange={(e) => onWeekChange(e.target.value)}
              disabled={saving}
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            />
            <button
              type="button"
              onClick={onSave}
              disabled={saving}
              className={cn(
                "rounded-md px-4 py-1.5 text-sm font-semibold text-white transition-colors",
                saving ? "bg-slate-300 cursor-not-allowed" : "bg-slate-900 hover:bg-slate-800",
              )}
            >
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        }
      />

      <div className="grid gap-6 md:grid-cols-[2fr_1fr]">
        {/* Inputs */}
        <div className="rounded-xl border border-slate-200 bg-slate-50/30 p-5">
          <div className="mb-3 text-xs font-bold uppercase tracking-wider text-slate-500">
            Headcount
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <NumField
              label="W-2 employees"
              value={draft.headcount_w2}
              onChange={(v) => update({ headcount_w2: v })}
              disabled={saving}
              max={10000}
            />
            <NumField
              label="1099 contractors"
              value={draft.headcount_1099}
              onChange={(v) => update({ headcount_1099: v })}
              disabled={saving}
              max={10000}
            />
          </div>

          <div className="mt-5 mb-3 text-xs font-bold uppercase tracking-wider text-slate-500">
            Pipeline & Risk
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <NumField
              label="Open positions"
              value={draft.open_positions_total}
              onChange={(v) => update({ open_positions_total: v })}
              disabled={saving}
              max={1000}
            />
            <NumField
              label="90-day terminations"
              value={draft.terminations_90d_count}
              onChange={(v) => update({ terminations_90d_count: v })}
              disabled={saving}
              max={1000}
              hint="rolling 90-day window"
            />
            <NumField
              label="Below FMV"
              value={draft.below_fmv_count}
              onChange={(v) => update({ below_fmv_count: v })}
              disabled={saving}
              max={10000}
              hint="comp vs market median"
            />
          </div>

          <label className="mt-5 block">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">
              Notes (optional)
            </div>
            <input
              type="text"
              maxLength={1000}
              value={draft.notes}
              onChange={(e) => update({ notes: e.target.value })}
              disabled={saving}
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
              placeholder="e.g. Westside MD search active; 2 offers out for hospitalist roles"
            />
          </label>
        </div>

        {/* Live derived values panel */}
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="mb-3 text-xs font-bold uppercase tracking-wider text-slate-500">
            Derived (live)
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
            <dt className="text-slate-500">Total headcount</dt>
            <dd className="font-bold text-slate-900 tabular-nums">{total}</dd>
            <dt className="text-slate-500">Turnover (90d)</dt>
            <dd
              className={cn(
                "font-bold tabular-nums",
                total > 0 && terms / total > 0.1 ? "text-red-600" : "text-slate-900",
              )}
            >
              {turnoverPct}
              {total > 0 ? "%" : ""}
            </dd>
            <dt className="text-slate-500">W-2 / 1099 mix</dt>
            <dd className="text-slate-700 tabular-nums">
              {total > 0
                ? `${Math.round((w2 / total) * 100)}% / ${Math.round((c1099 / total) * 100)}%`
                : "—"}
            </dd>
          </dl>
          {draft.updated_at ? (
            <div className="mt-4 border-t border-slate-100 pt-3 text-[10px] text-slate-500">
              Last saved {new Date(draft.updated_at).toLocaleString()}
            </div>
          ) : null}
        </div>
      </div>
    </Card>
  );
}
