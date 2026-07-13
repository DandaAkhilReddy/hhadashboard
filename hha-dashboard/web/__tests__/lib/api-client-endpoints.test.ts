// @vitest-environment node
//
// Direct unit tests for the typed-endpoint surface in lib/api-client.ts.
// The page-level tests already mock `api` wholesale; this file pins the
// URL templates + qs encoding + FormData composition that every server
// component depends on. Mocks the api-fetch layer + the server-session
// auth header so no network or cookie is touched.

import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGetMock = vi.fn();
const apiPostJsonMock = vi.fn();
const apiPostFormDataMock = vi.fn();
const getServerAuthHeaderMock = vi.fn();

vi.mock("@/lib/api-fetch", () => ({
  apiGet: (path: string, headerFn: unknown) => apiGetMock(path, headerFn),
  apiPostJson: (path: string, body: unknown, headerFn: unknown) =>
    apiPostJsonMock(path, body, headerFn),
  apiPostFormData: (path: string, fd: FormData, headerFn: unknown) =>
    apiPostFormDataMock(path, fd, headerFn),
}));

vi.mock("@/lib/auth/server-session", () => ({
  getServerAuthHeader: () => getServerAuthHeaderMock(),
}));

import { api, fetchSites } from "@/lib/api-client";

beforeEach(() => {
  apiGetMock.mockReset();
  apiPostJsonMock.mockReset();
  apiPostFormDataMock.mockReset();
  getServerAuthHeaderMock.mockReset();
  // The endpoint methods don't care about the return value when we're
  // asserting on the call shape — let each test drive its own mock.
  apiGetMock.mockResolvedValue(undefined);
  apiPostJsonMock.mockResolvedValue(undefined);
  apiPostFormDataMock.mockResolvedValue(undefined);
});

// ----------------------------- Operations -----------------------------------

describe("api — operations endpoints", () => {
  it("sites() hits /api/v1/sites", async () => {
    await api.sites();
    expect(apiGetMock).toHaveBeenCalledWith("/api/v1/sites", expect.any(Function));
  });

  it("operationsSummary() hits /api/v1/operations/summary", async () => {
    await api.operationsSummary();
    expect(apiGetMock).toHaveBeenCalledWith("/api/v1/operations/summary", expect.any(Function));
  });

  it("sitesToday() hits /api/v1/operations/sites-today", async () => {
    await api.sitesToday();
    expect(apiGetMock).toHaveBeenCalledWith("/api/v1/operations/sites-today", expect.any(Function));
  });

  it("siteDetail(id) inserts the id into the URL template", async () => {
    await api.siteDetail(42);
    expect(apiGetMock).toHaveBeenCalledWith("/api/v1/operations/sites/42", expect.any(Function));
  });

  it("siteDetail handles large ids without scientific notation", async () => {
    await api.siteDetail(1_234_567);
    expect(apiGetMock).toHaveBeenCalledWith(
      "/api/v1/operations/sites/1234567",
      expect.any(Function),
    );
  });
});

// ----------------------------- Finance --------------------------------------

describe("api — finance endpoints", () => {
  it.each([
    ["financeToday", "/api/v1/finance/today"],
    ["arAging", "/api/v1/finance/ar-aging"],
    ["financeKpis", "/api/v1/finance/kpis"],
    ["monthlyTrend", "/api/v1/finance/monthly-trend"],
  ] as const)("%s() hits %s", async (method, path) => {
    await (api[method] as () => Promise<unknown>)();
    expect(apiGetMock).toHaveBeenCalledWith(path, expect.any(Function));
  });
});

// ----------------------------- Clinical -------------------------------------

describe("api — clinical endpoints", () => {
  it("clinicalSummary() hits /api/v1/clinical/summary", async () => {
    await api.clinicalSummary();
    expect(apiGetMock).toHaveBeenCalledWith("/api/v1/clinical/summary", expect.any(Function));
  });

  it("credentialsExpiring() hits /api/v1/clinical/credentials-expiring", async () => {
    await api.credentialsExpiring();
    expect(apiGetMock).toHaveBeenCalledWith(
      "/api/v1/clinical/credentials-expiring",
      expect.any(Function),
    );
  });
});

// ----------------------------- People + Scorecards --------------------------

