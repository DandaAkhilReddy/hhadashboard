// @vitest-environment happy-dom
//
// OverviewPage (`/`) server-component tests. The root dashboard
// aggregates 7 api endpoints into 4-board summary cards.

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const operationsSummaryMock = vi.fn();
const financeTodayMock = vi.fn();
const arAgingMock = vi.fn();
const clinicalSummaryMock = vi.fn();
const peopleSummaryMock = vi.fn();
const alertsMock = vi.fn();
const sitesTodayMock = vi.fn();

vi.mock("@/lib/api-client", () => ({
  api: {
    operationsSummary: () => operationsSummaryMock(),
    financeToday: () => financeTodayMock(),
    arAging: () => arAgingMock(),
    clinicalSummary: () => clinicalSummaryMock(),
    peopleSummary: () => peopleSummaryMock(),
    alerts: () => alertsMock(),
    sitesToday: () => sitesTodayMock(),
  },
}));

import OverviewPage from "@/app/page";

const OPS = {
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
  last_updated_at: null,
};
const FIN = {
  fl_daily_actual: 156_000,
  fl_daily_target: 200_000,
  fl_daily_delta: -44_000,
  fl_source_system: "VENTRA_FL_ATHENA",
  tx_daily_actual: 95_000,
  tx_daily_target: 90_000,
  tx_daily_delta: 5_000,
  tx_source_system: "HHA_TX_MANUAL",
  fl_mtd_actual: 3_400_000,
  fl_mtd_target: 4_000_000,
  fl_mtd_pct: 85,
  ventra_fee_mtd: 170_000,
};
const BUCKETS = {
  bucket_0_30: 1_000_000,
  bucket_31_60: 500_000,
  bucket_61_90: 250_000,
  bucket_91_120: 150_000,
  bucket_over_120: 800_000,
};
const AR = {
  fl_total_usd: 2_700_000,
  fl_buckets: BUCKETS,
  fl_over_120_pct: 18.5,
  fl_source_system: "VENTRA_FL_ATHENA",
  tx_total_usd: 1_800_000,
  tx_buckets: BUCKETS,
  tx_over_120_pct: 12.0,
  tx_source_system: "HHA_TX_MANUAL",
};
const CLIN = {
  hp_24h_pct: 96.5,
  hp_24h_target: 95,
  dc_48h_pct: 88.0,
  dc_48h_target: 90,
  los_fl_days: 4.2,
  los_tx_days: 4.0,
  los_woodmont_watch_days: 5.8,
  los_woodmont_trend_days: 0.4,
  credentials_expiring_30d: 2,
  credentials_expiring_60d: 5,
  credentials_expiring_90d: 8,
};
const PEOPLE = {
  headcount_w2: 187,
  headcount_1099: 42,
  headcount_total: 229,
  open_positions_total: 14,
  turnover_90d_pct: 8.5,
  below_fmv_count: 3,
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
    contract_end: null,
    annual_subsidy_usd: 250_000,
    ...overrides,
  };
}

function defaultMocks() {
  operationsSummaryMock.mockResolvedValue(OPS);
  financeTodayMock.mockResolvedValue(FIN);
  arAgingMock.mockResolvedValue(AR);
  clinicalSummaryMock.mockResolvedValue(CLIN);
  peopleSummaryMock.mockResolvedValue(PEOPLE);
  alertsMock.mockResolvedValue([]);
  sitesTodayMock.mockResolvedValue([makeSite()]);
}

async function renderPage() {
  const tree = await OverviewPage();
  return render(tree);
}

