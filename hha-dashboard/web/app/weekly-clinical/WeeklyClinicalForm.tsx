"use client";

import { Card, CardHeader } from "@/components/Card";
import { toast } from "@/components/Toast";
import {
  type ClinicalState,
  type WeeklyClinicalRowIn,
  type WeeklyClinicalRowOut,
  useApiBrowser,
} from "@/lib/api-browser";
import { cn } from "@/lib/format";
import { useRouter } from "next/navigation";
import { useState } from "react";

type StateRow = {
  state: ClinicalState;
  hp_24h_pct: string;
  dc_48h_pct: string;
  avg_los_days: string;
  charts_audited_count: string;
  notes: string;
  /** Last-saved updated_at (ISO-8601). Drives the lock state. */
  savedAt: string | null;
  /** Snapshot used by Cancel to revert in-progress edits. */
  savedSnapshot: SavedSnapshot | null;
  editMode: boolean;
  saving: boolean;
  feedback: { kind: "ok" | "error"; message: string } | null;
};

type SavedSnapshot = Pick<
  StateRow,
  "state" | "hp_24h_pct" | "dc_48h_pct" | "avg_los_days" | "charts_audited_count" | "notes"
>;

function emptyRow(state: ClinicalState): StateRow {
  return {
    state,
    hp_24h_pct: "",
    dc_48h_pct: "",
    avg_los_days: "",
    charts_audited_count: "",
    notes: "",
    savedAt: null,
    savedSnapshot: null,
    editMode: true,
    saving: false,
    feedback: null,
  };
}

