/**
 * Browser-side API client for client components (entry forms).
 *
 * Returns a `useApiBrowser()` hook that yields the same call signatures the
 * entry forms used to import from `@/lib/api-client`. The difference: each
 * call resolves a fresh Bearer token via MSAL `acquireTokenSilent` instead
 * of reading a server cookie. In dev mode (no MSAL configured), falls back
 * to `Authorization: Dev admin` so local dev keeps working.
 *
 * Why a hook (and not bare functions)?
 *   MSAL's `useMsal()` and `acquireTokenSilent` are React-bound. The token
 *   acquisition can trigger an iframe refresh; doing that inside a queryFn
 *   would race the React render cycle. Resolving the auth header at hook
 *   entry and closing over it keeps the timing predictable.
 *
 * Type re-exports come straight from api-client.ts so the entry forms can
 * `import { type DailyEntryOut } from "@/lib/api-browser"` without going
 * through the server-only module.
 */

import { useMsal } from "@azure/msal-react";
import { useCallback, useMemo } from "react";
import type {
  ClinicalState,
  DailyCensusBatchIn,
  DailyEntryIn,
  DailyEntryOut,
  FileType,
  FinanceState,
  MonthlyFinanceBatchIn,
  MonthlyFinanceRowIn,
  MonthlyFinanceRowOut,
  UploadAccepted,
  UploadRow,
  WeeklyClinicalBatchIn,
  WeeklyClinicalRowIn,
  WeeklyClinicalRowOut,
  WeeklyHrIn,
  WeeklyHrOut,
} from "./api-client";
import { type GetAuthHeader, apiGet, apiPostFormData, apiPostJson } from "./api-fetch";
import { apiScope, isMsalConfigured } from "./auth/msal-config";

export type {
  ClinicalState,
  DailyCensusBatchIn,
  DailyEntryIn,
  DailyEntryOut,
  FileType,
  FinanceState,
  MonthlyFinanceBatchIn,
  MonthlyFinanceRowIn,
  MonthlyFinanceRowOut,
  UploadAccepted,
  UploadRow,
  WeeklyClinicalBatchIn,
  WeeklyClinicalRowIn,
  WeeklyClinicalRowOut,
  WeeklyHrIn,
  WeeklyHrOut,
} from "./api-client";

export type BrowserApi = {
  getDailyCensus: (date?: string) => Promise<DailyEntryOut[]>;
  saveDailyCensus: (batch: DailyCensusBatchIn) => Promise<DailyEntryOut[]>;

  listUploads: (sinceId?: number, limit?: number) => Promise<UploadRow[]>;
  stageUpload: (file: File, fileType: FileType) => Promise<UploadAccepted>;

  getMonthlyFinance: (year?: number, month?: number) => Promise<MonthlyFinanceRowOut[]>;
  saveMonthlyFinance: (batch: MonthlyFinanceBatchIn) => Promise<MonthlyFinanceRowOut[]>;

  getWeeklyClinical: (weekEnding?: string) => Promise<WeeklyClinicalRowOut[]>;
  saveWeeklyClinical: (batch: WeeklyClinicalBatchIn) => Promise<WeeklyClinicalRowOut[]>;

  getWeeklyHr: (weekEnding?: string) => Promise<WeeklyHrOut | null>;
  saveWeeklyHr: (payload: WeeklyHrIn) => Promise<WeeklyHrOut>;
};

function makeApi(getAuthHeader: GetAuthHeader): BrowserApi {
  const get = <T>(path: string) => apiGet<T>(path, getAuthHeader);
  const postJson = <T>(path: string, body: unknown) => apiPostJson<T>(path, body, getAuthHeader);
  const postFormData = <T>(path: string, fd: FormData) =>
    apiPostFormData<T>(path, fd, getAuthHeader);

  return {
    getDailyCensus: (date?: string) => {
      const qs = date ? `?date=${encodeURIComponent(date)}` : "";
      return get<DailyEntryOut[]>(`/api/v1/entries/daily-census${qs}`);
    },
    saveDailyCensus: (batch) => postJson<DailyEntryOut[]>("/api/v1/entries/daily-census", batch),

    listUploads: (sinceId?: number, limit = 50) => {
      const qs = new URLSearchParams();
      if (sinceId !== undefined) qs.set("since_id", String(sinceId));
      qs.set("limit", String(limit));
      return get<UploadRow[]>(`/api/v1/uploads?${qs.toString()}`);
    },
    stageUpload: (file, fileType) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("file_type", fileType);
      return postFormData<UploadAccepted>("/api/v1/uploads", fd);
    },

    getMonthlyFinance: (year?: number, month?: number) => {
      const qs = new URLSearchParams();
      if (year !== undefined) qs.set("year", String(year));
      if (month !== undefined) qs.set("month", String(month));
      const suffix = qs.toString() ? `?${qs.toString()}` : "";
      return get<MonthlyFinanceRowOut[]>(`/api/v1/entries/monthly-finance${suffix}`);
    },
    saveMonthlyFinance: (batch) =>
      postJson<MonthlyFinanceRowOut[]>("/api/v1/entries/monthly-finance", batch),

    getWeeklyClinical: (weekEnding?: string) => {
      const qs = weekEnding ? `?week_ending=${encodeURIComponent(weekEnding)}` : "";
      return get<WeeklyClinicalRowOut[]>(`/api/v1/entries/weekly-clinical${qs}`);
    },
    saveWeeklyClinical: (batch) =>
      postJson<WeeklyClinicalRowOut[]>("/api/v1/entries/weekly-clinical", batch),

    getWeeklyHr: (weekEnding?: string) => {
      const qs = weekEnding ? `?week_ending=${encodeURIComponent(weekEnding)}` : "";
      return get<WeeklyHrOut | null>(`/api/v1/entries/weekly-hr${qs}`);
    },
    saveWeeklyHr: (payload) => postJson<WeeklyHrOut>("/api/v1/entries/weekly-hr", payload),
  };
}

/** Hook for entry forms. Returns a stable api object keyed by the active MSAL account. */
export function useApiBrowser(): BrowserApi {
  const { instance, accounts } = useMsal();
  const account = accounts[0] ?? null;
  const configured = isMsalConfigured();

  const getAuthHeader = useCallback<GetAuthHeader>(async () => {
    if (!configured || !account) return "Dev admin";
    const result = await instance.acquireTokenSilent({
      account,
      scopes: [apiScope()],
    });
    return `Bearer ${result.accessToken}`;
  }, [instance, account, configured]);

  return useMemo(() => makeApi(getAuthHeader), [getAuthHeader]);
}
