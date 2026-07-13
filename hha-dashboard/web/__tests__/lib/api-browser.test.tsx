// @vitest-environment happy-dom
//
// useApiBrowser hook tests — verifies the browser-side API client
// builds the right paths, handles optional query params, and forwards
// the Bearer header acquired via MSAL acquireTokenSilent.
//
// Strategy: mock @/lib/api-fetch so the underlying fetch is a spy,
// mock @azure/msal-react useMsal so we control the account + instance,
// mock @/lib/auth/msal-config so we can toggle isMsalConfigured.
// Render a tiny test component that calls useApiBrowser and invokes
// each method, then assert on the captured call args.

import { render } from "@testing-library/react";
import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGetMock = vi.fn();
const apiPostJsonMock = vi.fn();
const apiPostFormDataMock = vi.fn();

vi.mock("@/lib/api-fetch", () => ({
  apiGet: (...args: unknown[]) => apiGetMock(...args),
  apiPostJson: (...args: unknown[]) => apiPostJsonMock(...args),
  apiPostFormData: (...args: unknown[]) => apiPostFormDataMock(...args),
}));

const acquireTokenSilentMock = vi.fn();

vi.mock("@azure/msal-react", () => ({
  useMsal: vi.fn(),
}));

vi.mock("@/lib/auth/msal-config", () => ({
  isMsalConfigured: vi.fn(),
  apiScope: () => "api://x/access_as_user",
}));

import { isMsalConfigured } from "@/lib/auth/msal-config";
import { useMsal } from "@azure/msal-react";

import { type BrowserApi, useApiBrowser } from "@/lib/api-browser";

/** Tiny harness component — captures the api object on first render. */
function ApiHarness({ onApi }: { onApi: (api: BrowserApi) => void }) {
  const api = useApiBrowser();
  useEffect(() => {
    onApi(api);
  }, [api, onApi]);
  return null;
}

function captureApi(): Promise<BrowserApi> {
  return new Promise<BrowserApi>((resolve) => {
    render(<ApiHarness onApi={resolve} />);
  });
}

