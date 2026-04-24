"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Card, CardHeader } from "@/components/Card";
import { FileDrop } from "@/components/FileDrop";
import { toast } from "@/components/Toast";
import { api, type FileType, type UploadRow } from "@/lib/api-client";
import { cn } from "@/lib/format";

// ---- Client-side filename → file_type inference ----

const FILE_TYPE_LABELS: Record<FileType, string> = {
  census_pdf: "Census PDF",
  finance_xlsx: "Finance (Excel)",
  clinical_xlsx: "Clinical audit (Excel)",
  hr_xlsx: "HR export (Excel)",
  unknown: "— Pick type —",
};

function inferType(filename: string): FileType | null {
  const name = filename.toLowerCase();
  if (/census/.test(name) && /\.pdf$/.test(name)) return "census_pdf";
  if (/(collection|finance|revenue|ar[-_])/.test(name) && /\.xlsx?$/.test(name))
    return "finance_xlsx";
  if (/(clinical|audit|chart[-_]|h&?p|dc[-_]summary)/.test(name) && /\.(xlsx|csv)$/.test(name))
    return "clinical_xlsx";
  if (/(hr|headcount|turnover|roster|payroll)/.test(name) && /\.(xlsx|csv)$/.test(name))
    return "hr_xlsx";
  return null;
}

type Staged = {
  localId: number;
  file: File;
  fileType: FileType;
  confidenceAutoDetected: boolean;
};

// ---- Status presentation ----

const STATUS_LABEL: Record<UploadRow["status"], { label: string; className: string }> = {
  uploaded: { label: "⏳ Queued", className: "bg-slate-100 text-slate-700" },
  processing: { label: "⚙ Processing", className: "bg-blue-100 text-blue-800" },
  processed: { label: "✓ Processed", className: "bg-emerald-100 text-emerald-800" },
  error: { label: "✗ Error", className: "bg-red-100 text-red-800" },
  expired: { label: "⏲ Expired", className: "bg-amber-100 text-amber-800" },
};

function relativeTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

function humanBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

// ---- Main component ----

