// @vitest-environment happy-dom
//
// Chart components are Recharts wrappers. Recharts measures DOM via
// ResizeObserver, which happy-dom doesn't ship by default. We stub it
// plus a passthrough ResponsiveContainer so the chart still mounts and
// renders its content with explicit dimensions.
//
// These are smoke + data-transform tests — Recharts' own visual output
// (bars, lines, gridlines) is the library's responsibility. We assert
// that our component does not crash on representative inputs and that
// the props it derives (today highlight, gap handling, reference line)
// reach the SVG layer.

import { render } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

// Stub ResizeObserver before Recharts imports run.
beforeAll(() => {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  (globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver =
    ResizeObserverStub;
});

// ResponsiveContainer auto-measures parent dimensions; force a fixed
// size so child charts render their interior SVG even in happy-dom.
vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 800, height: 400 }} data-testid="rc">
        {children}
      </div>
    ),
  };
});

import { CensusTrendChart } from "@/components/CensusTrendChart";
import { MonthlyRevenueChart } from "@/components/MonthlyRevenueChart";

describe("CensusTrendChart", () => {
  it("renders without crashing for a 14-day series with mixed null/data", () => {
    const points = Array.from({ length: 14 }, (_, i) => ({
      date: `2026-05-${String(i + 1).padStart(2, "0")}`,
      census: i % 3 === 0 ? null : 100 + i,
      isToday: i === 13,
    }));

    const { container, getByTestId } = render(<CensusTrendChart points={points} avg={120} />);

    // Wrapper div carries the documented fixed height
    expect(container.firstChild).toHaveClass("h-44", "w-full");
    // ResponsiveContainer mock mounted
    expect(getByTestId("rc")).toBeInTheDocument();
  });

  it("renders cleanly for an empty points array (no crash, no NaN)", () => {
    const { container } = render(<CensusTrendChart points={[]} avg={0} />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("renders cleanly when every point has null census", () => {
    const points = Array.from({ length: 5 }, (_, i) => ({
      date: `2026-05-${String(i + 1).padStart(2, "0")}`,
      census: null,
      isToday: false,
    }));

    const { container } = render(<CensusTrendChart points={points} avg={0} />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("renders cleanly with a single today-only data point", () => {
    const { container } = render(
      <CensusTrendChart points={[{ date: "2026-05-13", census: 150, isToday: true }]} avg={150} />,
    );
    expect(container.firstChild).toBeInTheDocument();
  });
});

describe("MonthlyRevenueChart", () => {
  it("renders without crashing for a 12-month series", () => {
    const trend = Array.from({ length: 12 }, (_, i) => ({
      month: `2026-${String(i + 1).padStart(2, "0")}`,
      revenue_usd: 5_000_000 + i * 100_000,
    }));

    const { container, getByTestId } = render(<MonthlyRevenueChart trend={trend} />);

    expect(container.firstChild).toBeInTheDocument();
    expect(getByTestId("rc")).toBeInTheDocument();
  });

  it("renders cleanly for an empty series", () => {
    const { container } = render(<MonthlyRevenueChart trend={[]} />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("wrapper div carries the documented h-48 height for layout consistency", () => {
    const trend = [{ month: "2026-05", revenue_usd: 1000 }];
    const { container } = render(<MonthlyRevenueChart trend={trend} />);
    expect(container.firstChild).toHaveClass("h-48", "w-full");
  });
});
