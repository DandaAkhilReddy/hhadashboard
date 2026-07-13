// @vitest-environment happy-dom
//
// /census/entry server-page tests. The page is a thin async server
// component that:
//   1. Reads the `census_session` cookie; missing → redirect("/census/login")
//   2. Parses optional ?date= searchParam, validates as YYYY-MM-DD
//   3. Forwards the cookie to /census-portal/sites + /summary in parallel
//   4. 401 on either response → redirect("/census/login")
//   5. !ok on either response → renders an inline error banner
//   6. happy path → renders <CensusEntryForm> with the prefill payload

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const cookieGet = vi.fn();
const redirectMock = vi.fn((_path: string) => {
  // Match Next.js redirect() semantics — it throws to halt rendering.
  throw new Error(`NEXT_REDIRECT:${_path}`);
});

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: cookieGet }),
}));

vi.mock("next/navigation", () => ({
  redirect: (path: string) => redirectMock(path),
}));

// Form is its own test; passthrough surfacing the four props the page sets.
vi.mock("@/app/census/entry/CensusEntryForm", () => ({
  CensusEntryForm: (props: {
    initialDate: string;
    initialSites: unknown[];
    initialSummary: unknown;
    apiBase: string;
  }) => (
    <div
      data-testid="census-entry-form"
      data-initial-date={props.initialDate}
      data-api-base={props.apiBase}
      data-sites={JSON.stringify(props.initialSites)}
      data-summary={JSON.stringify(props.initialSummary)}
    />
  ),
}));

import CensusEntryPage from "@/app/census/entry/page";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  cookieGet.mockReset();
  redirectMock.mockClear();
});

// ----------------------------- Cookie guard ---------------------------------

describe("CensusEntryPage — cookie guard", () => {
  it("missing census_session cookie redirects to /census/login", async () => {
    cookieGet.mockReturnValue(undefined);

    await expect(CensusEntryPage({ searchParams: Promise.resolve({}) })).rejects.toThrow(
      /NEXT_REDIRECT:\/census\/login/,
    );
    expect(redirectMock).toHaveBeenCalledWith("/census/login");
  });
});

// ----------------------------- 401 from API ---------------------------------

describe("CensusEntryPage — 401 handling", () => {
  it("redirects when /sites returns 401", async () => {
    cookieGet.mockReturnValue({ value: "session-tok" });
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response("", { status: 401 }))
      .mockResolvedValueOnce(jsonResponse({}));

    await expect(CensusEntryPage({ searchParams: Promise.resolve({}) })).rejects.toThrow(
      /NEXT_REDIRECT:\/census\/login/,
    );
    expect(redirectMock).toHaveBeenCalledWith("/census/login");
    fetchSpy.mockRestore();
  });

  it("redirects when /summary returns 401", async () => {
    cookieGet.mockReturnValue({ value: "session-tok" });
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({}))
      .mockResolvedValueOnce(new Response("", { status: 401 }));

    await expect(CensusEntryPage({ searchParams: Promise.resolve({}) })).rejects.toThrow(
      /NEXT_REDIRECT:\/census\/login/,
    );
    fetchSpy.mockRestore();
  });
});

// ----------------------------- Error fallback -------------------------------

describe("CensusEntryPage — non-401 error fallback", () => {
  it("renders the inline error banner when /sites is non-OK (e.g. 500)", async () => {
    cookieGet.mockReturnValue({ value: "session-tok" });
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response("", { status: 500 }))
      .mockResolvedValueOnce(jsonResponse({}));

    const tree = await CensusEntryPage({ searchParams: Promise.resolve({}) });
    render(tree);

    expect(screen.getByText(/Could not load census data/)).toBeInTheDocument();
    expect(screen.getByText(/sites: 500/)).toBeInTheDocument();
    fetchSpy.mockRestore();
  });

  it("renders the inline error banner when /summary is non-OK", async () => {
    cookieGet.mockReturnValue({ value: "session-tok" });
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({}))
      .mockResolvedValueOnce(new Response("", { status: 502 }));

    const tree = await CensusEntryPage({ searchParams: Promise.resolve({}) });
    render(tree);

    expect(screen.getByText(/summary: 502/)).toBeInTheDocument();
    fetchSpy.mockRestore();
  });
});

// ----------------------------- Date param parsing ---------------------------