describe("api — people + scorecards + alerts endpoints", () => {
  it("peopleSummary() hits /api/v1/people/summary", async () => {
    await api.peopleSummary();
    expect(apiGetMock).toHaveBeenCalledWith("/api/v1/people/summary", expect.any(Function));
  });

  it("openPositionsBySite() hits /api/v1/people/open-positions-by-site", async () => {
    await api.openPositionsBySite();
    expect(apiGetMock).toHaveBeenCalledWith(
      "/api/v1/people/open-positions-by-site",
      expect.any(Function),
    );
  });

  it("scorecards() hits /api/v1/scorecards", async () => {
    await api.scorecards();
    expect(apiGetMock).toHaveBeenCalledWith("/api/v1/scorecards", expect.any(Function));
  });

  it("alerts() hits /api/v1/alerts", async () => {
    await api.alerts();
    expect(apiGetMock).toHaveBeenCalledWith("/api/v1/alerts", expect.any(Function));
  });
});

// ----------------------------- Uploads --------------------------------------

describe("api — uploads endpoints", () => {
  it("stageUpload composes the FormData with file + file_type", async () => {
    const file = new File(["abc"], "census.pdf", { type: "application/pdf" });
    await api.stageUpload(file, "census_pdf");

    expect(apiPostFormDataMock).toHaveBeenCalledTimes(1);
    const [path, fd, _hdr] = apiPostFormDataMock.mock.calls[0] as [string, FormData, unknown];
    expect(path).toBe("/api/v1/uploads");
    expect(fd.get("file_type")).toBe("census_pdf");
    expect((fd.get("file") as File).name).toBe("census.pdf");
  });

  it("listUploads() default — only limit=50 in qs", async () => {
    await api.listUploads();
    expect(apiGetMock).toHaveBeenCalledTimes(1);
    const path = apiGetMock.mock.calls[0]?.[0] as string;
    expect(path.startsWith("/api/v1/uploads?")).toBe(true);
    const qs = new URLSearchParams(path.split("?")[1]);
    expect(qs.get("limit")).toBe("50");
    expect(qs.get("since_id")).toBeNull();
  });

  it("listUploads(sinceId, limit) — both in qs", async () => {
    await api.listUploads(100, 25);
    const path = apiGetMock.mock.calls[0]?.[0] as string;
    const qs = new URLSearchParams(path.split("?")[1]);
    expect(qs.get("since_id")).toBe("100");
    expect(qs.get("limit")).toBe("25");
  });

  it("listUploads(0) — sinceId=0 is included (zero is a valid since_id)", async () => {
    await api.listUploads(0);
    const path = apiGetMock.mock.calls[0]?.[0] as string;
    const qs = new URLSearchParams(path.split("?")[1]);
    expect(qs.get("since_id")).toBe("0");
  });
});

// ----------------------------- Daily census entries -------------------------

describe("api — daily-census endpoints", () => {
  it("getDailyCensus() with no date — no qs suffix", async () => {
    await api.getDailyCensus();
    expect(apiGetMock).toHaveBeenCalledWith("/api/v1/entries/daily-census", expect.any(Function));
  });

  it("getDailyCensus(date) — date URI-encoded into qs", async () => {
    await api.getDailyCensus("2026-05-17");
    expect(apiGetMock).toHaveBeenCalledWith(
      "/api/v1/entries/daily-census?date=2026-05-17",
      expect.any(Function),
    );
  });

  it("getDailyCensus(date) — URI-encodes special chars", async () => {
    await api.getDailyCensus("2026/05/17");
    const path = apiGetMock.mock.calls[0]?.[0] as string;
    expect(path).toContain("date=2026%2F05%2F17");
  });

  it("saveDailyCensus posts JSON to /api/v1/entries/daily-census", async () => {
    const batch = { entry_date: "2026-05-17", rows: [{ site_id: 1, census: 198, open_shifts: 2 }] };
    await api.saveDailyCensus(batch);
    expect(apiPostJsonMock).toHaveBeenCalledWith(
      "/api/v1/entries/daily-census",
      batch,
      expect.any(Function),
    );
  });
});

// ----------------------------- Monthly finance ------------------------------

