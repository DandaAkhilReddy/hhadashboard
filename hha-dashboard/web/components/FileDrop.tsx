"use client";

import { useCallback, useRef, useState } from "react";
import { cn } from "@/lib/format";

type FileDropProps = {
  onFiles: (files: File[]) => void;
  accept?: string;
  multiple?: boolean;
  maxBytes?: number;
  disabled?: boolean;
};

const DEFAULT_ACCEPT = ".pdf,.xlsx,.xls,.csv";
const DEFAULT_MAX_BYTES = 25 * 1024 * 1024; // 25 MB

export function FileDrop({
  onFiles,
  accept = DEFAULT_ACCEPT,
  multiple = true,
  maxBytes = DEFAULT_MAX_BYTES,
  disabled = false,
}: FileDropProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback(
    (files: File[]) => {
      setError(null);
      const ok: File[] = [];
      const tooBig: string[] = [];
      for (const f of files) {
        if (f.size > maxBytes) {
          tooBig.push(f.name);
        } else {
          ok.push(f);
        }
      }
      if (tooBig.length) {
        setError(
          `${tooBig.length} file(s) exceed ${(maxBytes / 1024 / 1024).toFixed(0)} MB limit: ${tooBig.slice(0, 3).join(", ")}`,
        );
      }
      if (ok.length) onFiles(ok);
    },
    [onFiles, maxBytes],
  );

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-disabled={disabled}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setIsDragOver(true);
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragOver(false);
          if (disabled) return;
          handleFiles(Array.from(e.dataTransfer.files));
        }}
        onClick={() => {
          if (disabled) return;
          inputRef.current?.click();
        }}
        onKeyDown={(e) => {
          if (disabled) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        className={cn(
          "flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-12 text-center cursor-pointer transition-colors",
          isDragOver
            ? "border-indigo-500 bg-indigo-50"
            : "border-slate-300 bg-slate-50 hover:border-slate-400 hover:bg-slate-100",
          disabled && "cursor-not-allowed opacity-50",
        )}
      >
        <div className="text-3xl">📄</div>
        <div className="text-sm font-semibold text-slate-800">
          Drop files here or click to browse
        </div>
        <div className="text-xs text-slate-500">
          PDFs, Excel (.xlsx / .xls), CSV · Max {(maxBytes / 1024 / 1024).toFixed(0)} MB per file
        </div>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        hidden
        onChange={(e) => {
          if (e.target.files) {
            handleFiles(Array.from(e.target.files));
            // Reset so selecting the same file twice still fires onChange
            e.target.value = "";
          }
        }}
      />
      {error ? (
        <div className="mt-2 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      ) : null}
    </div>
  );
}
