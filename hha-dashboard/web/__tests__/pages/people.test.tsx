// @vitest-environment happy-dom
//
// PeoplePage server-component tests. Same pattern as ClinicalPage:
// mock @/lib/api-client, invoke the async page function, render the
// resolved JSX, assert.

import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const peopleSummaryMock = vi.fn();
const openPositionsBySiteMock = vi.fn();

vi.mock("@/lib/api-client", () => ({
  api: {
    peopleSummary: () => peopleSummaryMock(),
    openPositionsBySite: () => openPositionsBySiteMock(),
  },
}));

import PeoplePage from "@/app/people/page";

const SUMMARY = {
  headcount_w2: 187,
  headcount_1099: 42,
  headcount_total: 229,
  open_positions_total: 14,
  turnover_90d_pct: 8.5,
  below_fmv_count: 3,
};

const POSITIONS = [
  { site: "Westside Regional", state: "FL", count: 5, severity: "high" as const },
  { site: "Woodmont", state: "FL", count: 3, severity: "medium" as const },
  { site: "Pearland", state: "TX", count: 1, severity: "low" as const },
];

async function renderPage() {
  const tree = await PeoplePage();
  return render(tree);
}

describe("PeoplePage (server component)", () => {
  beforeEach(() => {
    peopleSummaryMock.mockReset();
    openPositionsBySiteMock.mockReset();
  });

  it("renders header + four headline metric cards with formatted values", async () => {
    peopleSummaryMock.mockResolvedValue(SUMMARY);
    openPositionsBySiteMock.mockResolvedValue([]);

    await renderPage();

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("People & Pipeline");
    // num(187) = "187"
    expect(screen.getByText("187")).toBeInTheDocument();
    // num(42)
    expect(screen.getByText("42")).toBeInTheDocument();
    // pct(8.5) = "8.5%"
    expect(screen.getByText("8.5%")).toBeInTheDocument();
    // num(14) — also in below_fmv = 3 but distinct value
    expect(screen.getByText("14")).toBeInTheDocument();
  });

  it("renders the open-positions table with one row per site", async () => {
    peopleSummaryMock.mockResolvedValue(SUMMARY);
    openPositionsBySiteMock.mockResolvedValue(POSITIONS);

    await renderPage();

    expect(screen.getByText("Westside Regional")).toBeInTheDocument();
    expect(screen.getByText("Woodmont")).toBeInTheDocument();
    expect(screen.getByText("Pearland")).toBeInTheDocument();
  });

  it("renders the table header columns", async () => {
    peopleSummaryMock.mockResolvedValue(SUMMARY);
    openPositionsBySiteMock.mockResolvedValue([POSITIONS[0]]);

    await renderPage();

    const table = screen.getByRole("table");
    expect(within(table).getByText("Site")).toBeInTheDocument();
    expect(within(table).getByText("State")).toBeInTheDocument();
    expect(within(table).getByText("Count")).toBeInTheDocument();
  });

  it.each([
    ["high", "text-red-600"],
    ["medium", "text-amber-600"],
    ["low", "text-emerald-600"],
  ] as const)(
    "applies %s severity tone class to the count cell",
    async (severity, expectedClass) => {
      peopleSummaryMock.mockResolvedValue(SUMMARY);
      openPositionsBySiteMock.mockResolvedValue([
        { site: `Test-${severity}`, state: "FL", count: 99, severity },
      ]);

      await renderPage();

      const countCell = screen.getByText("99");
      expect(countCell.className).toContain(expectedClass);
    },
  );

  it("renders the 'Providers below FMV' card with the comp_viewer badge + count", async () => {
    peopleSummaryMock.mockResolvedValue({ ...SUMMARY, below_fmv_count: 7 });
    openPositionsBySiteMock.mockResolvedValue([]);

    await renderPage();

    expect(screen.getByText(/Providers below FMV/i)).toBeInTheDocument();
    expect(screen.getByText(/comp_viewer only/)).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("uses 'warn' tone on the Open Positions metric card", async () => {
    peopleSummaryMock.mockResolvedValue(SUMMARY);
    openPositionsBySiteMock.mockResolvedValue([]);

    await renderPage();

    // num(14) renders in the warn-toned MetricCard value
    const openPositionsValue = screen.getByText("14");
    expect(openPositionsValue.className).toContain("text-amber-600");
  });

  it("calls both api methods exactly once on render", async () => {
    peopleSummaryMock.mockResolvedValue(SUMMARY);
    openPositionsBySiteMock.mockResolvedValue([]);

    await renderPage();

    expect(peopleSummaryMock).toHaveBeenCalledTimes(1);
    expect(openPositionsBySiteMock).toHaveBeenCalledTimes(1);
  });

  it("renders an empty open-positions table when the list is empty (no crash)", async () => {
    peopleSummaryMock.mockResolvedValue(SUMMARY);
    openPositionsBySiteMock.mockResolvedValue([]);

    const { container } = await renderPage();

    const table = screen.getByRole("table");
    const tbody = table.querySelector("tbody");
    expect(tbody?.children.length ?? 0).toBe(0);
    expect(container.firstChild).not.toBeNull();
  });
});
