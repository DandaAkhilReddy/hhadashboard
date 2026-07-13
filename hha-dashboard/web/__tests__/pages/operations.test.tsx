// @vitest-environment happy-dom
//
// OperationsPage server-component tests. The most table-heavy dashboard
// page — splits sites by state, renders FL/TX tables with extensive
// tone branching on variance + open_shifts + MD status, plus a
// header status line that toggles on facilities_reported.

import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const operationsSummaryMock = vi.fn();
const sitesTodayMock = vi.fn();

vi.mock("@/lib/api-client", () => ({
  api: {
    operationsSummary: () => operationsSummaryMock(),
    sitesToday: () => sitesTodayMock(),
  },
}));

// next/link in app router renders <a href>. Passthrough.
vi.mock("next/link", () => ({
  __esModule: true,
  default: ({
    href,
    children,
    className,
  }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

import OperationsPage from "@/app/operations/page";

const SUMMARY = {
  total_fl_census: 1234,
  total_tx_census: 480,
  total_fl_3mo_avg: 1300,
  census_variance_vs_avg: -66,
  sites_below_avg: 3,
  open_shifts_total: 8,
  fl_site_count: 7,
  tx_site_count: 4,
  facilities_reported: 9,
  facilities_missing: 2,
  last_updated_at: "2026-05-14T15:30:00Z",
};

function makeSite(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    id: 1,
    name: "Westside Regional",
    state: "FL",
    medical_director: "Dr. Alice",
    md_status: "ACTIVE",
    liaison: "Mary",
    census_today: 198,
    census_3mo_avg: 200,
    mtd_avg: 195.4,
    variance_pct: -1.0,
    open_shifts: 0,
    contract_end: "2027-12-31T00:00:00Z",
    annual_subsidy_usd: 250_000,
    ...overrides,
  };
}

async function renderPage() {
  const tree = await OperationsPage();
  return render(tree);
}

describe("OperationsPage (server component)", () => {
  beforeEach(() => {
    operationsSummaryMock.mockReset();
    sitesTodayMock.mockReset();
  });

  it("renders the header + subtitle + 'Enter Today's Data' link", async () => {
    operationsSummaryMock.mockResolvedValue(SUMMARY);
    sitesTodayMock.mockResolvedValue([]);

    await renderPage();

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Operations Board");
    expect(screen.getByText(/11 sites/)).toBeInTheDocument();
    const enterLink = screen.getByRole("link", { name: /Enter Today.s Data/i });
    expect(enterLink.getAttribute("href")).toBe("/daily-census");
  });

  it("renders the 'X of N reported · last update' header pill when facilities_reported > 0", async () => {
    operationsSummaryMock.mockResolvedValue(SUMMARY);
    sitesTodayMock.mockResolvedValue([]);

    await renderPage();

    expect(screen.getByText(/9 of 11 reported · last update/)).toBeInTheDocument();
  });

  it("renders 'No census submitted yet today' when facilities_reported = 0", async () => {
    operationsSummaryMock.mockResolvedValue({ ...SUMMARY, facilities_reported: 0 });
    sitesTodayMock.mockResolvedValue([]);

    await renderPage();

    expect(screen.getByText(/No census submitted yet today/)).toBeInTheDocument();
  });

  it("renders the four headline metric cards", async () => {
    operationsSummaryMock.mockResolvedValue(SUMMARY);
    sitesTodayMock.mockResolvedValue([]);

    await renderPage();

    expect(screen.getByText("1,234")).toBeInTheDocument(); // FL census
    expect(screen.getByText("480")).toBeInTheDocument(); // TX census
    expect(screen.getByText("8")).toBeInTheDocument(); // open shifts
    expect(screen.getByText("3")).toBeInTheDocument(); // sites below avg
    // signed(-66) -> "-66"; rendered as "-66 vs 3-mo avg"
    expect(screen.getByText(/-66 vs 3-mo avg/)).toBeInTheDocument();
    expect(screen.getByText(/of 7 FL sites/)).toBeInTheDocument();
  });

  it("uses warn tone on Open Shifts metric when > 5", async () => {
    operationsSummaryMock.mockResolvedValue({ ...SUMMARY, open_shifts_total: 10 });
    sitesTodayMock.mockResolvedValue([]);

    await renderPage();

    const openShifts = screen.getByText("10");
    expect(openShifts.className).toContain("text-amber-600");
  });

  it("uses neutral tone on Open Shifts metric when <= 5", async () => {
    operationsSummaryMock.mockResolvedValue({ ...SUMMARY, open_shifts_total: 3 });
    sitesTodayMock.mockResolvedValue([]);

    await renderPage();

    const openShifts = screen.getByText("3", { selector: ".text-slate-900" });
    expect(openShifts).toBeInTheDocument();
  });

  it("splits sites into FL + TX tables", async () => {
    operationsSummaryMock.mockResolvedValue(SUMMARY);
    sitesTodayMock.mockResolvedValue([
      makeSite({ id: 1, name: "Westside Regional", state: "FL" }),
      makeSite({ id: 2, name: "Pearland", state: "TX", census_today: 95 }),
    ]);

    await renderPage();

    expect(screen.getByText("Florida Sites — Daily Detail")).toBeInTheDocument();
    expect(screen.getByText("Texas Sites")).toBeInTheDocument();
    // Each table shows its site
    expect(screen.getByText("Westside Regional")).toBeInTheDocument();
    expect(screen.getByText("Pearland")).toBeInTheDocument();
  });

  it("renders the FL site count + TX site count badges from filtered arrays", async () => {
    operationsSummaryMock.mockResolvedValue(SUMMARY);
    sitesTodayMock.mockResolvedValue([
      makeSite({ id: 1, name: "FL-1", state: "FL" }),
      makeSite({ id: 2, name: "FL-2", state: "FL" }),
      makeSite({ id: 3, name: "TX-1", state: "TX" }),
    ]);

    await renderPage();

    // FL header badge: "2 sites" (after .filter), TX: "1 sites"
    expect(screen.getByText("2 sites")).toBeInTheDocument();
    expect(screen.getByText("1 sites")).toBeInTheDocument();
  });

  it.each([
    [-25, "text-red-600"],
    [-8, "text-amber-600"],
    [3, "text-emerald-600"],
  ] as const)("applies variance=%s tone class %s", async (variance, expectedClass) => {
    operationsSummaryMock.mockResolvedValue(SUMMARY);
    sitesTodayMock.mockResolvedValue([
      makeSite({ id: 1, name: `var-${variance}`, state: "FL", variance_pct: variance }),
    ]);

    await renderPage();

    // pct(-25) -> "-25.0%" etc.; locate the variance cell by its text.
    const varText = `${variance.toFixed(1)}%`;
    const cells = screen.getAllByText(varText);
    // At least one cell should carry the expected tone class
    expect(cells.some((c) => c.className.includes(expectedClass))).toBe(true);
  });

  it("renders '—' placeholders when site fields are null", async () => {
    operationsSummaryMock.mockResolvedValue(SUMMARY);
    sitesTodayMock.mockResolvedValue([
      makeSite({
        id: 1,
        name: "Nullsite",
        state: "FL",
        medical_director: null,
        liaison: null,
        census_today: null,
        census_3mo_avg: null,
        mtd_avg: null,
        variance_pct: null,
        open_shifts: null,
        contract_end: null,
        md_status: null,
      }),
    ]);

    await renderPage();

    // Several em-dashes render across the columns
    const placeholders = screen.getAllByText("—");
    expect(placeholders.length).toBeGreaterThanOrEqual(5);
  });

  it.each([
    [0, "text-emerald-600"],
    [2, "text-amber-600"],
    [5, "text-red-600"],
  ] as const)("applies open_shifts=%s tone class", async (shifts, expectedClass) => {
    operationsSummaryMock.mockResolvedValue(SUMMARY);
    sitesTodayMock.mockResolvedValue([
      makeSite({ id: 1, name: `s-${shifts}`, state: "FL", open_shifts: shifts }),
    ]);

    await renderPage();

    // The open_shifts cell renders the count
    const shiftCells = screen.getAllByText(String(shifts));
    expect(shiftCells.some((c) => c.className.includes(expectedClass))).toBe(true);
  });

  it("renders MD status badges: ACTIVE -> Active, VACANT -> 'VACANT', PIP -> 'PIP'", async () => {
    operationsSummaryMock.mockResolvedValue(SUMMARY);
    sitesTodayMock.mockResolvedValue([
      makeSite({ id: 1, name: "Active-Site", state: "FL", md_status: "ACTIVE" }),
      makeSite({ id: 2, name: "Vacant-Site", state: "FL", md_status: "VACANT" }),
      makeSite({ id: 3, name: "PIP-Site", state: "FL", md_status: "PIP" }),
    ]);

    await renderPage();

    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("VACANT")).toBeInTheDocument();
    // 'PIP' appears in two places: status badge + '(PIP)' inline after MD name
    expect(screen.getAllByText("PIP").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("(PIP)")).toBeInTheDocument();
  });

  it("renders TX status badge: VACANT -> 'No MD' (different from FL's 'VACANT')", async () => {
    operationsSummaryMock.mockResolvedValue(SUMMARY);
    sitesTodayMock.mockResolvedValue([
      makeSite({ id: 1, name: "TX-Vacant", state: "TX", md_status: "VACANT" }),
    ]);

    await renderPage();

    expect(screen.getByText("No MD")).toBeInTheDocument();
  });

  it("renders site name as a link to /operations/<id>", async () => {
    operationsSummaryMock.mockResolvedValue(SUMMARY);
    sitesTodayMock.mockResolvedValue([
      makeSite({ id: 42, name: "Westside Regional", state: "FL" }),
    ]);

    await renderPage();

    const link = screen.getByRole("link", { name: /Westside Regional/ });
    expect(link.getAttribute("href")).toBe("/operations/42");
  });

  it("renders the FL table header columns", async () => {
    operationsSummaryMock.mockResolvedValue(SUMMARY);
    sitesTodayMock.mockResolvedValue([]);

    await renderPage();

    const tables = screen.getAllByRole("table");
    // First table is FL (more columns), second is TX
    const flTable = tables[0] as HTMLElement;
    for (const col of [
      "Site",
      "Medical Director",
      "Liaison",
      "Census",
      "3-Mo",
      "MTD",
      "Var",
      "Open Shifts",
      "Contract Thru",
      "Subsidy",
      "Status",
    ]) {
      expect(within(flTable).getByText(col)).toBeInTheDocument();
    }
  });

  it("calls both api methods exactly once", async () => {
    operationsSummaryMock.mockResolvedValue(SUMMARY);
    sitesTodayMock.mockResolvedValue([]);

    await renderPage();

    expect(operationsSummaryMock).toHaveBeenCalledTimes(1);
    expect(sitesTodayMock).toHaveBeenCalledTimes(1);
  });
});
