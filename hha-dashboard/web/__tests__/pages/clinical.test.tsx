// @vitest-environment happy-dom
//
// ClinicalPage server-component tests.
//
// Strategy: mock @/lib/api-client to provide a stubbed `api` object, then
// invoke the page function directly (it's an async function that returns
// JSX) and render the awaited result via RTL.

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const clinicalSummaryMock = vi.fn();
const credentialsExpiringMock = vi.fn();

vi.mock("@/lib/api-client", () => ({
  api: {
    clinicalSummary: () => clinicalSummaryMock(),
    credentialsExpiring: () => credentialsExpiringMock(),
  },
}));

import ClinicalPage from "@/app/clinical/page";

const SUMMARY_OK = {
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

const EXPIRING_FIXTURE = [
  {
    physician: "Dr. Franklyn",
    type: "DEA",
    expires_in_days: 12,
    expires_on: "2026-05-26T00:00:00Z",
    tier: "urgent" as const,
  },
  {
    physician: "Dr. Patel",
    type: "License",
    expires_in_days: 22,
    expires_on: "2026-06-05T00:00:00Z",
    tier: "urgent" as const,
  },
  {
    physician: "Dr. Reddy",
    type: "BCLS",
    expires_in_days: 45,
    expires_on: "2026-06-28T00:00:00Z",
    tier: "warning" as const,
  },
];

async function renderPage() {
  // Server components return JSX after awaiting; treat the function as a
  // plain async fn and render the resolved output.
  const tree = await ClinicalPage();
  return render(tree);
}

describe("ClinicalPage (server component)", () => {
  beforeEach(() => {
    clinicalSummaryMock.mockReset();
    credentialsExpiringMock.mockReset();
  });

  it("renders the page header + subtitle", async () => {
    clinicalSummaryMock.mockResolvedValue(SUMMARY_OK);
    credentialsExpiringMock.mockResolvedValue([]);

    await renderPage();

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Clinical Quality");
    expect(screen.getByText(/Documentation timeliness/)).toBeInTheDocument();
  });

  it("renders the four documentation/LOS metric cards with formatted values", async () => {
    clinicalSummaryMock.mockResolvedValue(SUMMARY_OK);
    credentialsExpiringMock.mockResolvedValue([]);

    await renderPage();

    // pct(96.5) -> "96.5%"
    expect(screen.getByText("96.5%")).toBeInTheDocument();
    // pct(88.0) -> "88.0%"
    expect(screen.getByText("88.0%")).toBeInTheDocument();
    // LOS uses ${value}d
    expect(screen.getByText("4.2d")).toBeInTheDocument();
    expect(screen.getByText("4d")).toBeInTheDocument();
  });

  it("colors hp_24h as 'good' when at or above target", async () => {
    clinicalSummaryMock.mockResolvedValue({ ...SUMMARY_OK, hp_24h_pct: 95, hp_24h_target: 95 });
    credentialsExpiringMock.mockResolvedValue([]);

    await renderPage();

    const hp = screen.getByText("95.0%");
    expect(hp.className).toContain("text-emerald-600");
  });

  it("colors hp_24h as 'warn' when below target", async () => {
    clinicalSummaryMock.mockResolvedValue({ ...SUMMARY_OK, hp_24h_pct: 92, hp_24h_target: 95 });
    credentialsExpiringMock.mockResolvedValue([]);

    await renderPage();

    const hp = screen.getByText("92.0%");
    expect(hp.className).toContain("text-amber-600");
  });

  it("colors dc_48h as 'warn' when below target", async () => {
    clinicalSummaryMock.mockResolvedValue({ ...SUMMARY_OK, dc_48h_pct: 80, dc_48h_target: 90 });
    credentialsExpiringMock.mockResolvedValue([]);

    await renderPage();

    const dc = screen.getByText("80.0%");
    expect(dc.className).toContain("text-amber-600");
  });

  it("renders the urgent credentials list with name + type + days remaining", async () => {
    clinicalSummaryMock.mockResolvedValue(SUMMARY_OK);
    credentialsExpiringMock.mockResolvedValue(EXPIRING_FIXTURE);

    await renderPage();

    // urgent block lists Dr. Franklyn + Dr. Patel (2 urgents in the fixture)
    expect(screen.getByText("Dr. Franklyn")).toBeInTheDocument();
    expect(screen.getByText(/DEA/)).toBeInTheDocument();
    expect(screen.getByText("12 days")).toBeInTheDocument();
    expect(screen.getByText("Dr. Patel")).toBeInTheDocument();
    expect(screen.getByText("22 days")).toBeInTheDocument();
  });

  it("renders the warning credentials list (30-60d band)", async () => {
    clinicalSummaryMock.mockResolvedValue(SUMMARY_OK);
    credentialsExpiringMock.mockResolvedValue(EXPIRING_FIXTURE);

    await renderPage();

    expect(screen.getByText("Dr. Reddy")).toBeInTheDocument();
  });

  it("renders the expiring counts from the summary in the 30/60/90 bands", async () => {
    clinicalSummaryMock.mockResolvedValue({
      ...SUMMARY_OK,
      credentials_expiring_30d: 3,
      credentials_expiring_60d: 7,
      credentials_expiring_90d: 11,
    });
    credentialsExpiringMock.mockResolvedValue([]);

    await renderPage();

    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("11")).toBeInTheDocument();
  });

  it("renders the Woodmont LOS watch card with values + owner", async () => {
    clinicalSummaryMock.mockResolvedValue({
      ...SUMMARY_OK,
      los_woodmont_watch_days: 6.3,
      los_woodmont_trend_days: 0.5,
    });
    credentialsExpiringMock.mockResolvedValue([]);

    await renderPage();

    expect(screen.getByText("Woodmont LOS Watch")).toBeInTheDocument();
    expect(screen.getAllByText("6.3d").length).toBeGreaterThan(0);
    // ▲ + value
    expect(screen.getByText(/▲ \+0.5d/)).toBeInTheDocument();
    expect(screen.getByText(/Dr. Aneja · PIP weekly review/)).toBeInTheDocument();
  });

  it("calls api.clinicalSummary and api.credentialsExpiring exactly once each on render", async () => {
    clinicalSummaryMock.mockResolvedValue(SUMMARY_OK);
    credentialsExpiringMock.mockResolvedValue([]);

    await renderPage();

    expect(clinicalSummaryMock).toHaveBeenCalledTimes(1);
    expect(credentialsExpiringMock).toHaveBeenCalledTimes(1);
  });

  it("renders cleanly when no credentials are expiring (empty list -> empty bullet section)", async () => {
    clinicalSummaryMock.mockResolvedValue(SUMMARY_OK);
    credentialsExpiringMock.mockResolvedValue([]);

    const { container } = await renderPage();

    // The urgent + warning cards still render (the counts come from summary),
    // just with empty <ul>s — verify no crash + no name leaks from fixtures
    expect(container.firstChild).not.toBeNull();
    expect(screen.queryByText("Dr. Franklyn")).toBeNull();
  });
});