function fromOut(row: WeeklyClinicalRowOut): StateRow {
  const snapshot: SavedSnapshot = {
    state: row.state as ClinicalState,
    hp_24h_pct: row.hp_24h_pct,
    dc_48h_pct: row.dc_48h_pct,
    avg_los_days: row.avg_los_days,
    charts_audited_count: String(row.charts_audited_count),
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

function buildSinglePayload(r: StateRow): WeeklyClinicalRowIn {
  return {
    state: r.state,
    hp_24h_pct: r.hp_24h_pct || "0",
    dc_48h_pct: r.dc_48h_pct || "0",
    avg_los_days: r.avg_los_days || "0",
    charts_audited_count: Number.parseInt(r.charts_audited_count, 10) || 0,
    notes: r.notes.trim() || null,
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
  step = "0.1",
  max,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
  hint?: string;
  step?: string;
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
        step={step}
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm tabular-nums"
        placeholder="0"
      />
      {hint ? <div className="mt-1 text-[10px] text-slate-500">{hint}</div> : null}
    </label>
  );
}

function StateSection({
  row,
  onChange,
  onEdit,
  onCancel,
  onSave,
}: {
  row: StateRow;
  onChange: (patch: Partial<StateRow>) => void;
  onEdit: () => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  const tone =
    row.state === "FL" ? "border-indigo-200 bg-indigo-50/30" : "border-amber-200 bg-amber-50/30";

  if (!row.editMode) {
    return (
      <div className={cn("rounded-xl border p-5", tone)}>
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold text-slate-900">
              <span className="mr-2 text-emerald-600" aria-hidden>
                ✓
              </span>
              {row.state}
            </h3>
            <div className="text-xs text-slate-500">
              {row.state === "FL" ? "7 sites" : "4 sites"}
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

        <dl className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          <div>
            <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
              H&amp;P 24h
            </dt>
            <dd
              className={cn(
                "mt-0.5 text-base font-bold tabular-nums",
                Number.parseFloat(row.hp_24h_pct) >= 95 ? "text-emerald-700" : "text-amber-700",
              )}
            >
              {row.hp_24h_pct}%
            </dd>
          </div>
          <div>
            <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
              DC 48h
            </dt>
            <dd
              className={cn(
                "mt-0.5 text-base font-bold tabular-nums",
                Number.parseFloat(row.dc_48h_pct) >= 90 ? "text-emerald-700" : "text-amber-700",
              )}
            >
              {row.dc_48h_pct}%
            </dd>
          </div>
          <div>
            <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
              Avg LOS
            </dt>
            <dd className="mt-0.5 text-base font-bold tabular-nums text-slate-900">
              {row.avg_los_days}d
            </dd>
          </div>
          <div>
            <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
              Charts
            </dt>
            <dd className="mt-0.5 text-base font-bold tabular-nums text-slate-900">
              {row.charts_audited_count}
            </dd>
          </div>
        </dl>

        <div className="mt-3 text-[10px] uppercase tracking-wider text-slate-400">
          Saved {formatSavedAt(row.savedAt)}
        </div>

        {row.notes ? (
          <div className="mt-2 rounded-md bg-white/60 px-3 py-2 text-xs text-slate-600">
            <span className="font-semibold text-slate-500">Notes:</span> {row.notes}
          </div>
        ) : null}

        {row.feedback?.kind === "ok" ? (
          <div className="mt-3 text-xs text-emerald-700">{row.feedback.message}</div>
        ) : null}
      </div>
    );
  }

  // Quick visual cue while editing.
  const hp = Number.parseFloat(row.hp_24h_pct);
  const dc = Number.parseFloat(row.dc_48h_pct);
  const hpHint =
    Number.isFinite(hp) && hp >= 95
      ? "✓ at target"
      : Number.isFinite(hp)
        ? "⚠ below 95% target"
        : undefined;
  const dcHint =
    Number.isFinite(dc) && dc >= 90
      ? "✓ at target"
      : Number.isFinite(dc)
        ? "⚠ below 90% target"
        : undefined;

  return (
    <div className={cn("rounded-xl border p-5", tone)}>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-lg font-bold text-slate-900">{row.state}</h3>
          <div className="text-xs text-slate-500">
            {row.state === "FL"
              ? "7 sites — Westside, Woodmont, JFK Main + North, Palms West, University, Jackson"
              : "4 sites — Bay, Doctors, Huntsville, Corpus"}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onSave}
            disabled={row.saving}
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-semibold text-white transition-colors",
              row.saving ? "bg-slate-300 cursor-not-allowed" : "bg-indigo-600 hover:bg-indigo-700",
            )}
          >
            {row.saving ? "Saving…" : "Save"}
          </button>
          {row.savedSnapshot !== null ? (
            <button
              type="button"
              onClick={onCancel}
              disabled={row.saving}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:border-slate-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Cancel
            </button>
          ) : null}
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <NumField
          label="H&P within 24h (%)"
          value={row.hp_24h_pct}
          onChange={(v) => onChange({ hp_24h_pct: v, feedback: null })}
          disabled={row.saving}
          max={100}
          hint={hpHint}
        />
        <NumField
          label="DC summary within 48h (%)"
          value={row.dc_48h_pct}
          onChange={(v) => onChange({ dc_48h_pct: v, feedback: null })}
          disabled={row.saving}
          max={100}
          hint={dcHint}
        />
        <NumField
          label="Average LOS (days)"
          value={row.avg_los_days}
          onChange={(v) => onChange({ avg_los_days: v, feedback: null })}
          disabled={row.saving}
          step="0.01"
          max={60}
          hint="HHA target: ≤ 4.5 days"
        />
        <NumField
          label="Charts audited"
          value={row.charts_audited_count}
          onChange={(v) => onChange({ charts_audited_count: v, feedback: null })}
          disabled={row.saving}
          step="1"
          hint="sample size for the % above"
        />
      </div>

      <label className="mt-4 block">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">
          Notes (optional)
        </div>
        <input
          type="text"
          maxLength={1000}
          value={row.notes}
          onChange={(e) => onChange({ notes: e.target.value, feedback: null })}
          disabled={row.saving}
          className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          placeholder="e.g. Woodmont LOS still 5.8d — reviewed 3 outliers, all ICU step-downs"
        />
      </label>

      {row.feedback?.kind === "error" ? (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {row.feedback.message}
        </div>
      ) : null}
    </div>
  );
}