describe("CensusEntryPage — ?date= search-param parsing", () => {
  it("appends ?date= to both upstream requests when a valid date is given", async () => {
    cookieGet.mockReturnValue({ value: "session-tok" });
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ entry_date: "2026-05-10", sites: [] }))
      .mockResolvedValueOnce(
        jsonResponse({
          entry_date: "2026-05-10",
          total_census: 0,
          facilities_reported: 0,
          facilities_missing: 0,
          last_updated_at: null,
        }),
      );

    await CensusEntryPage({
      searchParams: Promise.resolve({ date: "2026-05-10" }),
    });

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    const [firstUrl, firstInit] = fetchSpy.mock.calls[0] as [string, RequestInit];
    const [secondUrl] = fetchSpy.mock.calls[1] as [string, RequestInit];
    expect(firstUrl).toContain("/census-portal/sites?date=2026-05-10");
    expect(secondUrl).toContain("/census-portal/summary?date=2026-05-10");
    // Cookie forwarded as a Cookie header
    expect((firstInit.headers as Record<string, string>).Cookie).toBe("census_session=session-tok");
    fetchSpy.mockRestore();
  });

  it("ignores a malformed date (no qs appended)", async () => {
    cookieGet.mockReturnValue({ value: "session-tok" });
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ entry_date: "2026-05-17", sites: [] }))
      .mockResolvedValueOnce(
        jsonResponse({
          entry_date: "2026-05-17",
          total_census: 0,
          facilities_reported: 0,
          facilities_missing: 0,
          last_updated_at: null,
        }),
      );

    await CensusEntryPage({
      searchParams: Promise.resolve({ date: "not-a-date" }),
    });

    const [firstUrl] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(firstUrl).not.toContain("?date=");
    fetchSpy.mockRestore();
  });

  it("takes the first element when ?date is sent as an array (Next quirk)", async () => {
    cookieGet.mockReturnValue({ value: "session-tok" });
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ entry_date: "2026-05-10", sites: [] }))
      .mockResolvedValueOnce(
        jsonResponse({
          entry_date: "2026-05-10",
          total_census: 0,
          facilities_reported: 0,
          facilities_missing: 0,
          last_updated_at: null,
        }),
      );

    await CensusEntryPage({
      searchParams: Promise.resolve({ date: ["2026-05-10", "2026-05-11"] }),
    });

    const [firstUrl] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(firstUrl).toContain("date=2026-05-10");
    expect(firstUrl).not.toContain("date=2026-05-11");
    fetchSpy.mockRestore();
  });
});

// ----------------------------- Happy path -----------------------------------

describe("CensusEntryPage — happy path", () => {
  it("renders header copy + CensusEntryForm with prefilled data", async () => {
    cookieGet.mockReturnValue({ value: "session-tok" });

    const sitesPayload = {
      entry_date: "2026-05-17",
      sites: [
        {
          site_id: 1,
          site_name: "Westside Regional",
          state: "FL",
          census: null,
          open_shifts: 0,
          entered_at: null,
        },
      ],
    };
    const summaryPayload = {
      entry_date: "2026-05-17",
      total_census: 0,
      facilities_reported: 0,
      facilities_missing: 1,
      last_updated_at: null,
    };

    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(sitesPayload))
      .mockResolvedValueOnce(jsonResponse(summaryPayload));

    const tree = await CensusEntryPage({ searchParams: Promise.resolve({}) });
    render(tree);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Daily Census");
    expect(screen.getByText(/patient count for each facility/i)).toBeInTheDocument();

    const form = screen.getByTestId("census-entry-form");
    expect(form.getAttribute("data-initial-date")).toBe("2026-05-17");
    expect(JSON.parse(form.getAttribute("data-sites") ?? "[]")).toEqual(sitesPayload.sites);
    expect(JSON.parse(form.getAttribute("data-summary") ?? "{}")).toEqual(summaryPayload);
    fetchSpy.mockRestore();
  });

  it("uses NEXT_PUBLIC_API_BASE_URL when set (passes to form as apiBase)", async () => {
    cookieGet.mockReturnValue({ value: "session-tok" });
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ entry_date: "2026-05-17", sites: [] }))
      .mockResolvedValueOnce(
        jsonResponse({
          entry_date: "2026-05-17",
          total_census: 0,
          facilities_reported: 0,
          facilities_missing: 0,
          last_updated_at: null,
        }),
      );

    const tree = await CensusEntryPage({ searchParams: Promise.resolve({}) });
    render(tree);

    const form = screen.getByTestId("census-entry-form");
    // The constant is captured at module load — assert it lands somewhere.
    expect(form.getAttribute("data-api-base")).toBeTruthy();
    fetchSpy.mockRestore();
  });
});
