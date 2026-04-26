"use client";

import { cn } from "@/lib/format";
import { useCallback, useEffect, useState } from "react";

export type ToastVariant = "success" | "error" | "info";

type ToastItem = {
  id: number;
  message: string;
  variant: ToastVariant;
};

let NEXT_ID = 1;
type Subscriber = (toasts: ToastItem[]) => void;
const subscribers: Set<Subscriber> = new Set();
let current: ToastItem[] = [];

function notify() {
  for (const fn of subscribers) fn(current);
}

export function toast(message: string, variant: ToastVariant = "info", timeoutMs = 4000) {
  const item: ToastItem = { id: NEXT_ID++, message, variant };
  current = [...current, item];
  notify();
  setTimeout(() => {
    current = current.filter((t) => t.id !== item.id);
    notify();
  }, timeoutMs);
}

const VARIANT_CLASSES: Record<ToastVariant, string> = {
  success: "border-emerald-200 bg-emerald-50 text-emerald-900",
  error: "border-red-200 bg-red-50 text-red-900",
  info: "border-slate-200 bg-white text-slate-800",
};

const VARIANT_ICONS: Record<ToastVariant, string> = {
  success: "✓",
  error: "✗",
  info: "ℹ",
};

export function Toaster() {
  const [items, setItems] = useState<ToastItem[]>(current);

  const sub = useCallback((list: ToastItem[]) => setItems(list), []);

  useEffect(() => {
    subscribers.add(sub);
    return () => {
      subscribers.delete(sub);
    };
  }, [sub]);

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {items.map((t) => (
        <div
          key={t.id}
          className={cn(
            "pointer-events-auto flex items-start gap-3 rounded-lg border px-4 py-3 shadow-lg min-w-[280px] max-w-[420px]",
            VARIANT_CLASSES[t.variant],
          )}
        >
          <span className="mt-0.5 font-bold">{VARIANT_ICONS[t.variant]}</span>
          <span className="text-sm flex-1">{t.message}</span>
        </div>
      ))}
    </div>
  );
}
