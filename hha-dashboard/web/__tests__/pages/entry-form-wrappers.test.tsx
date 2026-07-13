// @vitest-environment happy-dom
//
// Server-component WRAPPER tests for the 5 entry-form pages. Each page
// is a thin async function that:
//   1. fetches initial state from api-client (with .catch fallback)
//   2. parses searchParams (date/period selection)
//   3. renders <PageHeader /> + a client-component form
//
// The form components themselves (DailyCensusForm, MonthlyFinanceForm,
// WeeklyClinicalForm, WeeklyHrForm, UploadDropZone) are large stateful
// client components with their own surface — they get covered separately.
// Here we mock them to bypass-passthrough divs that surface the props
// the page passed, so the page-level contract (initial state + fallback)
// is what we assert on.

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getDailyCensusMock = vi.fn();
const getMonthlyFinanceMock = vi.fn();
const getWeeklyClinicalMock = vi.fn();
const getWeeklyHrMock = vi.fn();
const listUploadsMock = vi.fn();

vi.mock("@/lib/api-client", () => ({
  api: {
    getDailyCensus: () => getDailyCensusMock(),
    getMonthlyFinance: (year?: number, month?: number) => getMonthlyFinanceMock(year, month),
    getWeeklyClinical: (weekEnding?: string) => getWeeklyClinicalMock(weekEnding),
    getWeeklyHr: (weekEnding?: string) => getWeeklyHrMock(weekEnding),
    listUploads: () => listUploadsMock(),
  },
}));

// Each form component renders a passthrough div with data-testid so the
// test can read the props that the page passed.
vi.mock("@/app/daily-census/DailyCensusForm", () => ({
  DailyCensusForm: ({ initialRows }: { initialRows: unknown[] }) => (
    <div data-testid="daily-census-form" data-rows={JSON.stringify(initialRows)} />
  ),
}));

vi.mock("@/app/monthly-finance/MonthlyFinanceForm", () => ({
  MonthlyFinanceForm: (props: {
    initialYear: number;
    initialMonth: number;
    initialRows: unknown[];
  }) => (
    <div
      data-testid="monthly-finance-form"
      data-year={props.initialYear}
      data-month={props.initialMonth}
      data-rows={JSON.stringify(props.initialRows)}
    />
  ),
}));

vi.mock("@/app/weekly-clinical/WeeklyClinicalForm", () => ({
  WeeklyClinicalForm: (props: { initialWeekEnding: string; initialRows: unknown[] }) => (
    <div
      data-testid="weekly-clinical-form"
      data-week-ending={props.initialWeekEnding}
      data-rows={JSON.stringify(props.initialRows)}
    />
  ),
}));

vi.mock("@/app/weekly-hr/WeeklyHrForm", () => ({
  WeeklyHrForm: (props: { initialWeekEnding: string; initial: unknown }) => (
    <div
      data-testid="weekly-hr-form"
      data-week-ending={props.initialWeekEnding}
      data-initial={JSON.stringify(props.initial)}
    />
  ),
}));

vi.mock("@/app/uploads/UploadDropZone", () => ({
  UploadDropZone: ({ initialUploads }: { initialUploads: unknown[] }) => (
    <div data-testid="upload-dropzone" data-uploads={JSON.stringify(initialUploads)} />
  ),
}));

import DailyCensusPage from "@/app/daily-census/page";
import MonthlyFinancePage from "@/app/monthly-finance/page";
import UploadsPage from "@/app/uploads/page";
import WeeklyClinicalPage from "@/app/weekly-clinical/page";
import WeeklyHrPage from "@/app/weekly-hr/page";

describe("DailyCensusPage", () => {
  beforeEach(() => {
    getDailyCensusMock.mockReset();
  });

  it("passes server-fetched rows to DailyCensusForm", async () => {
    const rows = [
      { site_id: 1, site_name: "Westside Regional", state: "FL", census: 198, open_shifts: 0 },
    ];
    getDailyCensusMock.mockResolvedValue(rows);

    render(await DailyCensusPage());

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Enter Today's Census");
    const form = screen.getByTestId("daily-census-form");
    expect(JSON.parse(form.getAttribute("data-rows") || "[]")).toEqual(rows);
  });

  it("falls back to empty rows when the fetch rejects", async () => {
    getDailyCensusMock.mockRejectedValue(new Error("boom"));

    render(await DailyCensusPage());

    const form = screen.getByTestId("daily-census-form");
    expect(JSON.parse(form.getAttribute("data-rows") || "[]")).toEqual([]);
  });

  it("renders the idempotent-save reminder in the subtitle", async () => {
    getDailyCensusMock.mockResolvedValue([]);
    render(await DailyCensusPage());
    expect(screen.getByText(/Re-saving the same day overwrites/)).toBeInTheDocument();
  });
});

