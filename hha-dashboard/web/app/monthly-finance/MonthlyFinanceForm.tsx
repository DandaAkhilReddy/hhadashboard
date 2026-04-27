"use client";

import { Card, CardHeader } from "@/components/Card";
import { toast } from "@/components/Toast";
import {
  type FinanceState,
  type MonthlyFinanceRowIn,
  type MonthlyFinanceRowOut,
  useApiBrowser,
} from "@/lib/api-browser";
import { cn } from "@/lib/format";
import { useRouter } from "next/navigation";
import { useState } from "react";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * Per-state row state machine.
 *
 * `savedAt`/`savedSnapshot` carry the last-persisted view of this row;
 * non-null `savedAt` = "this state has been entered for the period" =
 * row renders as a locked summary with [Edit].
 *
 * `editMode` toggles between locked summary and the full input grid.
 * Snapshot is used to revert on Cancel.
 */
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
  /** Last-saved updated_at (ISO-8601 from the API). Drives the lock state. */
  savedAt: string | null;
  /** Snapshot used by Cancel to revert in-progress edits. */
  savedSnapshot: SavedSnapshot | null;
  editMode: boolean;
  saving: boolean;
  feedback: { kind: "ok" | "error"; message: string } | null;
};

type SavedSnapshot = Omit<
  StateRow,
  "savedAt" | "savedSnapshot" | "editMode" | "saving" | "feedback"
>;

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
    savedAt: null,
    savedSnapshot: null,
    // Never-saved rows start unlocked so the user can fill them in.
    editMode: true,
    saving: false,
    feedback: null,
  };
}

function fromOut(row: MonthlyFinanceRowOut): StateRow {
  const snapshot: SavedSnapshot = {
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
  };
  return {
    ...snapshot,
    savedAt: row.updated_at,
    savedSnapshot: snapshot,
    // Already-entered rows start LOCKED (the user must click Edit to change).
    editMode: false,
    saving: false,
    feedback: null,
  };
}

function arSum(r: {
  ar_0_30_usd: string;
  ar_31_60_usd: string;
  ar_61_90_usd: string;
  ar_91_120_usd: string;
  ar_over_120_usd: string;
}): number {
  const n = (s: string) => Number.parseFloat(s) || 0;
  return (
    n(r.ar_0_30_usd) +
    n(r.ar_31_60_usd) +
    n(r.ar_61_90_usd) +
    n(r.ar_91_120_usd) +
    n(r.ar_over_120_usd)
  );
}

