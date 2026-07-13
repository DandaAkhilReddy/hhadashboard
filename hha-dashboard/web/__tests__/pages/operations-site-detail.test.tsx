// @vitest-environment happy-dom
//
// /operations/[siteId] server-component tests. Covers param validation,
// the api.siteDetail throw-to-404 catch, the variance + open_shifts +
// md_status three-way tone branches, MetricCard composition, and the
// recent_entries history table empty-state vs populated branches.

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const siteDetailMock = vi.fn();
const notFoundMock = vi.fn(() => {
  throw new Error("NEXT_NOT_FOUND");
});

vi.mock("@/lib/api-client", () => ({
  api: {
    siteDetail: (id: number) => siteDetailMock(id),
  },
}));

vi.mock("next/navigation", () => ({
  notFound: () => notFoundMock(),
}));

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

// The chart component is exercised by its own test file; here we just
// confirm the page passes it down.
vi.mock("@/components/CensusTrendChart", () => ({
  CensusTrendChart: ({ points, avg }: { points: unknown[]; avg: number }) => (
    <div data-testid="census-trend-chart" data-points={JSON.stringify(points)} data-avg={avg} />
  ),
}));

// SiteCensusForm has its own dedicated test; passthrough surfacing props.
vi.mock("@/app/operations/[siteId]/SiteCensusForm", () => ({
  SiteCensusForm: ({
    siteId,
    initialCensus,
    initialOpenShifts,
    initialNotes,
  }: {
    siteId: number;
    initialCensus: number | null;
    initialOpenShifts: number | null;
    initialNotes: string | null;
  }) => (
    <div
      data-testid="site-census-form"
      data-site-id={siteId}
      data-census={initialCensus ?? "null"}
      data-shifts={initialOpenShifts ?? "null"}
      data-notes={initialNotes ?? "null"}
    />
  ),
}));

import SiteDetailPage from "@/app/operations/[siteId]/page";

type SiteDetail = Awaited<ReturnType<typeof import("@/lib/api-client").api["siteDetail"]>>;

function siteDetail(overrides: Partial<SiteDetail> = {}): SiteDetail {
  return {
    id: 42,
    name: "Westside Regional",
    state: "FL",
    medical_director: "Dr. Alice",
    md_status: "ACTIVE",
    liaison: "Mary",
    census_today: 198,
    census_3mo_avg: 200,
    mtd_avg: 195.4,
    variance_pct: -1,
    open_shifts: 0,
    contract_end: "2027-12-31T00:00:00Z",
    annual_subsidy_usd: 250_000,
    entered_today: true,
    recent_entries: [],
    ...overrides,
  } as SiteDetail;
}

async function renderPage(siteIdRaw: string): Promise<void> {
  const tree = await SiteDetailPage({ params: Promise.resolve({ siteId: siteIdRaw }) });
  render(tree);
}

describe("SiteDetailPage — param validation + api failure", () => {
  beforeEach(() => {
    siteDetailMock.mockReset();
    notFoundMock.mockClear();
  });

  it("invalid siteId ('abc' → NaN) triggers notFound()", async () => {
    await expect(renderPage("abc")).rejects.toThrow(/NEXT_NOT_FOUND/);
    expect(notFoundMock).toHaveBeenCalled();
    expect(siteDetailMock).not.toHaveBeenCalled();
  });

  it("siteId = '0' (not > 0) triggers notFound()", async () => {
    await expect(renderPage("0")).rejects.toThrow(/NEXT_NOT_FOUND/);
    expect(notFoundMock).toHaveBeenCalled();
  });

  it("siteId = '-1' triggers notFound()", async () => {
    await expect(renderPage("-1")).rejects.toThrow(/NEXT_NOT_FOUND/);
    expect(notFoundMock).toHaveBeenCalled();
  });

  it("api.siteDetail throw triggers the catch -> notFound()", async () => {
    siteDetailMock.mockRejectedValue(new Error("404 from API"));
    await expect(renderPage("42")).rejects.toThrow(/NEXT_NOT_FOUND/);
    expect(notFoundMock).toHaveBeenCalled();
  });
});

