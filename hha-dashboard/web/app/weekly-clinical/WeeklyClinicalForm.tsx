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
  updated_at: string | null;
};

function emptyRow(state: ClinicalState): StateRow {
  return {
    state,
    hp_24h_pct: "",
    dc_48h_pct: "",
    avg_los_days: "",
    charts_audited_count: "",
    notes: "",
    updated_at: null,
  };
}

function fromOut(row: WeeklyClinicalRowOut): StateRow {
  return {
    state: row.state as ClinicalState,
    hp_24h_pct: row.hp_24h_pct,
    dc_48h_pct: row.dc_48h_pct,
    avg_los_days: row.avg_los_days,
    charts_audited_count: String(row.charts_audited_count),
    notes: row.notes ?? "",
    updated_at: row.updated_at,
  };
}

function buildPayload(rows: StateRow[]): WeeklyClinicalRowIn[] {
  return rows
    .filter((r) => r.hp_24h_pct.trim() !== "" || r.dc_48h_pct.trim() !== "")
    .map((r) => ({
      state: r.state,
      hp_24h_pct: r.hp_24h_pct || "0",
      dc_48h_pct: r.dc_48h_pct || "0",
      avg_los_days: r.avg_los_days || "0",
      charts_audited_count: Number.parseInt(r.charts_audited_count, 10) || 0,
      notes: r.notes.trim() || null,
    }));
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
  saving,
}: {
  row: StateRow;
  onChange: (patch: Partial<StateRow>) => void;
  saving: boolean;
}) {
  const tone =
    row.state === "FL" ? "border-indigo-200 bg-indigo-50/30" : "border-amber-200 bg-amber-50/30";

  // Quick visual cue: are H&P / DC at-or-above target?
  const hp = Number.parseFloat(row.hp_24h_pct);
  const dc = Number.parseFloat(row.dc_48h_pct);
  const hpTone =
    Number.isFinite(hp) && hp >= 95
      ? "✓ at target"
      : Number.isFinite(hp)
        ? "⚠ below 95% target"
        : undefined;
  const dcTone =
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
        {row.updated_at ? (
          <div className="text-[10px] text-slate-500 text-right">
            <div>Saved</div>
            <div>{new Date(row.updated_at).toLocaleDateString()}</div>
          </div>
        ) : null}
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <NumField
          label="H&P within 24h (%)"
          value={row.hp_24h_pct}
          onChange={(v) => onChange({ hp_24h_pct: v })}
          disabled={saving}
          max={100}
          hint={hpTone}
        />
        <NumField
          label="DC summary within 48h (%)"
          value={row.dc_48h_pct}
          onChange={(v) => onChange({ dc_48h_pct: v })}
          disabled={saving}
          max={100}
          hint={dcTone}
        />
        <NumField
          label="Average LOS (days)"
          value={row.avg_los_days}
          onChange={(v) => onChange({ avg_los_days: v })}
          disabled={saving}
          step="0.01"
          max={60}
          hint="HHA target: ≤ 4.5 days"
        />
        <NumField
          label="Charts audited"
          value={row.charts_audited_count}
          onChange={(v) => onChange({ charts_audited_count: v })}
          disabled={saving}
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
          onChange={(e) => onChange({ notes: e.target.value })}
          disabled={saving}
          className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          placeholder="e.g. Woodmont LOS still 5.8d — reviewed 3 outliers, all ICU step-downs"
        />
      </label>
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
  const [saving, setSaving] = useState(false);

  const onWeekChange = (newWeek: string): void => {
    setWeekEnding(newWeek);
    router.push(`/weekly-clinical?week_ending=${newWeek}`);
  };

  const onSave = async (): Promise<void> => {
    const payload = buildPayload([fl, tx]);
    if (payload.length === 0) {
      toast("Enter at least one state's H&P or DC %", "error");
      return;
    }
    // Date sanity check before round-trip
    const d = new Date(`${weekEnding}T00:00:00`);
    if (d.getDay() !== 0) {
      toast("Week ending must be a Sunday.", "error");
      return;
    }

    setSaving(true);
    try {
      const saved = await api.saveWeeklyClinical({
        week_ending: weekEnding,
        rows: payload,
      });
      const flSaved = saved.find((r) => r.state === "FL");
      const txSaved = saved.find((r) => r.state === "TX");
      if (flSaved) setFl(fromOut(flSaved));
      if (txSaved) setTx(fromOut(txSaved));
      toast(`Saved ${saved.length} state row${saved.length === 1 ? "" : "s"}.`, "success");
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
        owner="Dr. Aneja · Dr. Reddy · owner_clinical"
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

      <div className="grid gap-6 md:grid-cols-2">
        <StateSection
          row={fl}
          onChange={(p) => setFl((prev) => ({ ...prev, ...p }))}
          saving={saving}
        />
        <StateSection
          row={tx}
          onChange={(p) => setTx((prev) => ({ ...prev, ...p }))}
          saving={saving}
        />
      </div>
    </Card>
  );
}
