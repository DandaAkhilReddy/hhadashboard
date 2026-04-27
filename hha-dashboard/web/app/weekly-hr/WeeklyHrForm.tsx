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
};

type DraftState = Draft & {
  /** Last-saved updated_at (ISO-8601). Drives the lock state. */
  savedAt: string | null;
  /** Snapshot used by Cancel to revert in-progress edits. */
  savedSnapshot: Draft | null;
  editMode: boolean;
  saving: boolean;
  feedback: { kind: "ok" | "error"; message: string } | null;
};

function emptyDraft(): DraftState {
  return {
    headcount_w2: "",
    headcount_1099: "",
    open_positions_total: "",
    terminations_90d_count: "",
    below_fmv_count: "",
    notes: "",
    savedAt: null,
    savedSnapshot: null,
    editMode: true,
    saving: false,
    feedback: null,
  };
}

function fromOut(row: WeeklyHrOut | null): DraftState {
  if (!row) return emptyDraft();
  const snapshot: Draft = {
    headcount_w2: String(row.headcount_w2),
    headcount_1099: String(row.headcount_1099),
    open_positions_total: String(row.open_positions_total),
    terminations_90d_count: String(row.terminations_90d_count),
    below_fmv_count: String(row.below_fmv_count),
    notes: row.notes ?? "",
  };
  return {
    ...snapshot,
    savedAt: row.updated_at,
    savedSnapshot: snapshot,
    editMode: false,
    saving: false,
    feedback: null,
  };
}

