// @vitest-environment happy-dom
//
// CensusEntryForm — the standalone "census portal" multi-row entry surface
// for the non-Entra (cookie-session) caregivers. Distinct from
// DailyCensusForm: per-row lock/edit toggle, summary recomputed locally,
// raw fetch (not useApiBrowser), 401 → /census/login redirect, and a
// logout button that POSTs and replaces the route.

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
const replaceMock = vi.fn();
const refreshMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: replaceMock, refresh: refreshMock }),
}));

import {
  CensusEntryForm,
  type PortalSite,
  type PortalSummary,
} from "@/app/census/entry/CensusEntryForm";

function site(overrides: Partial<PortalSite> = {}): PortalSite {
  return {
    site_id: 1,
    site_name: "Westside Regional",
    state: "FL",
    census: null,
    open_shifts: 0,
    entered_at: null,
    ...overrides,
  };
}

const SUMMARY_EMPTY: PortalSummary = {
  entry_date: "2026-05-13",
  total_census: 0,
  facilities_reported: 0,
  facilities_missing: 3,
  last_updated_at: null,
};

const SUMMARY_PARTIAL: PortalSummary = {
  entry_date: "2026-05-13",
  total_census: 198,
  facilities_reported: 1,
  facilities_missing: 2,
  last_updated_at: "2026-05-13T15:30:00Z",
};

describe("CensusEntryForm — render + hydration", () => {
  beforeEach(() => {
    pushMock.mockReset();
    replaceMock.mockReset();
    refreshMock.mockReset();
  });

  it("renders one row per site with name + state badge", () => {
    render(
      <CensusEntryForm
        initialDate="2026-05-13"
        initialSites={[
          site({ site_id: 1, site_name: "Westside Regional", state: "FL" }),
          site({ site_id: 2, site_name: "Pearland", state: "TX" }),
        ]}
        initialSummary={SUMMARY_EMPTY}
        apiBase=""
      />,
    );

    expect(screen.getByText("Westside Regional")).toBeInTheDocument();
    expect(screen.getByText("Pearland")).toBeInTheDocument();
    expect(screen.getAllByText("FL").length).toBeGreaterThan(0);
    expect(screen.getAllByText("TX").length).toBeGreaterThan(0);
  });

  it("never-entered rows start in editMode (Save button visible, input editable)", () => {
    render(
      <CensusEntryForm
        initialDate="2026-05-13"
        initialSites={[site({ entered_at: null, census: null })]}
        initialSummary={SUMMARY_EMPTY}
        apiBase=""
      />,
    );

    // editMode=true → Save button shown (NOT the locked Enter/Edit branch)
    expect(screen.getByRole("button", { name: /^Save$/i })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Edit$/i })).toBeNull();
  });

  it("entered rows start LOCKED (Edit button visible, value rendered)", () => {
    render(
      <CensusEntryForm
        initialDate="2026-05-13"
        initialSites={[
          site({
            site_id: 1,
            entered_at: "2026-05-13T15:30:00Z",
            census: 250,
          }),
        ]}
        initialSummary={SUMMARY_PARTIAL}
        apiBase=""
      />,
    );

    expect(screen.getByRole("button", { name: /^Edit$/i })).toBeInTheDocument();
    // savedCensus 250 is unique (not duplicated by SummaryCard total_census which is 198)
    expect(screen.getByText("250")).toBeInTheDocument();
  });

  it("renders the SummaryCard quartet", () => {
    render(
      <CensusEntryForm
        initialDate="2026-05-13"
        initialSites={[site()]}
        initialSummary={SUMMARY_PARTIAL}
        apiBase=""
      />,
    );

    expect(screen.getByText("Total Census")).toBeInTheDocument();
    expect(screen.getByText("Facilities Reported")).toBeInTheDocument();
    expect(screen.getByText("Facilities Missing")).toBeInTheDocument();
    expect(screen.getByText("Last Updated")).toBeInTheDocument();
  });

  it("renders the 'No census submitted for this date yet' banner when all missing", () => {
    render(
      <CensusEntryForm
        initialDate="2026-05-13"
        initialSites={[site()]}
        initialSummary={SUMMARY_EMPTY}
        apiBase=""
      />,
    );
    expect(screen.getByText(/No census submitted for this date yet/i)).toBeInTheDocument();
  });

  it("renders 'Census for YYYY-MM-DD' subtitle when not today", () => {
    render(
      <CensusEntryForm
        initialDate="2020-01-01"
        initialSites={[site()]}
        initialSummary={SUMMARY_EMPTY}
        apiBase=""
      />,
    );
    expect(screen.getByText(/Census for 2020-01-01/)).toBeInTheDocument();
  });
});

