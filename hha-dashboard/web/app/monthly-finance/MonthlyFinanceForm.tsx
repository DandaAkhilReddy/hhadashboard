"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Card, CardHeader } from "@/components/Card";
import { toast } from "@/components/Toast";
import {
  useApiBrowser,
  type FinanceState,
  type MonthlyFinanceRowIn,
  type MonthlyFinanceRowOut,
} from "@/lib/api-browser";
import { cn } from "@/lib/format";

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

type StateRow = {
  state: FinanceState;
  collections_usd: string;
  ventra_fee_usd: string;
  ar_total_usd: string;
  ar_0_30_usd: string;
  ar_31_60_usd: string;
  ar_61_90_usd: string;
  ar_91_120_usd: string;
  ar_over_120_usd: string;
  net_collection_rate_pct: string;
  days_in_ar: string;
  notes: string;
  source_system: string | null;
  updated_at: string | null;
};

function emptyRow(state: FinanceState): StateRow {
  return {
    state,
    collections_usd: "",
    ventra_fee_usd: "",
    ar_total_usd: "",
    ar_0_30_usd: "",
    ar_31_60_usd: "",
    ar_61_90_usd: "",
    ar_91_120_usd: "",
    ar_over_120_usd: "",
    net_collection_rate_pct: "",
    days_in_ar: "",
    notes: "",
    source_system: null,
    updated_at: null,
  };
}

function fromOut(row: MonthlyFinanceRowOut): StateRow {
  return {
    state: row.state as FinanceState,
    collections_usd: row.collections_usd,
    ventra_fee_usd: row.ventra_fee_usd,
    ar_total_usd: row.ar_total_usd,
    ar_0_30_usd: row.ar_0_30_usd,
    ar_31_60_usd: row.ar_31_60_usd,
    ar_61_90_usd: row.ar_61_90_usd,
    ar_91_120_usd: row.ar_91_120_usd,
    ar_over_120_usd: row.ar_over_120_usd,
    net_collection_rate_pct: row.net_collection_rate_pct,
    days_in_ar: row.days_in_ar,
    notes: row.notes ?? "",
    source_system: row.source_system,
    updated_at: row.updated_at,
  };
}

function arSum(r: StateRow): number {
  const n = (s: string) => Number.parseFloat(s) || 0;
  return n(r.ar_0_30_usd) + n(r.ar_31_60_usd) + n(r.ar_61_90_usd) +
         n(r.ar_91_120_usd) + n(r.ar_over_120_usd);
}

function buildPayload(year: number, month: number, rows: StateRow[]): MonthlyFinanceRowIn[] {
  // Only include rows where collections_usd is non-empty (user actually entered).
  return rows
    .filter((r) => r.collections_usd.trim() !== "")
    .map((r) => ({
      state: r.state,
      collections_usd: r.collections_usd || "0",
      ventra_fee_usd: r.ventra_fee_usd || "0",
      ar_total_usd: r.ar_total_usd || "0",
      ar_0_30_usd: r.ar_0_30_usd || "0",
      ar_31_60_usd: r.ar_31_60_usd || "0",
      ar_61_90_usd: r.ar_61_90_usd || "0",
      ar_91_120_usd: r.ar_91_120_usd || "0",
      ar_over_120_usd: r.ar_over_120_usd || "0",
      net_collection_rate_pct: r.net_collection_rate_pct || "0",
      days_in_ar: r.days_in_ar || "0",
      notes: r.notes.trim() || null,
    }));
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
  const sum = arSum(row);
  const total = Number.parseFloat(row.ar_total_usd) || 0;
  const sumOk = total === 0 || Math.abs(sum - total) < 0.5;

  const tone = row.state === "FL" ? "border-indigo-200 bg-indigo-50/30" : "border-amber-200 bg-amber-50/30";

  return (
    <div className={cn("rounded-xl border p-5", tone)}>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-lg font-bold text-slate-900">{row.state}</h3>
          <div className="text-xs text-slate-500">
            {row.state === "FL" ? "Ventra fallback (until SFTP automated)" : "HHA manual (always)"}
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
        <NumField label="Collections (USD)" value={row.collections_usd}
          onChange={(v) => onChange({ collections_usd: v })} disabled={saving} />
        <NumField label="Ventra fee (USD)" value={row.ventra_fee_usd}
          onChange={(v) => onChange({ ventra_fee_usd: v })} disabled={saving}
          hint={row.state === "FL" ? "5% of collections" : "n/a (TX has no Ventra)"} />
      </div>

      <div className="mt-5 mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">
        AR Aging
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <NumField label="0–30 days" value={row.ar_0_30_usd}
          onChange={(v) => onChange({ ar_0_30_usd: v })} disabled={saving} />
        <NumField label="31–60 days" value={row.ar_31_60_usd}
          onChange={(v) => onChange({ ar_31_60_usd: v })} disabled={saving} />
        <NumField label="61–90 days" value={row.ar_61_90_usd}
          onChange={(v) => onChange({ ar_61_90_usd: v })} disabled={saving} />
        <NumField label="91–120 days" value={row.ar_91_120_usd}
          onChange={(v) => onChange({ ar_91_120_usd: v })} disabled={saving} />
        <NumField label=">120 days" value={row.ar_over_120_usd}
          onChange={(v) => onChange({ ar_over_120_usd: v })} disabled={saving} />
        <NumField label="AR total"
          value={row.ar_total_usd}
          onChange={(v) => onChange({ ar_total_usd: v })}
          disabled={saving}
          hint={
            total > 0 ? (
              sumOk ? `✓ matches sum (${sum.toLocaleString()})` :
              `⚠ buckets sum to ${sum.toLocaleString()}`
            ) : "enter buckets first"
          }
          hintTone={total > 0 && !sumOk ? "warn" : "neutral"}
        />
      </div>

      <div className="mt-5 mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">
        KPIs
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <NumField label="Net Collection Rate (%)" value={row.net_collection_rate_pct}
          onChange={(v) => onChange({ net_collection_rate_pct: v })} disabled={saving} />
        <NumField label="Days in A/R" value={row.days_in_ar}
          onChange={(v) => onChange({ days_in_ar: v })} disabled={saving}
          hint="target: 45 days" />
      </div>

      <label className="mt-4 block">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">
          Notes (optional)
        </div>
        <input
          type="text"
          maxLength={500}
          value={row.notes}
          onChange={(e) => onChange({ notes: e.target.value })}
          disabled={saving}
          className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          placeholder="e.g. Ventra report finalized 4/22; AR includes 3 disputed claims"
        />
      </label>
    </div>
  );
}