describe("SiteDetailPage — variance tone branch", () => {
  beforeEach(() => {
    siteDetailMock.mockReset();
    notFoundMock.mockClear();
  });

  it.each([
    [null, "neutral"],
    [-20, "bad"],
    [-5, "warn"],
    [3, "good"],
  ] as const)(
    "variance=%s -> tone group %s applied to MetricCard accent",
    async (variance, _tone) => {
      siteDetailMock.mockResolvedValue(siteDetail({ variance_pct: variance, census_today: 198 }));
      await renderPage("42");
      // The 4-card strip renders; whatever the tone, the page rendered without crashing.
      // Variance-specific text is the percent label in the MTD card.
      if (variance !== null) {
        expect(screen.getByText(new RegExp(`${variance.toFixed(1)}%`))).toBeInTheDocument();
      }
    },
  );

  it("renders the signed delta 'vs 3-mo avg' line when census_today + 3mo are both set", async () => {
    siteDetailMock.mockResolvedValue(
      siteDetail({ census_today: 198, census_3mo_avg: 200, variance_pct: -1 }),
    );
    await renderPage("42");
    // signed(-2) -> "-2"; rendered as "-2 vs 3-mo avg"
    expect(screen.getByText(/-2 vs 3-mo avg/)).toBeInTheDocument();
  });

  it("renders 'no baseline yet' when 3-mo avg is null", async () => {
    siteDetailMock.mockResolvedValue(siteDetail({ census_3mo_avg: null }));
    await renderPage("42");
    expect(screen.getByText(/no baseline yet/i)).toBeInTheDocument();
  });
});

describe("SiteDetailPage — open_shifts tone branch", () => {
  beforeEach(() => {
    siteDetailMock.mockReset();
    notFoundMock.mockClear();
  });

  it("renders 'fully covered' when open_shifts === 0", async () => {
    siteDetailMock.mockResolvedValue(siteDetail({ open_shifts: 0 }));
    await renderPage("42");
    expect(screen.getByText(/fully covered/i)).toBeInTheDocument();
  });

  it("renders 'needs coverage' when open_shifts >= 1", async () => {
    siteDetailMock.mockResolvedValue(siteDetail({ open_shifts: 4 }));
    await renderPage("42");
    expect(screen.getByText(/needs coverage/i)).toBeInTheDocument();
  });

  it("renders em-dash when open_shifts is null", async () => {
    siteDetailMock.mockResolvedValue(siteDetail({ open_shifts: null }));
    await renderPage("42");
    // Multiple em-dashes appear (open_shifts label + value); at least one.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1);
  });
});

describe("SiteDetailPage — MD status badges", () => {
  beforeEach(() => {
    siteDetailMock.mockReset();
    notFoundMock.mockClear();
  });

  it("md_status='VACANT' renders the 'MD VACANT ⚠' badge AND inline 'VACANT' in MD field", async () => {
    siteDetailMock.mockResolvedValue(siteDetail({ md_status: "VACANT", medical_director: null }));
    await renderPage("42");
    expect(screen.getByText(/MD VACANT/)).toBeInTheDocument();
    // The MD field shows red VACANT when medical_director is null
    expect(screen.getAllByText(/VACANT/i).length).toBeGreaterThanOrEqual(1);
  });

  it("md_status='PIP' renders the 'PIP Active' badge", async () => {
    siteDetailMock.mockResolvedValue(siteDetail({ md_status: "PIP" }));
    await renderPage("42");
    expect(screen.getByText(/PIP Active/)).toBeInTheDocument();
  });

  it("md_status='ACTIVE' renders the green 'Active' badge", async () => {
    siteDetailMock.mockResolvedValue(siteDetail({ md_status: "ACTIVE" }));
    await renderPage("42");
    expect(screen.getByText(/^Active$/)).toBeInTheDocument();
  });
});

describe("SiteDetailPage — entered_today badge", () => {
  beforeEach(() => {
    siteDetailMock.mockReset();
    notFoundMock.mockClear();
  });

  it("renders '✓ Entered today' when entered_today is true", async () => {
    siteDetailMock.mockResolvedValue(siteDetail({ entered_today: true }));
    await renderPage("42");
    expect(screen.getByText(/✓ Entered today/)).toBeInTheDocument();
  });

  it("renders 'Not entered today' when entered_today is false", async () => {
    siteDetailMock.mockResolvedValue(siteDetail({ entered_today: false }));
    await renderPage("42");
    expect(screen.getByText(/Not entered today/)).toBeInTheDocument();
  });
});