function formatSavedAt(iso: string | null): string {
  if (iso === null) return "";
  const d = new Date(iso);
  return `${d.toLocaleDateString()} at ${d.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  })}`;
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
  const [draft, setDraft] = useState<DraftState>(fromOut(initial));

  const update = (patch: Partial<DraftState>): void => {
    setDraft((prev) => ({ ...prev, ...patch }));
  };

  const onWeekChange = (newWeek: string): void => {
    setWeekEnding(newWeek);
    router.push(`/weekly-hr?week_ending=${newWeek}`);
  };

  const w2 = Number.parseInt(draft.headcount_w2, 10) || 0;
  const c1099 = Number.parseInt(draft.headcount_1099, 10) || 0;
  const total = w2 + c1099;
  const terms = Number.parseInt(draft.terminations_90d_count, 10) || 0;
  const turnoverPct = total > 0 ? ((terms / total) * 100).toFixed(1) : "—";

  function onEdit(): void {
    setDraft((prev) => ({
      ...prev,
      ...(prev.savedSnapshot ?? {}),
      editMode: true,
      feedback: null,
    }));
  }

  function onCancel(): void {
    setDraft((prev) => {
      if (prev.savedSnapshot === null) return prev;
      return {
        ...prev,
        ...prev.savedSnapshot,
        editMode: false,
        feedback: null,
      };
    });
  }

  async function onSave(): Promise<void> {
    if (draft.headcount_w2.trim() === "" && draft.headcount_1099.trim() === "") {
      update({ feedback: { kind: "error", message: "Enter at least one headcount value." } });
      return;
    }
    const d = new Date(`${weekEnding}T00:00:00`);
    if (d.getDay() !== 0) {
      update({ feedback: { kind: "error", message: "Week ending must be a Sunday." } });
      return;
    }

    update({ saving: true, feedback: null });
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
      toast(`Saved HR for week of ${weekEnding}.`, "success");
      router.refresh();
    } catch (err) {
      update({
        saving: false,
        feedback: { kind: "error", message: `Save failed: ${(err as Error).message}` },
      });
    }
  }

  // ---------- Locked summary ----------

  if (!draft.editMode) {
    const savedW2 = Number.parseInt(draft.headcount_w2, 10) || 0;
    const saved1099 = Number.parseInt(draft.headcount_1099, 10) || 0;
    const savedTotal = savedW2 + saved1099;
    const savedTerms = Number.parseInt(draft.terminations_90d_count, 10) || 0;
    const savedTurnover = savedTotal > 0 ? `${((savedTerms / savedTotal) * 100).toFixed(1)}%` : "—";

    return (
      <Card>
        <CardHeader
          title={`Week ending ${new Date(`${weekEnding}T00:00:00`).toLocaleDateString("en-US", {
            weekday: "short",
            month: "short",
            day: "numeric",
            year: "numeric",
          })}`}
          owner="Andrea · owner_hr"
          right={
            <input
              type="date"
              value={weekEnding}
              onChange={(e) => onWeekChange(e.target.value)}
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            />
          }
        />
        <div className="rounded-xl border border-emerald-200 bg-emerald-50/30 p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-lg font-bold text-slate-900">
                <span className="mr-2 text-emerald-600" aria-hidden>
                  ✓
                </span>
                HR — saved
              </h3>
              <div className="text-xs text-slate-500">
                Last saved {formatSavedAt(draft.savedAt)}
              </div>
            </div>
            <button
              type="button"
              onClick={onEdit}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:border-indigo-400 hover:text-indigo-700"
            >
              Edit
            </button>
          </div>

          <dl className="grid grid-cols-2 gap-3 text-sm md:grid-cols-3 lg:grid-cols-6">
            <div>
              <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">W-2</dt>
              <dd className="mt-0.5 text-base font-bold tabular-nums text-slate-900">{savedW2}</dd>
            </div>
            <div>
              <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                1099
              </dt>
              <dd className="mt-0.5 text-base font-bold tabular-nums text-slate-900">
                {saved1099}
              </dd>
            </div>
            <div>
              <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Total
              </dt>
              <dd className="mt-0.5 text-base font-bold tabular-nums text-slate-900">
                {savedTotal}
              </dd>
            </div>
            <div>
              <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Open
              </dt>
              <dd className="mt-0.5 text-base font-bold tabular-nums text-slate-900">
                {Number.parseInt(draft.open_positions_total, 10) || 0}
              </dd>
            </div>
            <div>
              <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                90d Term.
              </dt>
              <dd className="mt-0.5 text-base font-bold tabular-nums text-slate-900">
                {savedTerms}
              </dd>
            </div>
            <div>
              <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Turnover
              </dt>
              <dd
                className={cn(
                  "mt-0.5 text-base font-bold tabular-nums",
                  savedTotal > 0 && savedTerms / savedTotal > 0.1
                    ? "text-red-600"
                    : "text-slate-900",
                )}
              >
                {savedTurnover}
              </dd>
            </div>
          </dl>

          {draft.notes ? (
            <div className="mt-3 rounded-md bg-white/60 px-3 py-2 text-xs text-slate-600">
              <span className="font-semibold text-slate-500">Notes:</span> {draft.notes}
            </div>
          ) : null}

          {draft.feedback?.kind === "ok" ? (
            <div className="mt-3 text-xs text-emerald-700">{draft.feedback.message}</div>
          ) : null}
        </div>
      </Card>
    );
  }

  // ---------- Editable input grid ----------

  return (
    <Card>
      <CardHeader
        title={`Week ending ${new Date(`${weekEnding}T00:00:00`).toLocaleDateString("en-US", {
          weekday: "short",
          month: "short",
          day: "numeric",
          year: "numeric",
        })}`}
        owner="Andrea · owner_hr"
        right={
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={weekEnding}
              onChange={(e) => onWeekChange(e.target.value)}
              disabled={draft.saving}
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            />
            <button
              type="button"
              onClick={onSave}
              disabled={draft.saving}
              className={cn(
                "rounded-md px-4 py-1.5 text-sm font-semibold text-white transition-colors",
                draft.saving
                  ? "bg-slate-300 cursor-not-allowed"
                  : "bg-indigo-600 hover:bg-indigo-700",
              )}
            >
              {draft.saving ? "Saving…" : "Save"}
            </button>
            {draft.savedSnapshot !== null ? (
              <button
                type="button"
                onClick={onCancel}
                disabled={draft.saving}
                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 hover:border-slate-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Cancel
              </button>
            ) : null}
          </div>
        }
      />

      <div className="grid gap-6 md:grid-cols-[2fr_1fr]">
        <div className="rounded-xl border border-slate-200 bg-slate-50/30 p-5">
          <div className="mb-3 text-xs font-bold uppercase tracking-wider text-slate-500">
            Headcount
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <NumField
              label="W-2 employees"
              value={draft.headcount_w2}
              onChange={(v) => update({ headcount_w2: v, feedback: null })}
              disabled={draft.saving}
              max={10000}
            />
            <NumField
              label="1099 contractors"
              value={draft.headcount_1099}
              onChange={(v) => update({ headcount_1099: v, feedback: null })}
              disabled={draft.saving}
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
              onChange={(v) => update({ open_positions_total: v, feedback: null })}
              disabled={draft.saving}
              max={1000}
            />
            <NumField
              label="90-day terminations"
              value={draft.terminations_90d_count}
              onChange={(v) => update({ terminations_90d_count: v, feedback: null })}
              disabled={draft.saving}
              max={1000}
              hint="rolling 90-day window"
            />
            <NumField
              label="Below FMV"
              value={draft.below_fmv_count}
              onChange={(v) => update({ below_fmv_count: v, feedback: null })}
              disabled={draft.saving}
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
              onChange={(e) => update({ notes: e.target.value, feedback: null })}
              disabled={draft.saving}
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
              placeholder="e.g. Westside MD search active; 2 offers out for hospitalist roles"
            />
          </label>

          {draft.feedback?.kind === "error" ? (
            <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {draft.feedback.message}
            </div>
          ) : null}
        </div>

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
          {draft.savedAt ? (
            <div className="mt-4 border-t border-slate-100 pt-3 text-[10px] text-slate-500">
              Last saved {formatSavedAt(draft.savedAt)}
            </div>
          ) : null}
        </div>
      </div>
    </Card>
  );
}
