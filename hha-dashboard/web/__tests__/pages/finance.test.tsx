// @vitest-environment happy-dom
//
// FinancePage server-component tests. Pulls 4 different api endpoints
// (financeToday / arAging / financeKpis / monthlyTrend) in parallel
// and renders MetricCards + BucketChart + Row helpers + the Recharts
// MonthlyRevenueChart.
//
// Recharts needs a ResizeObserver stub; we also mock ResponsiveContainer
// to a fixed-size wrapper so the chart renders in happy-dom.

import { render, screen } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

beforeAll(() => {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  (globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver =
    ResizeObserverStub;
});

vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 800, height: 400 }}>{children}</div>
    ),
  };
});

const financeTodayMock = vi.fn();
const arAgingMock = vi.fn();
const financeKpisMock = vi.fn();
const monthlyTrendMock = vi.fn();

vi.mock("@/lib/api-client", () => ({
  api: {
    financeToday: () => financeTodayMock(),
    arAging: () => arAgingMock(),
    financeKpis: () => financeKpisMock(),
    monthlyTrend: () => monthlyTrendMock(),
  },
}));

import FinancePage from "@/app/finance/page";

const TODAY = {
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

const EMPTY_BUCKETS = {
  bucket_0_30: 1_000_000,
  bucket_31_60: 500_000,
  bucket_61_90: 250_000,
  bucket_91_120: 150_000,
  bucket_over_120: 800_000,
};

const AGING = {
  fl_total_usd: 2_700_000,
  fl_buckets: EMPTY_BUCKETS,
  fl_over_120_pct: 18.5,
  fl_source_system: "VENTRA_FL_ATHENA",
  tx_total_usd: 1_800_000,
  tx_buckets: EMPTY_BUCKETS,
  tx_over_120_pct: 12.0,
  tx_source_system: "HHA_TX_MANUAL",
};

const KPIS = {
  fl_days_in_ar: 38,
  tx_days_in_ar: 42,
  days_in_ar_target: 40,
  fl_ncr_pct: 91,
  tx_ncr_pct: 88,
  ncr_billed_at: "Billed at MGMA 50th percentile",
};

const TREND = [
  { month: "2026-04", revenue_usd: 4_800_000 },
  { month: "2026-05", revenue_usd: 5_200_000 },
];

function defaultMocks() {
  financeTodayMock.mockResolvedValue(TODAY);
  arAgingMock.mockResolvedValue(AGING);
  financeKpisMock.mockResolvedValue(KPIS);
  monthlyTrendMock.mockResolvedValue(TREND);
}

async function renderPage() {
  const tree = await FinancePage();
  return render(tree);
}

describe("FinancePage (server component)", () => {
  beforeEach(() => {
    financeTodayMock.mockReset();
    arAgingMock.mockReset();
    financeKpisMock.mockReset();
    monthlyTrendMock.mockReset();
  });

  it("renders the header + 'No denial analytics' subtitle", async () => {
    defaultMocks();
    await renderPage();

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/Finance/);
    expect(screen.getByText(/No denial analytics — Ventra/)).toBeInTheDocument();
  });

  it("renders the FL Daily Collections card with usd value and below-target sub", async () => {
    defaultMocks();
    await renderPage();

    expect(screen.getByText("$156,000")).toBeInTheDocument();
    // delta is shown via Math.abs + ▼ prefix
    expect(screen.getByText(/▼ \$44,000 below/)).toBeInTheDocument();
  });

  it("renders the TX Daily Collections card with usd value and above-target sub", async () => {
    defaultMocks();
    await renderPage();

    expect(screen.getByText("$95,000")).toBeInTheDocument();
    expect(screen.getByText(/▲ \$5,000 above/)).toBeInTheDocument();
  });

  it("renders the FL MTD card with compact-usd value and pct target", async () => {
    defaultMocks();
    await renderPage();

    // usd(3_400_000, true) -> "$3.40M"
    expect(screen.getByText("$3.40M")).toBeInTheDocument();
    // sub: "vs $4.00M target · 85.0%"
    expect(screen.getByText(/vs \$4\.00M target · 85\.0%/)).toBeInTheDocument();
  });

  it("renders the Ventra Fee card (5% of FL collections)", async () => {
    defaultMocks();
    await renderPage();

    expect(screen.getByText("Ventra Fee (5%)")).toBeInTheDocument();
    expect(screen.getByText("$170.0K")).toBeInTheDocument();
  });

  it("renders the AR aging buckets for both states", async () => {
    defaultMocks();
    await renderPage();

    expect(screen.getByText("FLORIDA")).toBeInTheDocument();
    expect(screen.getByText("TEXAS")).toBeInTheDocument();
    // Bucket labels rendered
    expect(screen.getAllByText("0-30").length).toBeGreaterThan(0);
    expect(screen.getAllByText(">120").length).toBeGreaterThan(0);
  });

  it("renders the >120d pct callout per state", async () => {
    defaultMocks();
    await renderPage();

    // FL over_120_pct = 18.5, TX = 12.0 — both rendered as pct()
    expect(screen.getByText("18.5%")).toBeInTheDocument();
    expect(screen.getByText("12.0%")).toBeInTheDocument();
  });

  it("renders the Days in A/R rows with target sub-line", async () => {
    defaultMocks();
    await renderPage();

    expect(screen.getByText("Days in A/R — Florida")).toBeInTheDocument();
    expect(screen.getByText("Days in A/R — Texas")).toBeInTheDocument();
    expect(screen.getByText("38")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    // 'Target <40' rendered twice (FL + TX rows)
    expect(screen.getAllByText("Target <40").length).toBe(2);
  });

  it("renders the Net Collection Rate rows with state-specific pct", async () => {
    defaultMocks();
    await renderPage();

    expect(screen.getByText("Net Collection Rate — FL")).toBeInTheDocument();
    expect(screen.getByText("Net Collection Rate — TX")).toBeInTheDocument();
    // pct(91, 0) -> "91%"
    expect(screen.getByText("91%")).toBeInTheDocument();
    expect(screen.getByText("88%")).toBeInTheDocument();
    expect(screen.getAllByText("Billed at MGMA 50th percentile").length).toBe(2);
  });

  it("renders the monthly revenue chart wrapper", async () => {
    defaultMocks();
    await renderPage();

    expect(screen.getByText(/Monthly revenue trend · 12 months/)).toBeInTheDocument();
  });

  it("renders the 'denial analytics out of scope' footer card", async () => {
    defaultMocks();
    await renderPage();

    expect(screen.getByText(/Denial analytics are out of scope/)).toBeInTheDocument();
    expect(screen.getByText(/HHA contracted the full RCM cycle to/)).toBeInTheDocument();
  });

  it("fetches all four api endpoints in parallel (each called once)", async () => {
    defaultMocks();
    await renderPage();

    expect(financeTodayMock).toHaveBeenCalledTimes(1);
    expect(arAgingMock).toHaveBeenCalledTimes(1);
    expect(financeKpisMock).toHaveBeenCalledTimes(1);
    expect(monthlyTrendMock).toHaveBeenCalledTimes(1);
  });
});