describe("useApiBrowser", () => {
  beforeEach(() => {
    apiGetMock.mockReset().mockResolvedValue([]);
    apiPostJsonMock.mockReset().mockResolvedValue([]);
    apiPostFormDataMock.mockReset().mockResolvedValue({});
    acquireTokenSilentMock.mockReset();
    vi.mocked(isMsalConfigured).mockReset();
    vi.mocked(useMsal).mockReturnValue({
      instance: { acquireTokenSilent: acquireTokenSilentMock },
      accounts: [],
      inProgress: "none",
    } as never);
  });

  // ---------- auth header resolution ----------

  it("returns 'Dev admin' header when MSAL is not configured", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const api = await captureApi();

    await api.getDailyCensus();

    // Last arg is the GetAuthHeader resolver — call it and assert
    const resolver = apiGetMock.mock.calls[0]?.[1] as () => Promise<string>;
    expect(await resolver()).toBe("Dev admin");
    expect(acquireTokenSilentMock).not.toHaveBeenCalled();
  });

  it("returns 'Dev admin' header when configured but no account is cached", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(true);
    // accounts: [] (default from beforeEach)
    const api = await captureApi();

    await api.getDailyCensus();

    const resolver = apiGetMock.mock.calls[0]?.[1] as () => Promise<string>;
    expect(await resolver()).toBe("Dev admin");
    expect(acquireTokenSilentMock).not.toHaveBeenCalled();
  });

  it("acquires a Bearer token via acquireTokenSilent when configured + account present", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(true);
    const account = { username: "alice@hha.com", homeAccountId: "x" };
    vi.mocked(useMsal).mockReturnValue({
      instance: { acquireTokenSilent: acquireTokenSilentMock },
      accounts: [account],
      inProgress: "none",
    } as never);
    acquireTokenSilentMock.mockResolvedValue({ accessToken: "jwt-xyz" });

    const api = await captureApi();
    await api.getDailyCensus();

    const resolver = apiGetMock.mock.calls[0]?.[1] as () => Promise<string>;
    expect(await resolver()).toBe("Bearer jwt-xyz");
    expect(acquireTokenSilentMock).toHaveBeenCalledWith({
      account,
      scopes: ["api://x/access_as_user"],
    });
  });

  // ---------- daily-census paths ----------

  it("getDailyCensus omits ?date= when no date is provided", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const api = await captureApi();

    await api.getDailyCensus();

    expect(apiGetMock).toHaveBeenCalledWith("/api/v1/entries/daily-census", expect.any(Function));
  });

  it("getDailyCensus appends ?date=YYYY-MM-DD when provided", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const api = await captureApi();

    await api.getDailyCensus("2026-05-14");

    expect(apiGetMock).toHaveBeenCalledWith(
      "/api/v1/entries/daily-census?date=2026-05-14",
      expect.any(Function),
    );
  });

  it("saveDailyCensus POSTs the batch JSON to the documented path", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const api = await captureApi();

    const batch = {
      entry_date: "2026-05-14",
      rows: [{ site_id: 1, census: 100, open_shifts: 0 }],
    };
    await api.saveDailyCensus(batch);

    expect(apiPostJsonMock).toHaveBeenCalledWith(
      "/api/v1/entries/daily-census",
      batch,
      expect.any(Function),
    );
  });

  // ---------- uploads ----------

  it("listUploads defaults limit=50 and omits since_id when not given", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const api = await captureApi();

    await api.listUploads();

    const [path] = apiGetMock.mock.calls[0] as [string, unknown];
    expect(path).toContain("/api/v1/uploads?");
    expect(path).toContain("limit=50");
    expect(path).not.toContain("since_id=");
  });

  it("listUploads adds since_id + custom limit when provided", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const api = await captureApi();

    await api.listUploads(42, 10);

    const [path] = apiGetMock.mock.calls[0] as [string, unknown];
    expect(path).toContain("since_id=42");
    expect(path).toContain("limit=10");
  });

  it("stageUpload posts FormData with file + file_type fields", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const api = await captureApi();

    const file = new File(["x"], "x.pdf", { type: "application/pdf" });
    await api.stageUpload(file, "census_pdf" as never);

    expect(apiPostFormDataMock).toHaveBeenCalledTimes(1);
    const [path, fd] = apiPostFormDataMock.mock.calls[0] as [string, FormData, unknown];
    expect(path).toBe("/api/v1/uploads");
    expect(fd).toBeInstanceOf(FormData);
    expect((fd as FormData).get("file")).toBe(file);
    expect((fd as FormData).get("file_type")).toBe("census_pdf");
  });

  // ---------- monthly finance ----------

  it("getMonthlyFinance omits query when no year/month provided", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const api = await captureApi();

    await api.getMonthlyFinance();

    expect(apiGetMock).toHaveBeenCalledWith(
      "/api/v1/entries/monthly-finance",
      expect.any(Function),
    );
  });

  it("getMonthlyFinance adds year + month query params when both provided", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const api = await captureApi();

    await api.getMonthlyFinance(2026, 5);

    const [path] = apiGetMock.mock.calls[0] as [string, unknown];
    expect(path).toContain("year=2026");
    expect(path).toContain("month=5");
  });

  it("getMonthlyFinance adds only year when month omitted", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const api = await captureApi();

    await api.getMonthlyFinance(2026);

    const [path] = apiGetMock.mock.calls[0] as [string, unknown];
    expect(path).toContain("year=2026");
    expect(path).not.toContain("month=");
  });

  it("saveMonthlyFinance POSTs the batch JSON", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const api = await captureApi();

    const batch = {
      year: 2026,
      month: 5,
      rows: [{ state: "FL" as const, collections_usd: 100 }],
    };
    await api.saveMonthlyFinance(batch as never);

    expect(apiPostJsonMock).toHaveBeenCalledWith(
      "/api/v1/entries/monthly-finance",
      batch,
      expect.any(Function),
    );
  });

  // ---------- weekly clinical ----------

  it("getWeeklyClinical omits week_ending when not given", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const api = await captureApi();

    await api.getWeeklyClinical();

    expect(apiGetMock).toHaveBeenCalledWith(
      "/api/v1/entries/weekly-clinical",
      expect.any(Function),
    );
  });

  it("getWeeklyClinical encodes week_ending in the query string", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const api = await captureApi();

    await api.getWeeklyClinical("2026-05-10");

    expect(apiGetMock).toHaveBeenCalledWith(
      "/api/v1/entries/weekly-clinical?week_ending=2026-05-10",
      expect.any(Function),
    );
  });

  it("saveWeeklyClinical POSTs the batch JSON", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const api = await captureApi();

    const batch = {
      week_ending: "2026-05-10",
      rows: [{ state: "FL" as const, hp_24h_pct: 95.5 }],
    };
    await api.saveWeeklyClinical(batch as never);

    expect(apiPostJsonMock).toHaveBeenCalledWith(
      "/api/v1/entries/weekly-clinical",
      batch,
      expect.any(Function),
    );
  });

  // ---------- weekly HR ----------

  it("getWeeklyHr omits week_ending when not given", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const api = await captureApi();

    await api.getWeeklyHr();

    expect(apiGetMock).toHaveBeenCalledWith("/api/v1/entries/weekly-hr", expect.any(Function));
  });

  it("getWeeklyHr encodes week_ending when provided", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const api = await captureApi();

    await api.getWeeklyHr("2026-05-10");

    expect(apiGetMock).toHaveBeenCalledWith(
      "/api/v1/entries/weekly-hr?week_ending=2026-05-10",
      expect.any(Function),
    );
  });

  it("saveWeeklyHr POSTs the payload JSON", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const api = await captureApi();

    const payload = { week_ending: "2026-05-10", headcount_w2: 100 };
    await api.saveWeeklyHr(payload as never);

    expect(apiPostJsonMock).toHaveBeenCalledWith(
      "/api/v1/entries/weekly-hr",
      payload,
      expect.any(Function),
    );
  });
});