describe("CensusEntryForm — date picker", () => {
  beforeEach(() => {
    pushMock.mockReset();
    replaceMock.mockReset();
    refreshMock.mockReset();
  });

  it("changing the date pushes /census/entry?date=...", () => {
    render(
      <CensusEntryForm
        initialDate="2026-05-13"
        initialSites={[site()]}
        initialSummary={SUMMARY_EMPTY}
        apiBase=""
      />,
    );

    const dateInput = screen.getByDisplayValue("2026-05-13") as HTMLInputElement;
    fireEvent.change(dateInput, { target: { value: "2026-05-10" } });

    expect(pushMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/census\/entry\?date=2026-05-10/),
    );
  });
});

describe("CensusEntryForm — Edit / Cancel", () => {
  beforeEach(() => {
    pushMock.mockReset();
    replaceMock.mockReset();
    refreshMock.mockReset();
  });

  it("Edit unlocks the row (reveals input + Save button + Cancel button)", () => {
    render(
      <CensusEntryForm
        initialDate="2026-05-13"
        initialSites={[site({ site_id: 1, entered_at: "2026-05-13T15:30:00Z", census: 198 })]}
        initialSummary={SUMMARY_PARTIAL}
        apiBase=""
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Edit/i }));

    expect(screen.getByRole("button", { name: /^Save$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Cancel$/i })).toBeInTheDocument();
    expect((screen.getByRole("spinbutton") as HTMLInputElement).value).toBe("198");
  });

  it("Cancel re-locks the row (Edit button returns)", () => {
    render(
      <CensusEntryForm
        initialDate="2026-05-13"
        initialSites={[site({ site_id: 1, entered_at: "2026-05-13T15:30:00Z", census: 198 })]}
        initialSummary={SUMMARY_PARTIAL}
        apiBase=""
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Edit/i }));
    fireEvent.click(screen.getByRole("button", { name: /^Cancel$/i }));

    expect(screen.getByRole("button", { name: /Edit/i })).toBeInTheDocument();
  });
});