export function WeeklyClinicalForm({
  initialWeekEnding,
  initialRows,
}: {
  initialWeekEnding: string;
  initialRows: WeeklyClinicalRowOut[];
}) {
  const router = useRouter();
  const api = useApiBrowser();
  const [weekEnding, setWeekEnding] = useState(initialWeekEnding);

  const initialFL = initialRows.find((r) => r.state === "FL");
  const initialTX = initialRows.find((r) => r.state === "TX");

  const [fl, setFl] = useState<StateRow>(initialFL ? fromOut(initialFL) : emptyRow("FL"));
  const [tx, setTx] = useState<StateRow>(initialTX ? fromOut(initialTX) : emptyRow("TX"));

  function setRow(state: ClinicalState, updater: (prev: StateRow) => StateRow): void {
    if (state === "FL") setFl(updater);
    else setTx(updater);
  }

  const onWeekChange = (newWeek: string): void => {
    setWeekEnding(newWeek);
    router.push(`/weekly-clinical?week_ending=${newWeek}`);
  };

  function onEdit(state: ClinicalState): void {
    setRow(state, (r) => ({
      ...r,
      ...(r.savedSnapshot ?? {}),
      editMode: true,
      feedback: null,
    }));
  }

  function onCancel(state: ClinicalState): void {
    setRow(state, (r) => {
      if (r.savedSnapshot === null) return r;
      return {
        ...r,
        ...r.savedSnapshot,
        editMode: false,
        feedback: null,
      };
    });
  }

  async function onSave(state: ClinicalState): Promise<void> {
    const current = state === "FL" ? fl : tx;
    if (current.hp_24h_pct.trim() === "" && current.dc_48h_pct.trim() === "") {
      setRow(state, (r) => ({
        ...r,
        feedback: { kind: "error", message: "Enter at least H&P or DC % to save." },
      }));
      return;
    }
    const d = new Date(`${weekEnding}T00:00:00`);
    if (d.getDay() !== 0) {
      setRow(state, (r) => ({
        ...r,
        feedback: { kind: "error", message: "Week ending must be a Sunday." },
      }));
      return;
    }

    setRow(state, (r) => ({ ...r, saving: true, feedback: null }));
    try {
      const saved = await api.saveWeeklyClinical({
        week_ending: weekEnding,
        rows: [buildSinglePayload(current)],
      });
      const echoed = saved.find((r) => r.state === state);
      if (!echoed) {
        setRow(state, (r) => ({
          ...r,
          saving: false,
          feedback: {
            kind: "error",
            message: "Save succeeded but server didn't echo this row — refresh.",
          },
        }));
        return;
      }
      setRow(state, () => fromOut(echoed));
      toast(`Saved ${state} clinical for week of ${weekEnding}.`, "success");
      router.refresh();
    } catch (err) {
      setRow(state, (r) => ({
        ...r,
        saving: false,
        feedback: { kind: "error", message: `Save failed: ${(err as Error).message}` },
      }));
    }
  }

  return (
    <Card>
      <CardHeader
        title={`Week ending ${new Date(`${weekEnding}T00:00:00`).toLocaleDateString("en-US", {
          weekday: "short",
          month: "short",
          day: "numeric",
          year: "numeric",
        })}`}
        owner="Dr. Aneja · Dr. Reddy · owner_clinical"
        right={
          <input
            type="date"
            value={weekEnding}
            onChange={(e) => onWeekChange(e.target.value)}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
          />
        }
      />

      <div className="grid gap-6 md:grid-cols-2">
        <StateSection
          row={fl}
          onChange={(p) => setRow("FL", (r) => ({ ...r, ...p }))}
          onEdit={() => onEdit("FL")}
          onCancel={() => onCancel("FL")}
          onSave={() => onSave("FL")}
        />
        <StateSection
          row={tx}
          onChange={(p) => setRow("TX", (r) => ({ ...r, ...p }))}
          onEdit={() => onEdit("TX")}
          onCancel={() => onCancel("TX")}
          onSave={() => onSave("TX")}
        />
      </div>
    </Card>
  );
}