describe("OverviewPage / dashboard root (server component)", () => {
  beforeEach(() => {
    operationsSummaryMock.mockReset();
    financeTodayMock.mockReset();
    arAgingMock.mockReset();
    clinicalSummaryMock.mockReset();
    peopleSummaryMock.mockReset();
    alertsMock.mockReset();
    sitesTodayMock.mockReset();
  });

  it("renders the header + API-live badge", async () => {
    defaultMocks();
    await renderPage();

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Overview");
    expect(screen.getByText(/all 4 boards at a glance/)).toBeInTheDocument();
    expect(screen.getByText(/API live/)).toBeInTheDocument();
  });

  it("renders the 4 headline metric cards", async () => {
    defaultMocks();
    await renderPage();

    // FL census 1234 + delta sub line
    expect(screen.getByText("1,234")).toBeInTheDocument();
    expect(screen.getByText(/-66 vs 3-mo avg/)).toBeInTheDocument();
    // FL MTD compact-usd
    expect(screen.getByText("$3.40M")).toBeInTheDocument();
    expect(screen.getByText(/85\.0% of \$4\.00M target/)).toBeInTheDocument();
    // Open positions appears in the metric card AND the People MiniStat.
    expect(screen.getAllByText("14").length).toBeGreaterThanOrEqual(2);
  });

  it("FL Census tone branches: 'bad' when variance < 0, 'good' when >= 0", async () => {
    operationsSummaryMock.mockResolvedValue({ ...OPS, census_variance_vs_avg: -10 });
    financeTodayMock.mockResolvedValue(FIN);
    arAgingMock.mockResolvedValue(AR);
    clinicalSummaryMock.mockResolvedValue(CLIN);
    peopleSummaryMock.mockResolvedValue(PEOPLE);
    alertsMock.mockResolvedValue([]);
    sitesTodayMock.mockResolvedValue([]);

    await renderPage();
    expect(screen.getByText("1,234").className).toContain("text-red-600");

    // Positive variance -> good tone
    operationsSummaryMock.mockResolvedValue({ ...OPS, census_variance_vs_avg: 5 });
    await renderPage();
    const cells = screen.getAllByText("1,234");
    expect(cells.some((c) => c.className.includes("text-emerald-600"))).toBe(true);
  });

  it("Active Alerts tone: 'bad' when any alert has severity='red', else 'warn'", async () => {
    operationsSummaryMock.mockResolvedValue(OPS);
    financeTodayMock.mockResolvedValue(FIN);
    arAgingMock.mockResolvedValue(AR);
    clinicalSummaryMock.mockResolvedValue(CLIN);
    peopleSummaryMock.mockResolvedValue(PEOPLE);
    sitesTodayMock.mockResolvedValue([]);

    // 'red' alert -> bad (red-600)
    alertsMock.mockResolvedValue([
      {
        id: "a1",
        severity: "red",
        category: "finance",
        owner: "Sandy",
        title: "x",
        detail: "y",
      },
    ]);
    await renderPage();
    expect(screen.getByText("1").className).toContain("text-red-600");
  });

  it("renders the AlertBanner with provided alerts", async () => {
    operationsSummaryMock.mockResolvedValue(OPS);
    financeTodayMock.mockResolvedValue(FIN);
    arAgingMock.mockResolvedValue(AR);
    clinicalSummaryMock.mockResolvedValue(CLIN);
    peopleSummaryMock.mockResolvedValue(PEOPLE);
    sitesTodayMock.mockResolvedValue([]);
    alertsMock.mockResolvedValue([
      {
        id: "a1",
        severity: "red",
        category: "finance",
        owner: "Sandy",
        title: "Collections dip",
        detail: "FL daily below target",
      },
    ]);

    await renderPage();
    expect(screen.getByText("Collections dip")).toBeInTheDocument();
  });

  it("renders the Operations FL census table with one row per FL site", async () => {
    defaultMocks();
    sitesTodayMock.mockResolvedValue([
      makeSite({ id: 1, name: "Westside Regional", state: "FL", variance_pct: -20 }),
      makeSite({ id: 2, name: "Woodmont", state: "FL", variance_pct: -8 }),
      makeSite({ id: 3, name: "Pearland", state: "TX" }), // filtered out (FL only)
    ]);

    await renderPage();

    expect(screen.getByText("Westside Regional")).toBeInTheDocument();
    expect(screen.getByText("Woodmont")).toBeInTheDocument();
    expect(screen.queryByText("Pearland")).toBeNull();
  });

  it("Operations FL census variance tone branches", async () => {
    defaultMocks();
    sitesTodayMock.mockResolvedValue([
      makeSite({ id: 1, name: "Red-Site", variance_pct: -20 }),
      makeSite({ id: 2, name: "Amber-Site", variance_pct: -8 }),
      makeSite({ id: 3, name: "Green-Site", variance_pct: 2 }),
      makeSite({ id: 4, name: "Null-Site", variance_pct: null, census_today: null }),
    ]);

    await renderPage();

    // -20% -> red; -8% -> amber; 2% -> emerald
    expect(screen.getByText("-20.0%").className).toContain("text-red-600");
    expect(screen.getByText("-8.0%").className).toContain("text-amber-600");
    expect(screen.getByText("2.0%").className).toContain("text-emerald-600");
  });

  it("renders ProgressRow ribbons for FL Daily / TX Daily / FL MTD", async () => {
    defaultMocks();
    await renderPage();

    expect(screen.getByText("FL Daily")).toBeInTheDocument();
    expect(screen.getByText("TX Daily")).toBeInTheDocument();
    expect(screen.getByText("FL MTD")).toBeInTheDocument();
  });

  it("ProgressRow tone: red when <90%, amber 90-99%, emerald >=100%", async () => {
    operationsSummaryMock.mockResolvedValue(OPS);
    arAgingMock.mockResolvedValue(AR);
    clinicalSummaryMock.mockResolvedValue(CLIN);
    peopleSummaryMock.mockResolvedValue(PEOPLE);
    alertsMock.mockResolvedValue([]);
    sitesTodayMock.mockResolvedValue([]);

    // FL Daily 156k / 200k = 78% -> red
    financeTodayMock.mockResolvedValue({
      ...FIN,
      fl_daily_actual: 156_000,
      fl_daily_target: 200_000,
      tx_daily_actual: 92_000,
      tx_daily_target: 100_000, // 92% -> amber
      fl_mtd_actual: 5_000_000,
      fl_mtd_target: 5_000_000, // 100% -> emerald
    });
    await renderPage();

    // Find the 3 ProgressRow value spans
    const flDailyValue = screen.getByText(/\$156,000 \/ \$200,000/);
    const txDailyValue = screen.getByText(/\$92,000 \/ \$100,000/);
    const flMtdValue = screen.getByText(/\$5\.00M \/ \$5\.00M/);

    expect(flDailyValue.className).toContain("text-red-700");
    expect(txDailyValue.className).toContain("text-amber-700");
    expect(flMtdValue.className).toContain("text-emerald-700");
  });

  it("renders AR aging top-band buckets with > 120d pct callouts for FL + TX", async () => {
    defaultMocks();
    await renderPage();

    expect(screen.getByText(/AR aging — FL top-band/)).toBeInTheDocument();
    // The 5 bucket labels render
    expect(screen.getByText("0-30")).toBeInTheDocument();
    expect(screen.getByText(">120")).toBeInTheDocument();
    // 18.5% and 12.0% callouts
    expect(screen.getByText("18.5%")).toBeInTheDocument();
    expect(screen.getByText("12.0%")).toBeInTheDocument();
  });

  it("Clinical Quality Row tone: hp_24h good (>= target), dc_48h warn (< target)", async () => {
    defaultMocks();
    await renderPage();

    // 96.5 >= 95 -> emerald
    expect(screen.getByText("96.5%").className).toContain("text-emerald-600");
    // 88.0 < 90 -> amber
    expect(screen.getByText("88.0%").className).toContain("text-amber-600");
  });

  it("Credentials expiring tone: red when > 0, emerald when 0", async () => {
    operationsSummaryMock.mockResolvedValue(OPS);
    financeTodayMock.mockResolvedValue(FIN);
    arAgingMock.mockResolvedValue(AR);
    peopleSummaryMock.mockResolvedValue(PEOPLE);
    alertsMock.mockResolvedValue([]);
    sitesTodayMock.mockResolvedValue([]);
    clinicalSummaryMock.mockResolvedValue({ ...CLIN, credentials_expiring_30d: 4 });

    await renderPage();
    expect(screen.getByText("4").className).toContain("text-red-600");
  });

  it("renders People MiniStats for W-2, 1099, Open Positions (warn), Turnover", async () => {
    defaultMocks();
    await renderPage();

    expect(screen.getByText("W-2")).toBeInTheDocument();
    expect(screen.getByText("1099")).toBeInTheDocument();
    // 'Open Positions' appears in both the headline metric AND the MiniStat
    expect(screen.getAllByText("Open Positions").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Turnover 90d")).toBeInTheDocument();
    // Turnover 8.5% rendered through pct()
    expect(screen.getByText("8.5%")).toBeInTheDocument();
  });

  it("renders the comp_viewer-gated 'Providers below FMV' row", async () => {
    defaultMocks();
    await renderPage();

    expect(screen.getByText("Providers below FMV")).toBeInTheDocument();
    expect(screen.getByText(/comp_viewer/)).toBeInTheDocument();
  });

  it("renders the footer with the documented '7 endpoints' provenance line", async () => {
    defaultMocks();
    await renderPage();

    expect(screen.getByText(/fetched 7 endpoints from FastAPI/)).toBeInTheDocument();
  });

  it("calls all 7 api endpoints exactly once each in parallel", async () => {
    defaultMocks();
    await renderPage();

    expect(operationsSummaryMock).toHaveBeenCalledTimes(1);
    expect(financeTodayMock).toHaveBeenCalledTimes(1);
    expect(arAgingMock).toHaveBeenCalledTimes(1);
    expect(clinicalSummaryMock).toHaveBeenCalledTimes(1);
    expect(peopleSummaryMock).toHaveBeenCalledTimes(1);
    expect(alertsMock).toHaveBeenCalledTimes(1);
    expect(sitesTodayMock).toHaveBeenCalledTimes(1);
  });

  it("filters sites table to FL only (TX sites dropped from this view)", async () => {
    defaultMocks();
    sitesTodayMock.mockResolvedValue([
      makeSite({ id: 1, name: "FL-A", state: "FL" }),
      makeSite({ id: 2, name: "FL-B", state: "FL" }),
      makeSite({ id: 3, name: "TX-X", state: "TX" }),
      makeSite({ id: 4, name: "TX-Y", state: "TX" }),
    ]);

    await renderPage();

    expect(screen.getByText("FL-A")).toBeInTheDocument();
    expect(screen.getByText("FL-B")).toBeInTheDocument();
    expect(screen.queryByText("TX-X")).toBeNull();
    expect(screen.queryByText("TX-Y")).toBeNull();
  });

  it("renders em-dash placeholders in census/variance cells when site fields are null", async () => {
    defaultMocks();
    sitesTodayMock.mockResolvedValue([
      makeSite({
        id: 1,
        name: "NullSite",
        state: "FL",
        census_today: null,
        census_3mo_avg: null,
        variance_pct: null,
      }),
    ]);

    await renderPage();

    const placeholders = screen.getAllByText("—");
    expect(placeholders.length).toBeGreaterThanOrEqual(3);
  });
});