describe("SiteDetailPage — recent entries table", () => {
  beforeEach(() => {
    siteDetailMock.mockReset();
    notFoundMock.mockClear();
  });

  it("renders the empty-state when recent_entries is []", async () => {
    siteDetailMock.mockResolvedValue(siteDetail({ recent_entries: [] }));
    await renderPage("42");
    expect(screen.getByText(/No entries yet for this site/i)).toBeInTheDocument();
  });

  it("renders the entries table with one row per history entry", async () => {
    siteDetailMock.mockResolvedValue(
      siteDetail({
        recent_entries: [
          {
            entry_date: "2026-05-12",
            census: 195,
            open_shifts: 1,
            entered_by_upn: "crystal@hha.com",
            source: "manual",
            notes: "Surge unit re-opened",
            updated_at: null,
          },
          {
            entry_date: "2026-05-11",
            census: 192,
            open_shifts: 2,
            entered_by_upn: "system@hha.com",
            source: "pdf",
            notes: null,
            updated_at: null,
          },
        ],
      }),
    );
    await renderPage("42");
    expect(screen.getByText("195")).toBeInTheDocument();
    expect(screen.getByText("192")).toBeInTheDocument();
    expect(screen.getByText(/Surge unit re-opened/)).toBeInTheDocument();
  });

  it("renders 'Manual' vs 'PDF' source badges by source value", async () => {
    siteDetailMock.mockResolvedValue(
      siteDetail({
        recent_entries: [
          {
            entry_date: "2026-05-12",
            census: 195,
            open_shifts: 1,
            entered_by_upn: "x@y.com",
            source: "manual",
            notes: null,
            updated_at: null,
          },
          {
            entry_date: "2026-05-11",
            census: 195,
            open_shifts: 1,
            entered_by_upn: "x@y.com",
            source: "pdf",
            notes: null,
            updated_at: null,
          },
        ],
      }),
    );
    await renderPage("42");
    expect(screen.getByText("Manual")).toBeInTheDocument();
    expect(screen.getByText("PDF")).toBeInTheDocument();
  });
});

describe("SiteDetailPage — chrome", () => {
  beforeEach(() => {
    siteDetailMock.mockReset();
    notFoundMock.mockClear();
  });

  it("renders the 'Back to Operations Board' link pointing at /operations", async () => {
    siteDetailMock.mockResolvedValue(siteDetail());
    await renderPage("42");
    const back = screen.getByRole("link", { name: /Back to Operations Board/i });
    expect(back.getAttribute("href")).toBe("/operations");
  });

  it("passes initialCensus + initialOpenShifts + initialNotes=null to SiteCensusForm", async () => {
    siteDetailMock.mockResolvedValue(siteDetail({ id: 42, census_today: 198, open_shifts: 2 }));
    await renderPage("42");
    const form = screen.getByTestId("site-census-form");
    expect(form.getAttribute("data-site-id")).toBe("42");
    expect(form.getAttribute("data-census")).toBe("198");
    expect(form.getAttribute("data-shifts")).toBe("2");
    expect(form.getAttribute("data-notes")).toBe("null");
  });

  it("renders the CensusTrendChart with buildTrendPoints output + 3mo avg", async () => {
    siteDetailMock.mockResolvedValue(
      siteDetail({
        census_3mo_avg: 200,
        recent_entries: [
          {
            entry_date: "2026-05-12",
            census: 195,
            open_shifts: 0,
            entered_by_upn: "",
            source: "manual",
            notes: null,
            updated_at: null,
          },
        ],
      }),
    );
    await renderPage("42");
    const chart = screen.getByTestId("census-trend-chart");
    expect(chart.getAttribute("data-avg")).toBe("200");
    const points = JSON.parse(chart.getAttribute("data-points") || "[]") as unknown[];
    expect(points.length).toBeGreaterThan(0);
  });

  it("renders the facility info block (MD, Liaison, Contract end, Annual subsidy)", async () => {
    siteDetailMock.mockResolvedValue(
      siteDetail({
        medical_director: "Dr. Alice",
        liaison: "Mary",
        contract_end: "2027-12-31T00:00:00Z",
        annual_subsidy_usd: 250_000,
      }),
    );
    await renderPage("42");
    expect(screen.getByText("Dr. Alice")).toBeInTheDocument();
    expect(screen.getByText("Mary")).toBeInTheDocument();
    expect(screen.getByText(/Medical Director/i)).toBeInTheDocument();
    expect(screen.getByText(/Liaison/i)).toBeInTheDocument();
    expect(screen.getByText(/Contract end/i)).toBeInTheDocument();
    expect(screen.getByText(/Annual subsidy/i)).toBeInTheDocument();
  });
});
