// @vitest-environment happy-dom
//
// ScorecardsPage server-component tests + the local MgmaBandChip /
// ScorecardCard / Tile helpers. The page also embeds branching tone
// logic (rank<=5 / rank>=40 / between), comp-redaction banner, and
// the PIP/VACANT/Active status badges — all asserted here.

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const scorecardsMock = vi.fn();

vi.mock("@/lib/api-client", () => ({
  api: {
    scorecards: () => scorecardsMock(),
  },
}));

import ScorecardsPage from "@/app/scorecards/page";

function makeCard(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    physician_id: 1,
    name: "Dr. Alice",
    site: "Westside Regional",
    state: "FL",
    employment_type: "W2",
    comp_model: "SALARY",
    status: "ACTIVE",
    rank: 10,
    rvu_90d: 5400,
    below_fmv: false,
    mgma_band: "50_75",
    mgma_p50_usd: 290_000,
    effective_comp_usd: 285_000,
    fmv_source_note: "MGMA 2024 IM Hospitalist (national)",
    revenue_per_fte_usd: null,
    encounters_per_day: null,
    documentation_score_pct: null,
    chart_turnaround_days: null,
    ...overrides,
  };
}

async function renderPage() {
  const tree = await ScorecardsPage();
  return render(tree);
}

describe("ScorecardsPage (server component)", () => {
  beforeEach(() => {
    scorecardsMock.mockReset();
  });

  it("renders the header + sensitive-data banner", async () => {
    scorecardsMock.mockResolvedValue([makeCard()]);

    await renderPage();

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Doctor Scorecards");
    expect(screen.getByText(/Sensitive data/i)).toBeInTheDocument();
  });

  it("renders the 'Comp $ redacted' notice when the first card has null effective_comp_usd", async () => {
    scorecardsMock.mockResolvedValue([makeCard({ effective_comp_usd: null })]);

    await renderPage();

    expect(screen.getByText(/Comp \$ redacted/)).toBeInTheDocument();
  });

  it("omits the redacted notice when comp is visible (effective_comp_usd is a number)", async () => {
    scorecardsMock.mockResolvedValue([makeCard({ effective_comp_usd: 280_000 })]);

    await renderPage();

    expect(screen.queryByText(/Comp \$ redacted/)).toBeNull();
  });

  it("renders one ScorecardCard per scorecard, sorted by rank ascending", async () => {
    scorecardsMock.mockResolvedValue([
      makeCard({ physician_id: 1, name: "Dr. C", rank: 30 }),
      makeCard({ physician_id: 2, name: "Dr. A", rank: 1 }),
      makeCard({ physician_id: 3, name: "Dr. B", rank: 15 }),
    ]);

    await renderPage();

    const names = screen.getAllByText(/^Dr\. [A-Z]$/).map((el) => el.textContent);
    expect(names).toEqual(["Dr. A", "Dr. B", "Dr. C"]);
  });

  it("colors rank green when rank <= 5 (top performer)", async () => {
    scorecardsMock.mockResolvedValue([makeCard({ rank: 3 })]);
    await renderPage();
    expect(screen.getByText("#3").className).toContain("text-emerald-600");
  });

  it("colors rank red when rank >= 40 (PIP zone)", async () => {
    scorecardsMock.mockResolvedValue([makeCard({ rank: 42 })]);
    await renderPage();
    expect(screen.getByText("#42").className).toContain("text-red-600");
  });

  it("colors rank slate-900 (neutral) when rank is between 6 and 39", async () => {
    scorecardsMock.mockResolvedValue([makeCard({ rank: 20 })]);
    await renderPage();
    expect(screen.getByText("#20").className).toContain("text-slate-900");
  });

  it("renders an MGMA band chip with the documented label per band", async () => {
    scorecardsMock.mockResolvedValue([
      makeCard({ physician_id: 1, mgma_band: "below_25" }),
      makeCard({ physician_id: 2, mgma_band: "above_90" }),
    ]);

    await renderPage();

    expect(screen.getByText(/MGMA Below 25th/)).toBeInTheDocument();
    expect(screen.getByText(/MGMA Above 90th/)).toBeInTheDocument();
  });

  it("renders the effective_comp + p50 line when comp is visible", async () => {
    scorecardsMock.mockResolvedValue([
      makeCard({ effective_comp_usd: 285_000, mgma_p50_usd: 290_000 }),
    ]);

    await renderPage();

    // usd(285000) → "$285,000"; usd(290000) → "$290,000"
    expect(screen.getByText("$285,000")).toBeInTheDocument();
    expect(screen.getByText(/MGMA p50 \$290,000/)).toBeInTheDocument();
  });

  it("renders '$ redacted' inline when comp is null", async () => {
    scorecardsMock.mockResolvedValue([makeCard({ effective_comp_usd: null })]);

    await renderPage();

    // Two occurrences: one in the banner, one in the card. getAllByText covers both.
    const redacted = screen.getAllByText(/redacted/i);
    expect(redacted.length).toBeGreaterThanOrEqual(2);
  });

  it("renders 'PIP Active' badge for PIP status", async () => {
    scorecardsMock.mockResolvedValue([makeCard({ status: "PIP" })]);
    await renderPage();
    expect(screen.getByText("PIP Active")).toBeInTheDocument();
  });

  it("renders 'VACANT' badge for VACANT status", async () => {
    scorecardsMock.mockResolvedValue([makeCard({ status: "VACANT" })]);
    await renderPage();
    expect(screen.getByText("VACANT")).toBeInTheDocument();
  });

  it("renders 'Active' badge for ACTIVE status (default)", async () => {
    scorecardsMock.mockResolvedValue([makeCard({ status: "ACTIVE" })]);
    await renderPage();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("renders 'Below FMV' chip when below_fmv=true (alongside the status badge)", async () => {
    scorecardsMock.mockResolvedValue([makeCard({ below_fmv: true, status: "ACTIVE" })]);
    await renderPage();
    // 'Below FMV' appears in both the filter <option> at the top AND the
    // chip on the card → expect 2 occurrences when below_fmv=true.
    expect(screen.getAllByText("Below FMV")).toHaveLength(2);
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("omits the Below FMV chip when below_fmv=false (only the filter option remains)", async () => {
    scorecardsMock.mockResolvedValue([makeCard({ below_fmv: false })]);
    await renderPage();
    // Only the filter <option> renders 'Below FMV'; the chip is absent.
    expect(screen.getAllByText("Below FMV")).toHaveLength(1);
  });

  it("renders 'em-dash' placeholders for P2 tiles (revenue, doc score, chart turn) when null", async () => {
    scorecardsMock.mockResolvedValue([makeCard()]);
    await renderPage();

    // 3 P2 tiles render '—' when their value is null
    const placeholders = screen.getAllByText("—");
    expect(placeholders.length).toBeGreaterThanOrEqual(3);
  });

  it("renders the FMV reference card when fmv_source_note is present on the first card", async () => {
    scorecardsMock.mockResolvedValue([makeCard({ fmv_source_note: "MGMA 2024 IM Hospitalist" })]);
    await renderPage();
    expect(screen.getByText(/MGMA 2024 IM Hospitalist/)).toBeInTheDocument();
  });

  it("omits the FMV reference card when fmv_source_note is null", async () => {
    scorecardsMock.mockResolvedValue([makeCard({ fmv_source_note: null })]);
    await renderPage();
    expect(screen.queryByText(/FMV reference:/)).toBeNull();
  });

  it("calls api.scorecards exactly once", async () => {
    scorecardsMock.mockResolvedValue([]);
    await renderPage();
    expect(scorecardsMock).toHaveBeenCalledTimes(1);
  });

  it("renders cleanly when the scorecards list is empty (P2 footnote still shows)", async () => {
    scorecardsMock.mockResolvedValue([]);
    await renderPage();

    expect(screen.getByText(/Grey tiles are P2 deliverables/)).toBeInTheDocument();
    // No physician cards rendered
    expect(screen.queryByText(/^#\d+$/)).toBeNull();
  });
});