export function UploadDropZone({ initialUploads }: { initialUploads: UploadRow[] }) {
  const router = useRouter();
  const [staged, setStaged] = useState<Staged[]>([]);
  const [uploads, setUploads] = useState<UploadRow[]>(initialUploads);
  const [uploading, setUploading] = useState(false);
  const nextLocalId = useRef(1);

  // Poll for updates every 30 s
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const rows = await api.listUploads();
        setUploads(rows);
      } catch {
        // silent — next tick retries
      }
    }, 30_000);
    return () => clearInterval(interval);
  }, []);

  const onFilesDropped = useCallback((files: File[]) => {
    const newStaged = files.map<Staged>((f) => {
      const detected = inferType(f.name);
      return {
        localId: nextLocalId.current++,
        file: f,
        fileType: detected ?? "unknown",
        confidenceAutoDetected: detected !== null,
      };
    });
    setStaged((prev) => [...prev, ...newStaged]);
  }, []);

  const removeStaged = (localId: number) => {
    setStaged((prev) => prev.filter((s) => s.localId !== localId));
  };

  const updateStagedType = (localId: number, fileType: FileType) => {
    setStaged((prev) =>
      prev.map((s) => (s.localId === localId ? { ...s, fileType, confidenceAutoDetected: false } : s)),
    );
  };

  const allReady = staged.length > 0 && staged.every((s) => s.fileType !== "unknown");

  const submitAll = async () => {
    if (!allReady || uploading) return;
    setUploading(true);

    let succeeded = 0;
    for (const s of staged) {
      try {
        await api.stageUpload(s.file, s.fileType);
        succeeded++;
      } catch (err) {
        toast(`Upload failed: ${s.file.name}`, "error");
      }
    }
    setUploading(false);

    if (succeeded > 0) {
      toast(
        `${succeeded} file(s) uploaded. Will be processed within 15 minutes.`,
        "success",
      );
      setStaged([]);
      // Refresh the recent-uploads list immediately
      try {
        const rows = await api.listUploads();
        setUploads(rows);
      } catch {
        // silent
      }
      // Trigger server-component refetch for dashboards
      router.refresh();
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <FileDrop onFiles={onFilesDropped} disabled={uploading} />

        {staged.length > 0 ? (
          <div className="mt-6 space-y-2">
            <div className="text-xs font-bold uppercase tracking-wider text-slate-500">
              Staged ({staged.length}) — review type, then Upload
            </div>
            {staged.map((s) => (
              <div
                key={s.localId}
                className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-2"
              >
                <div className="flex-1 min-w-0">
                  <div className="truncate text-sm font-medium text-slate-800">{s.file.name}</div>
                  <div className="text-xs text-slate-500">{humanBytes(s.file.size)}</div>
                </div>
                <select
                  value={s.fileType}
                  onChange={(e) => updateStagedType(s.localId, e.target.value as FileType)}
                  className={cn(
                    "rounded-md border px-2 py-1 text-xs font-medium",
                    s.fileType === "unknown"
                      ? "border-amber-300 bg-amber-50 text-amber-900"
                      : s.confidenceAutoDetected
                        ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                        : "border-slate-300 bg-white text-slate-700",
                  )}
                >
                  <option value="unknown" disabled>
                    — Pick type —
                  </option>
                  <option value="census_pdf">Census PDF</option>
                  <option value="finance_xlsx">Finance (Excel)</option>
                  <option value="clinical_xlsx">Clinical audit (Excel)</option>
                  <option value="hr_xlsx">HR export (Excel)</option>
                </select>
                <button
                  type="button"
                  onClick={() => removeStaged(s.localId)}
                  disabled={uploading}
                  className="text-sm text-slate-400 hover:text-red-600 disabled:opacity-50"
                  aria-label="Remove"
                >
                  ✕
                </button>
              </div>
            ))}
            <div className="flex items-center justify-between pt-2">
              <div className="text-xs text-slate-500">
                {allReady
                  ? "Ready to upload."
                  : "Pick a type for each file before uploading."}
              </div>
              <button
                type="button"
                onClick={submitAll}
                disabled={!allReady || uploading}
                className={cn(
                  "rounded-md px-4 py-2 text-sm font-semibold text-white transition-colors",
                  !allReady || uploading
                    ? "bg-slate-300 cursor-not-allowed"
                    : "bg-slate-900 hover:bg-slate-800",
                )}
              >
                {uploading ? "Uploading..." : `Upload ${staged.length} file${staged.length === 1 ? "" : "s"}`}
              </button>
            </div>
          </div>
        ) : null}
      </Card>

      <Card>
        <CardHeader
          title="Recent uploads"
          owner="Last 50 · polls every 30s"
        />
        {uploads.length === 0 ? (
          <div className="text-sm text-slate-500 py-4">No uploads yet. Drop a file above to get started.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-500">
                  <th className="py-2 font-semibold">File</th>
                  <th className="py-2 font-semibold">Type</th>
                  <th className="py-2 font-semibold">Size</th>
                  <th className="py-2 font-semibold">Status</th>
                  <th className="py-2 font-semibold">Rows</th>
                  <th className="py-2 font-semibold">When</th>
                  <th className="py-2 font-semibold">By</th>
                </tr>
              </thead>
              <tbody>
                {uploads.map((u) => {
                  const statusInfo = STATUS_LABEL[u.status] ?? STATUS_LABEL.uploaded;
                  return (
                    <tr
                      key={u.id}
                      className="border-b border-slate-100 last:border-0 hover:bg-slate-50"
                    >
                      <td className="py-2.5 font-medium text-slate-900 max-w-[300px] truncate">
                        {u.original_filename}
                      </td>
                      <td className="py-2.5 text-xs text-slate-500">{FILE_TYPE_LABELS[u.file_type as FileType] ?? u.file_type}</td>
                      <td className="py-2.5 text-xs text-slate-500">{humanBytes(u.size_bytes)}</td>
                      <td className="py-2.5">
                        <span className={cn("inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold", statusInfo.className)}>
                          {statusInfo.label}
                        </span>
                        {u.status === "error" && u.error_message ? (
                          <div className="mt-0.5 text-[10px] text-red-600 max-w-[240px] truncate" title={u.error_message}>
                            {u.error_message}
                          </div>
                        ) : null}
                        {u.retry_count > 0 && u.status !== "processed" ? (
                          <div className="mt-0.5 text-[10px] text-slate-500">retry {u.retry_count}/3</div>
                        ) : null}
                      </td>
                      <td className="py-2.5 text-xs text-slate-500 tabular-nums">
                        {u.rows_written ?? "—"}
                      </td>
                      <td className="py-2.5 text-xs text-slate-500">{relativeTime(u.uploaded_at)}</td>
                      <td className="py-2.5 text-xs text-slate-500 max-w-[160px] truncate">
                        {u.uploaded_by_upn}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