describe("MonthlyFinancePage", () => {
  beforeEach(() => {
    getMonthlyFinanceMock.mockReset();
  });

  it("uses ?year + ?month from searchParams when provided", async () => {
    getMonthlyFinanceMock.mockResolvedValue([]);

    render(
      await MonthlyFinancePage({
        searchParams: Promise.resolve({ year: "2026", month: "3" }),
      }),
    );

    expect(getMonthlyFinanceMock).toHaveBeenCalledWith(2026, 3);
    const form = screen.getByTestId("monthly-finance-form");
    expect(Number(form.getAttribute("data-year"))).toBe(2026);
    expect(Number(form.getAttribute("data-month"))).toBe(3);
  });

  it("defaults to last completed month when no params (computes year + month dynamically)", async () => {
    getMonthlyFinanceMock.mockResolvedValue([]);

    render(await MonthlyFinancePage({ searchParams: Promise.resolve({}) }));

    expect(getMonthlyFinanceMock).toHaveBeenCalledTimes(1);
    const args = getMonthlyFinanceMock.mock.calls[0] as [number, number];
    const [year, month] = args;
    // Locked contract from defaultPeriod(): month = getMonth() OR 12 (Jan rollover);
    // year is currentYear unless January, then currentYear - 1
    const now = new Date();
    const expectedMonth = now.getMonth() === 0 ? 12 : now.getMonth();
    const expectedYear = now.getMonth() === 0 ? now.getFullYear() - 1 : now.getFullYear();
    expect(month).toBe(expectedMonth);
    expect(year).toBe(expectedYear);
  });

  it("falls back to empty rows when the fetch rejects", async () => {
    getMonthlyFinanceMock.mockRejectedValue(new Error("boom"));

    render(
      await MonthlyFinancePage({
        searchParams: Promise.resolve({ year: "2026", month: "5" }),
      }),
    );

    const form = screen.getByTestId("monthly-finance-form");
    expect(JSON.parse(form.getAttribute("data-rows") || "[]")).toEqual([]);
  });

  it("renders the header + Sandy/Maribel owner copy", async () => {
    getMonthlyFinanceMock.mockResolvedValue([]);
    render(await MonthlyFinancePage({ searchParams: Promise.resolve({}) }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/Monthly Finance Entry/);
    expect(screen.getByText(/Sandy Collins \/ Maribel Reyes/)).toBeInTheDocument();
  });
});

describe("WeeklyClinicalPage", () => {
  beforeEach(() => {
    getWeeklyClinicalMock.mockReset();
  });

  it("uses ?week_ending from searchParams when provided", async () => {
    getWeeklyClinicalMock.mockResolvedValue([]);

    render(
      await WeeklyClinicalPage({
        searchParams: Promise.resolve({ week_ending: "2026-05-10" }),
      }),
    );

    expect(getWeeklyClinicalMock).toHaveBeenCalledWith("2026-05-10");
    const form = screen.getByTestId("weekly-clinical-form");
    expect(form.getAttribute("data-week-ending")).toBe("2026-05-10");
  });

  it("defaults to last-Sunday (server-computed ISO YYYY-MM-DD) when no param", async () => {
    getWeeklyClinicalMock.mockResolvedValue([]);

    render(await WeeklyClinicalPage({ searchParams: Promise.resolve({}) }));

    // The fetch was called with SOME ISO date string
    const calledArg = getWeeklyClinicalMock.mock.calls[0]?.[0] as string;
    expect(calledArg).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("falls back to empty rows when the fetch rejects", async () => {
    getWeeklyClinicalMock.mockRejectedValue(new Error("boom"));

    render(
      await WeeklyClinicalPage({
        searchParams: Promise.resolve({ week_ending: "2026-05-10" }),
      }),
    );

    const form = screen.getByTestId("weekly-clinical-form");
    expect(JSON.parse(form.getAttribute("data-rows") || "[]")).toEqual([]);
  });
});

describe("WeeklyHrPage", () => {
  beforeEach(() => {
    getWeeklyHrMock.mockReset();
  });

  it("uses ?week_ending from searchParams when provided", async () => {
    const initial = { week_ending: "2026-05-10", headcount_w2: 100 };
    getWeeklyHrMock.mockResolvedValue(initial);

    render(
      await WeeklyHrPage({
        searchParams: Promise.resolve({ week_ending: "2026-05-10" }),
      }),
    );

    expect(getWeeklyHrMock).toHaveBeenCalledWith("2026-05-10");
    const form = screen.getByTestId("weekly-hr-form");
    expect(JSON.parse(form.getAttribute("data-initial") || "null")).toEqual(initial);
  });

  it("falls back to null when the fetch rejects (page contract: initial can be null)", async () => {
    getWeeklyHrMock.mockRejectedValue(new Error("boom"));

    render(
      await WeeklyHrPage({
        searchParams: Promise.resolve({ week_ending: "2026-05-10" }),
      }),
    );

    const form = screen.getByTestId("weekly-hr-form");
    expect(form.getAttribute("data-initial")).toBe("null");
  });

  it("renders the header + Andrea owner copy", async () => {
    getWeeklyHrMock.mockResolvedValue(null);
    render(await WeeklyHrPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/Weekly HR Snapshot/);
    expect(screen.getByText(/Andrea/)).toBeInTheDocument();
  });
});

describe("UploadsPage", () => {
  beforeEach(() => {
    listUploadsMock.mockReset();
  });

  it("passes the initial uploads list to UploadDropZone", async () => {
    const uploads = [
      { id: 1, filename: "x.pdf", status: "processed" },
      { id: 2, filename: "y.xlsx", status: "uploaded" },
    ];
    listUploadsMock.mockResolvedValue(uploads);

    render(await UploadsPage());

    const dropzone = screen.getByTestId("upload-dropzone");
    expect(JSON.parse(dropzone.getAttribute("data-uploads") || "[]")).toEqual(uploads);
  });

  it("falls back to empty uploads list when the fetch rejects", async () => {
    listUploadsMock.mockRejectedValue(new Error("boom"));

    render(await UploadsPage());

    const dropzone = screen.getByTestId("upload-dropzone");
    expect(JSON.parse(dropzone.getAttribute("data-uploads") || "[]")).toEqual([]);
  });

  it("renders the dev-mode hint about Azurite + the upload_ingest worker", async () => {
    listUploadsMock.mockResolvedValue([]);
    render(await UploadsPage());
    expect(screen.getByText(/Dev mode: upload hits Azurite/)).toBeInTheDocument();
  });
});
