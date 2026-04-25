/**
 * Typed API client for the FastAPI backend.
 *
 * Session 1: hand-typed shapes (matches Pydantic response_model).
 * Session 2: replace with auto-generated types via `npm run gen-types`.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// ---------- Types (mirror Pydantic schemas) ----------

export type Site = {
  id: number;
  name: string;
  state: string;
  hospital_system: string | null;
  status: string;
  created_at: string;
};

export type SiteToday = {
  id: number;
  name: string;
  state: string;
  medical_director: string | null;
  md_status: string;
  liaison: string | null;
  census_today: number;
  census_3mo_avg: number;
  mtd_avg: number;
  variance_pct: number;
  open_shifts: number;
  contract_end: string;
  annual_subsidy_usd: number;
};

export type DailyEntryHistoryRow = {
  entry_date: string;
  census: number;
  open_shifts: number;
  entered_by_upn: string;
  source: string;
  notes: string | null;
  updated_at: string | null;
};

export type SiteDetail = SiteToday & {
  entered_today: boolean;
  recent_entries: DailyEntryHistoryRow[];
};

export type OperationsSummary = {
  total_fl_census: number;
  total_tx_census: number;
  total_fl_3mo_avg: number;
  census_variance_vs_avg: number;
  sites_below_avg: number;
  open_shifts_total: number;
  fl_site_count: number;
  tx_site_count: number;
};

export type FinanceToday = {
  fl_daily_actual: number;
  fl_daily_target: number;
  fl_daily_delta: number;
  fl_source_system: string;
  tx_daily_actual: number;
  tx_daily_target: number;
  tx_daily_delta: number;
  tx_source_system: string;
  fl_mtd_actual: number;
  fl_mtd_target: number;
  fl_mtd_pct: number;
  ventra_fee_mtd: number;
};

export type ArBuckets = {
  bucket_0_30: number;
  bucket_31_60: number;
  bucket_61_90: number;
  bucket_91_120: number;
  bucket_over_120: number;
};

export type ArAging = {
  fl_total_usd: number;
  fl_buckets: ArBuckets;
  fl_over_120_pct: number;
  fl_source_system: string;
  tx_total_usd: number;
  tx_buckets: ArBuckets;
  tx_over_120_pct: number;
  tx_source_system: string;
};

export type FinanceKpis = {
  fl_days_in_ar: number;
  tx_days_in_ar: number;
  days_in_ar_target: number;
  fl_ncr_pct: number;
  tx_ncr_pct: number;
  ncr_billed_at: string;
};

export type MonthRevenue = { month: string; revenue_usd: number };

export type ClinicalSummary = {
  hp_24h_pct: number;
  hp_24h_target: number;
  dc_48h_pct: number;
  dc_48h_target: number;
  los_fl_days: number;
  los_tx_days: number;
  los_woodmont_watch_days: number;
  los_woodmont_trend_days: number;
  credentials_expiring_30d: number;
  credentials_expiring_60d: number;
  credentials_expiring_90d: number;
};

export type CredentialExpiring = {
  physician: string;
  type: string;
  expires_in_days: number;
  expires_on: string;
  tier: "urgent" | "warning" | "info";
};

export type PeopleSummary = {
  headcount_w2: number;
  headcount_1099: number;
  headcount_total: number;
  open_positions_total: number;
  turnover_90d_pct: number;
  below_fmv_count: number;
};

export type OpenPositionBySite = {
  site: string;
  state: string;
  count: number;
  severity: "high" | "medium" | "low";
};

export type Scorecard = {
  physician_id: number;
  name: string;
  site: string;
  state: string;
  employment_type: "W2" | "1099";
  comp_model: "SALARY" | "PER_DIEM" | "RVU" | "HYBRID";
  status: "ACTIVE" | "PIP" | "VACANT" | "TERMED";
  rank: number;
  rvu_90d: number;
  below_fmv: boolean;
  revenue_per_fte_usd: number | null;
  encounters_per_day: number | null;
  documentation_score_pct: number | null;
  chart_turnaround_days: number | null;
};

export type Alert = {
  id: string;
  severity: "red" | "yellow" | "blue";
  category: "finance" | "operations" | "clinical" | "people";
  title: string;
  detail: string;
  owner: string;
};

export type FileType = "census_pdf" | "finance_xlsx" | "clinical_xlsx" | "hr_xlsx" | "unknown";

export type UploadRow = {
  id: number;
  uploaded_by_upn: string;
  uploaded_at: string;
  file_type: string;
  original_filename: string;
  blob_name: string;
  size_bytes: number;
  sha256: string;
  status: "uploaded" | "processing" | "processed" | "error" | "expired";
  processing_started_at: string | null;
  processing_finished_at: string | null;
  rows_written: number | null;
  error_message: string | null;
  retry_count: number;
};

export type UploadAccepted = {
  id: number;
  status: string;
  file_type: string;
  message: string;
};

// ---- Daily census entry (Crystal's form) ----

export type DailyEntryIn = {
  site_id: number;
  census: number;
  open_shifts: number;
  notes?: string | null;
};

export type DailyCensusBatchIn = {
  entry_date: string; // YYYY-MM-DD
  rows: DailyEntryIn[];
};

export type DailyEntryOut = {
  site_id: number;
  site_name: string;
  state: string;
  entry_date: string;
  census: number | null;
  open_shifts: number;
  entered_by_upn: string | null;
  source: string | null;
  notes: string | null;
  updated_at: string | null;
};

// ---------- Fetch wrapper ----------

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: "Dev admin" },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`${path} → ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as T;
}

// ---------- Typed endpoints ----------

async function postFormData<T>(path: string, formData: FormData): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { Authorization: "Dev admin" },
    body: formData,
  });
  if (!res.ok) {
    throw new Error(`${path} → ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      Authorization: "Dev admin",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`${path} → ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as T;
}

export const api = {
  sites: () => get<Site[]>("/api/v1/sites"),

  operationsSummary: () => get<OperationsSummary>("/api/v1/operations/summary"),
  sitesToday: () => get<SiteToday[]>("/api/v1/operations/sites-today"),
  siteDetail: (siteId: number) => get<SiteDetail>(`/api/v1/operations/sites/${siteId}`),

  financeToday: () => get<FinanceToday>("/api/v1/finance/today"),
  arAging: () => get<ArAging>("/api/v1/finance/ar-aging"),
  financeKpis: () => get<FinanceKpis>("/api/v1/finance/kpis"),
  monthlyTrend: () => get<MonthRevenue[]>("/api/v1/finance/monthly-trend"),

  clinicalSummary: () => get<ClinicalSummary>("/api/v1/clinical/summary"),
  credentialsExpiring: () => get<CredentialExpiring[]>("/api/v1/clinical/credentials-expiring"),

  peopleSummary: () => get<PeopleSummary>("/api/v1/people/summary"),
  openPositionsBySite: () =>
    get<OpenPositionBySite[]>("/api/v1/people/open-positions-by-site"),

  scorecards: () => get<Scorecard[]>("/api/v1/scorecards"),

  alerts: () => get<Alert[]>("/api/v1/alerts"),

  stageUpload: (file: File, fileType: FileType): Promise<UploadAccepted> => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("file_type", fileType);
    return postFormData<UploadAccepted>("/api/v1/uploads", fd);
  },
  listUploads: (sinceId?: number, limit = 50): Promise<UploadRow[]> => {
    const qs = new URLSearchParams();
    if (sinceId !== undefined) qs.set("since_id", String(sinceId));
    qs.set("limit", String(limit));
    return get<UploadRow[]>(`/api/v1/uploads?${qs.toString()}`);
  },

  getDailyCensus: (date?: string): Promise<DailyEntryOut[]> => {
    const qs = date ? `?date=${encodeURIComponent(date)}` : "";
    return get<DailyEntryOut[]>(`/api/v1/entries/daily-census${qs}`);
  },
  saveDailyCensus: (batch: DailyCensusBatchIn): Promise<DailyEntryOut[]> =>
    postJson<DailyEntryOut[]>("/api/v1/entries/daily-census", batch),
};

// Backwards-compat for Session 1 homepage
export async function fetchSites(): Promise<Site[]> {
  return api.sites();
}