function NumField({
  label,
  value,
  onChange,
  disabled,
  hint,
  hintTone,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
  hint?: string;
  hintTone?: "neutral" | "warn";
}) {
  return (
    <label className="block">
      <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <input
        type="number"
        min={0}
        step="0.01"
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm tabular-nums"
        placeholder="0"
      />
      {hint ? (
        <div className={cn(
          "mt-1 text-[10px]",
          hintTone === "warn" ? "text-amber-700" : "text-slate-500",
        )}>{hint}</div>
      ) : null}
    </label>
  );
}

export function MonthlyFinanceForm({
  initialYear,
  initialMonth,
  initialRows,
}: {
  initialYear: number;
  initialMonth: number;
  initialRows: MonthlyFinanceRowOut[];
}) {
  const router = useRouter();
  const api = useApiBrowser();
  const [year, setYear] = useState(initialYear);
  const [month, setMonth] = useState(initialMonth);

  const initialFL = initialRows.find((r) => r.state === "FL");
  const initialTX = initialRows.find((r) => r.state === "TX");

  const [fl, setFl] = useState<StateRow>(initialFL ? fromOut(initialFL) : emptyRow("FL"));
  const [tx, setTx] = useState<StateRow>(initialTX ? fromOut(initialTX) : emptyRow("TX"));
  const [saving, setSaving] = useState(false);

  const reload = (newYear: number, newMonth: number): void => {
    // Navigate to the same page with new ?year=&month= so server fetches fresh
    const url = `/monthly-finance?year=${newYear}&month=${newMonth}`;
    router.push(url);
  };

  const onPeriodChange = (newYear: number, newMonth: number): void => {
    setYear(newYear);
    setMonth(newMonth);
    reload(newYear, newMonth);
  };

  const onSave = async (): Promise<void> => {
    const payload = buildPayload(year, month, [fl, tx]);
    if (payload.length === 0) {
      toast("Enter at least one state's collections.", "error");
      return;
    }

    setSaving(true);
    try {
      const saved = await api.saveMonthlyFinance({ year, month, rows: payload });
      // Merge saved values back so source_system + updated_at refresh
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
        title={`${MONTHS[month - 1]} ${year}`}
        owner="Sandy Collins · owner_finance"
        right={
          <div className="flex items-center gap-2">
            <select
              value={month}
              onChange={(e) => onPeriodChange(year, Number.parseInt(e.target.value, 10))}
              disabled={saving}
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            >
              {MONTHS.map((m, i) => (
                <option key={m} value={i + 1}>{m}</option>
              ))}
            </select>
            <select
              value={year}
              onChange={(e) => onPeriodChange(Number.parseInt(e.target.value, 10), month)}
              disabled={saving}
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            >
              {[year - 2, year - 1, year, year + 1].map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
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
        <StateSection row={fl} onChange={(p) => setFl((prev) => ({ ...prev, ...p }))} saving={saving} />
        <StateSection row={tx} onChange={(p) => setTx((prev) => ({ ...prev, ...p }))} saving={saving} />
      </div>
    </Card>
  );
}