describe("api — monthly-finance endpoints", () => {
  it("getMonthlyFinance() with no args — no qs suffix", async () => {
    await api.getMonthlyFinance();
    expect(apiGetMock).toHaveBeenCalledWith(
      "/api/v1/entries/monthly-finance",
      expect.any(Function),
    );
  });

  it("getMonthlyFinance(year) — year in qs, no month", async () => {
    await api.getMonthlyFinance(2026);
    const path = apiGetMock.mock.calls[0]?.[0] as string;
    expect(path.startsWith("/api/v1/entries/monthly-finance?")).toBe(true);
    const qs = new URLSearchParams(path.split("?")[1]);
    expect(qs.get("year")).toBe("2026");
    expect(qs.get("month")).toBeNull();
  });

  it("getMonthlyFinance(undefined, month) — month in qs, no year", async () => {
    await api.getMonthlyFinance(undefined, 5);
    const path = apiGetMock.mock.calls[0]?.[0] as string;
    const qs = new URLSearchParams(path.split("?")[1]);
    expect(qs.get("year")).toBeNull();
    expect(qs.get("month")).toBe("5");
  });

  it("getMonthlyFinance(year, month) — both in qs", async () => {
    await api.getMonthlyFinance(2026, 5);
    const path = apiGetMock.mock.calls[0]?.[0] as string;
    const qs = new URLSearchParams(path.split("?")[1]);
    expect(qs.get("year")).toBe("2026");
    expect(qs.get("month")).toBe("5");
  });

  it("saveMonthlyFinance posts JSON to /api/v1/entries/monthly-finance", async () => {
    const batch = { year: 2026, month: 5, rows: [] };
    await api.saveMonthlyFinance(batch as never);
    expect(apiPostJsonMock).toHaveBeenCalledWith(
      "/api/v1/entries/monthly-finance",
      batch,
      expect.any(Function),
    );
  });
});

// ----------------------------- Weekly clinical + HR -------------------------

describe("api — weekly clinical/HR endpoints", () => {
  it("getWeeklyClinical() with no week — no qs", async () => {
    await api.getWeeklyClinical();
    expect(apiGetMock).toHaveBeenCalledWith(
      "/api/v1/entries/weekly-clinical",
      expect.any(Function),
    );
  });

  it("getWeeklyClinical(weekEnding) — URI-encoded into qs", async () => {
    await api.getWeeklyClinical("2026-05-10");
    expect(apiGetMock).toHaveBeenCalledWith(
      "/api/v1/entries/weekly-clinical?week_ending=2026-05-10",
      expect.any(Function),
    );
  });

  it("saveWeeklyClinical posts JSON to /api/v1/entries/weekly-clinical", async () => {
    const batch = { week_ending: "2026-05-10", rows: [] };
    await api.saveWeeklyClinical(batch as never);
    expect(apiPostJsonMock).toHaveBeenCalledWith(
      "/api/v1/entries/weekly-clinical",
      batch,
      expect.any(Function),
    );
  });

  it("getWeeklyHr() with no week — no qs", async () => {
    await api.getWeeklyHr();
    expect(apiGetMock).toHaveBeenCalledWith("/api/v1/entries/weekly-hr", expect.any(Function));
  });

  it("getWeeklyHr(weekEnding) — URI-encoded into qs", async () => {
    await api.getWeeklyHr("2026-05-10");
    expect(apiGetMock).toHaveBeenCalledWith(
      "/api/v1/entries/weekly-hr?week_ending=2026-05-10",
      expect.any(Function),
    );
  });

  it("saveWeeklyHr posts JSON to /api/v1/entries/weekly-hr", async () => {
    const payload = { week_ending: "2026-05-10", headcount_w2: 100, headcount_1099: 20 };
    await api.saveWeeklyHr(payload as never);
    expect(apiPostJsonMock).toHaveBeenCalledWith(
      "/api/v1/entries/weekly-hr",
      payload,
      expect.any(Function),
    );
  });
});

// ----------------------------- Backwards-compat -----------------------------

describe("fetchSites — Session-1 backcompat helper", () => {
  it("delegates to api.sites()", async () => {
    await fetchSites();
    expect(apiGetMock).toHaveBeenCalledWith("/api/v1/sites", expect.any(Function));
  });
});

// ----------------------------- Auth-header wiring ---------------------------

describe("api — every endpoint forwards the server auth header function", () => {
  it("apiGet receives a thunk that returns getServerAuthHeader()", async () => {
    getServerAuthHeaderMock.mockReturnValue({ Authorization: "Bearer x" });

    await api.sites();
    const headerFn = apiGetMock.mock.calls[0]?.[1] as () => unknown;
    expect(typeof headerFn).toBe("function");
    const headers = headerFn();
    expect(headers).toEqual({ Authorization: "Bearer x" });
    expect(getServerAuthHeaderMock).toHaveBeenCalledTimes(1);
  });
});