function buildSinglePayload(r: StateRow): MonthlyFinanceRowIn {
  return {
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

function compactUsd(value: string): string {
  const n = Number.parseFloat(value);
  if (!Number.isFinite(n)) return "$—";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
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
    // Locked summary — condensed KPIs + Edit button.
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
              {row.state === "FL"
                ? "Ventra fallback (until SFTP automated)"
                : "HHA manual (always)"}
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

        <dl className="grid grid-cols-2 gap-3 text-sm md:grid-cols-3">
          <div>
            <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
              Collections
            </dt>
            <dd className="mt-0.5 text-base font-bold tabular-nums text-slate-900">
              {compactUsd(row.collections_usd)}
            </dd>
          </div>
          <div>
            <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
              Net Coll. Rate
            </dt>
            <dd className="mt-0.5 text-base font-bold tabular-nums text-slate-900">
              {row.net_collection_rate_pct}%
            </dd>
          </div>
          <div>
            <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
              Days in A/R
            </dt>
            <dd className="mt-0.5 text-base font-bold tabular-nums text-slate-900">
              {row.days_in_ar}d
            </dd>
          </div>
          <div>
            <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
              AR total
            </dt>
            <dd className="mt-0.5 text-sm tabular-nums text-slate-700">
              {compactUsd(row.ar_total_usd)}
            </dd>
          </div>
          <div className="md:col-span-2">
            <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Saved</dt>
            <dd className="mt-0.5 text-xs text-slate-600">{formatSavedAt(row.savedAt)}</dd>
          </div>
        </dl>

        {row.notes ? (
          <div className="mt-3 rounded-md bg-white/60 px-3 py-2 text-xs text-slate-600">
            <span className="font-semibold text-slate-500">Notes:</span> {row.notes}
          </div>
        ) : null}

        {row.feedback?.kind === "ok" ? (
          <div className="mt-3 text-xs text-emerald-700">{row.feedback.message}</div>
        ) : null}
      </div>
    );
  }

  // Unlocked — full input grid.
  const sum = arSum(row);
  const total = Number.parseFloat(row.ar_total_usd) || 0;
  const sumOk = total === 0 || Math.abs(sum - total) < 0.5;

  return (
    <div className={cn("rounded-xl border p-5", tone)}>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-lg font-bold text-slate-900">{row.state}</h3>
          <div className="text-xs text-slate-500">
            {row.state === "FL" ? "Ventra fallback (until SFTP automated)" : "HHA manual (always)"}
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
          label="Collections (USD)"
          value={row.collections_usd}
          onChange={(v) => onChange({ collections_usd: v, feedback: null })}
          disabled={row.saving}
        />
        <NumField
          label="Ventra fee (USD)"
          value={row.ventra_fee_usd}
          onChange={(v) => onChange({ ventra_fee_usd: v, feedback: null })}
          disabled={row.saving}
          hint={row.state === "FL" ? "5% of collections" : "n/a (TX has no Ventra)"}
        />
      </div>

      <div className="mt-5 mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">
        AR Aging
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <NumField
          label="0–30 days"
          value={row.ar_0_30_usd}
          onChange={(v) => onChange({ ar_0_30_usd: v, feedback: null })}
          disabled={row.saving}
        />
        <NumField
          label="31–60 days"
          value={row.ar_31_60_usd}
          onChange={(v) => onChange({ ar_31_60_usd: v, feedback: null })}
          disabled={row.saving}
        />
        <NumField
          label="61–90 days"
          value={row.ar_61_90_usd}
          onChange={(v) => onChange({ ar_61_90_usd: v, feedback: null })}
          disabled={row.saving}
        />
        <NumField
          label="91–120 days"
          value={row.ar_91_120_usd}
          onChange={(v) => onChange({ ar_91_120_usd: v, feedback: null })}
          disabled={row.saving}
        />
        <NumField
          label=">120 days"
          value={row.ar_over_120_usd}
          onChange={(v) => onChange({ ar_over_120_usd: v, feedback: null })}
          disabled={row.saving}
        />
        <NumField
          label="AR total"
          value={row.ar_total_usd}
          onChange={(v) => onChange({ ar_total_usd: v, feedback: null })}
          disabled={row.saving}
          hint={
            total > 0
              ? sumOk
                ? `✓ matches sum (${sum.toLocaleString()})`
                : `⚠ buckets sum to ${sum.toLocaleString()}`
              : "enter buckets first"
          }
          hintTone={total > 0 && !sumOk ? "warn" : "neutral"}
        />
      </div>

      <div className="mt-5 mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">
        KPIs
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <NumField
          label="Net Collection Rate (%)"
          value={row.net_collection_rate_pct}
          onChange={(v) => onChange({ net_collection_rate_pct: v, feedback: null })}
          disabled={row.saving}
        />
        <NumField
          label="Days in A/R"
          value={row.days_in_ar}
          onChange={(v) => onChange({ days_in_ar: v, feedback: null })}
          disabled={row.saving}
          hint="target: 45 days"
        />
      </div>

      <label className="mt-4 block">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">
          Notes (optional)
        </div>
        <input
          type="text"
          maxLength={500}
          value={row.notes}
          onChange={(e) => onChange({ notes: e.target.value, feedback: null })}
          disabled={row.saving}
          className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          placeholder="e.g. Ventra report finalized 4/22; AR includes 3 disputed claims"
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
        <div
          className={cn(
            "mt-1 text-[10px]",
            hintTone === "warn" ? "text-amber-700" : "text-slate-500",
          )}
        >
          {hint}
        </div>
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

  function setRow(state: FinanceState, updater: (prev: StateRow) => StateRow): void {
    if (state === "FL") setFl(updater);
    else setTx(updater);
  }

  const onPeriodChange = (newYear: number, newMonth: number): void => {
    setYear(newYear);
    setMonth(newMonth);
    router.push(`/monthly-finance?year=${newYear}&month=${newMonth}`);
  };

  function onEdit(state: FinanceState): void {
    setRow(state, (r) => ({
      ...r,
      // Reset live fields to last-saved snapshot in case prior edits were
      // abandoned without Cancel.
      ...(r.savedSnapshot ?? {}),
      editMode: true,
      feedback: null,
    }));
  }

  function onCancel(state: FinanceState): void {
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

  async function onSave(state: FinanceState): Promise<void> {
    const current = state === "FL" ? fl : tx;
    if (current.collections_usd.trim() === "") {
      setRow(state, (r) => ({
        ...r,
        feedback: { kind: "error", message: "Enter at least Collections to save." },
      }));
      return;
    }
    setRow(state, (r) => ({ ...r, saving: true, feedback: null }));
    try {
      const saved = await api.saveMonthlyFinance({
        year,
        month,
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
      toast(`Saved ${state} for ${MONTHS[month - 1]} ${year}.`, "success");
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
        title={`${MONTHS[month - 1]} ${year}`}
        owner="Sandy Collins · owner_finance"
        right={
          <div className="flex items-center gap-2">
            <select
              value={month}
              onChange={(e) => onPeriodChange(year, Number.parseInt(e.target.value, 10))}
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            >
              {MONTHS.map((m, i) => (
                <option key={m} value={i + 1}>
                  {m}
                </option>
              ))}
            </select>
            <select
              value={year}
              onChange={(e) => onPeriodChange(Number.parseInt(e.target.value, 10), month)}
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            >
              {[year - 2, year - 1, year, year + 1].map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </div>
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