describe("CensusEntryForm — Save row", () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    pushMock.mockReset();
    replaceMock.mockReset();
    refreshMock.mockReset();
    fetchSpy = vi.spyOn(globalThis, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  it("rejects empty census with feedback 'Enter a census number.'", async () => {
    render(
      <CensusEntryForm
        initialDate="2026-05-13"
        initialSites={[site()]}
        initialSummary={SUMMARY_EMPTY}
        apiBase=""
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));
    });

    expect(screen.getByText(/Enter a census number/i)).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("rejects census > 2000 with feedback 'Census must be 0–2000.'", async () => {
    render(
      <CensusEntryForm
        initialDate="2026-05-13"
        initialSites={[site()]}
        initialSummary={SUMMARY_EMPTY}
        apiBase=""
      />,
    );

    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "2001" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));
    });

    expect(screen.getByText(/Census must be 0.2000/)).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("on 401: redirects to /census/login and skips state update", async () => {
    fetchSpy.mockResolvedValueOnce(new Response("", { status: 401 }));

    render(
      <CensusEntryForm
        initialDate="2026-05-13"
        initialSites={[site()]}
        initialSummary={SUMMARY_EMPTY}
        apiBase=""
      />,
    );

    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "198" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));
    });

    expect(replaceMock).toHaveBeenCalledWith("/census/login");
  });

  it("on non-ok non-401: feedback 'Save failed (status): detail'", async () => {
    fetchSpy.mockResolvedValueOnce(new Response("Bad Request", { status: 400 }));

    render(
      <CensusEntryForm
        initialDate="2026-05-13"
        initialSites={[site()]}
        initialSummary={SUMMARY_EMPTY}
        apiBase=""
      />,
    );

    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "198" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));
    });

    await waitFor(() => {
      expect(screen.getByText(/Save failed \(400\): Bad Request/)).toBeInTheDocument();
    });
  });

  it("on success: row locks, savedCensus updates, summary recomputes, router.refresh fires", async () => {
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify([{ site_id: 1, census: 198, entered_at: "2026-05-13T16:00:00Z" }]),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(
      <CensusEntryForm
        initialDate="2026-05-13"
        initialSites={[site({ site_id: 1, site_name: "Westside Regional" })]}
        initialSummary={SUMMARY_EMPTY}
        apiBase=""
      />,
    );

    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "198" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));
    });

    await waitFor(() => {
      expect(refreshMock).toHaveBeenCalled();
    });

    // Row is locked (Edit button replaces Save/Cancel)
    expect(screen.getByRole("button", { name: /Edit/i })).toBeInTheDocument();
  });

  it("on success: server response missing this row yields error feedback", async () => {
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify([{ site_id: 99, census: 1, entered_at: "2026-05-13T16:00:00Z" }]),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(
      <CensusEntryForm
        initialDate="2026-05-13"
        initialSites={[site({ site_id: 1 })]}
        initialSummary={SUMMARY_EMPTY}
        apiBase=""
      />,
    );

    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "198" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));
    });

    await waitFor(() => {
      expect(
        screen.getByText(/Server response missing this row . refresh and retry/),
      ).toBeInTheDocument();
    });
  });

  it("on network/throw failure: feedback carries err.message", async () => {
    fetchSpy.mockRejectedValueOnce(new Error("connection reset"));

    render(
      <CensusEntryForm
        initialDate="2026-05-13"
        initialSites={[site({ site_id: 1 })]}
        initialSummary={SUMMARY_EMPTY}
        apiBase=""
      />,
    );

    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "198" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));
    });

    await waitFor(() => {
      expect(screen.getByText(/connection reset/)).toBeInTheDocument();
    });
  });

  it("posts the correct shape: entry_date + single-row array with site_id+census", async () => {
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify([{ site_id: 1, census: 198, entered_at: "2026-05-13T16:00:00Z" }]),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(
      <CensusEntryForm
        initialDate="2026-05-13"
        initialSites={[site({ site_id: 1 })]}
        initialSummary={SUMMARY_EMPTY}
        apiBase="https://api.example.com"
      />,
    );

    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "198" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));
    });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.example.com/api/v1/census-portal/daily-census");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(JSON.parse(init.body as string)).toEqual({
      entry_date: "2026-05-13",
      rows: [{ site_id: 1, census: 198 }],
    });
  });
});

describe("CensusEntryForm — logout", () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    pushMock.mockReset();
    replaceMock.mockReset();
    refreshMock.mockReset();
    fetchSpy = vi.spyOn(globalThis, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  it("posts to /api/v1/census-portal/logout with credentials and redirects to /census/login", async () => {
    fetchSpy.mockResolvedValueOnce(new Response("", { status: 200 }));

    render(
      <CensusEntryForm
        initialDate="2026-05-13"
        initialSites={[site()]}
        initialSummary={SUMMARY_EMPTY}
        apiBase="https://api.example.com"
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Sign out/i }));
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      "https://api.example.com/api/v1/census-portal/logout",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
    expect(replaceMock).toHaveBeenCalledWith("/census/login");
  });
});
