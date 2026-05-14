// @vitest-environment happy-dom
//
// Leaf component tests — pure presentational pieces with no data fetching
// and no React Query / MSW interaction. RTL + jest-dom assertions.
//
// Each component verifies:
//   1. Renders the props it receives.
//   2. Default/variant branches render with the expected class names
//      (a Tailwind class regression is a UI bug that ships silently).
//   3. Conditional slots (subtitle, owner, right, source) appear when
//      provided and are skipped when absent.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AlertBanner } from "@/components/AlertBanner";
import { Badge, SourceTag } from "@/components/Badge";
import { Card, CardHeader } from "@/components/Card";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";

describe("Badge", () => {
  it("renders children inside an inline span", () => {
    render(<Badge>Hello</Badge>);
    const el = screen.getByText("Hello");
    expect(el).toBeInTheDocument();
    expect(el.tagName).toBe("SPAN");
  });

  it("applies the gray default variant class when variant is omitted", () => {
    render(<Badge>Default</Badge>);
    const el = screen.getByText("Default");
    expect(el.className).toContain("bg-slate-100");
    expect(el.className).toContain("text-slate-700");
  });

  it.each([
    ["good", "bg-emerald-50", "bg-emerald-500"],
    ["warn", "bg-amber-50", "bg-amber-500"],
    ["bad", "bg-red-50", "bg-red-500"],
    ["blue", "bg-blue-50", "bg-blue-500"],
    ["gray", "bg-slate-100", "bg-slate-400"],
  ] as const)("applies %s variant class to badge and dot", (variant, bgClass, dotClass) => {
    render(
      <Badge variant={variant} dot>
        {variant}
      </Badge>,
    );
    const badge = screen.getByText(variant);
    expect(badge.className).toContain(bgClass);
    // The dot is rendered as a sibling span inside the badge — find it via
    // the badge's first child element.
    const dot = badge.querySelector("span[aria-hidden]");
    expect(dot).toBeInTheDocument();
    expect(dot?.className).toContain(dotClass);
  });

  it("omits the dot span when the dot prop is falsy", () => {
    render(<Badge>NoDot</Badge>);
    const badge = screen.getByText("NoDot");
    expect(badge.querySelector("span[aria-hidden]")).toBeNull();
  });
});

describe("SourceTag", () => {
  it("renders the FL · Ventra auto label with good (green) variant", () => {
    render(<SourceTag source="VENTRA_FL_ATHENA" />);
    const el = screen.getByText("FL · Ventra ✓ auto");
    expect(el).toBeInTheDocument();
    expect(el.className).toContain("bg-emerald-50");
  });

  it("renders the FL · Ventra (manual) label with warn (amber) variant", () => {
    render(<SourceTag source="VENTRA_FL_FALLBACK" />);
    const el = screen.getByText("FL · Ventra (manual)");
    expect(el.className).toContain("bg-amber-50");
  });

  it("renders the TX · manual label with gray variant", () => {
    render(<SourceTag source="HHA_TX_MANUAL" />);
    const el = screen.getByText("TX · manual");
    expect(el.className).toContain("bg-slate-100");
  });

  it("falls through to the raw source string + gray variant for unknown values", () => {
    render(<SourceTag source="UNKNOWN_VENDOR_X" />);
    const el = screen.getByText("UNKNOWN_VENDOR_X");
    expect(el.className).toContain("bg-slate-100");
  });
});

describe("Card", () => {
  it("renders children", () => {
    render(<Card>Inside</Card>);
    expect(screen.getByText("Inside")).toBeInTheDocument();
  });

  it("applies base card styling regardless of interactive flag", () => {
    const { container } = render(<Card>x</Card>);
    const div = container.firstChild as HTMLElement;
    expect(div.className).toContain("rounded-xl");
    expect(div.className).toContain("border-slate-200");
    expect(div.className).toContain("bg-white");
    // Without interactive, the hover-translate class must NOT be present
    expect(div.className).not.toContain("hover:-translate-y-0.5");
  });

  it("adds hover translate + shadow when interactive=true", () => {
    const { container } = render(<Card interactive>x</Card>);
    const div = container.firstChild as HTMLElement;
    expect(div.className).toContain("hover:-translate-y-0.5");
    expect(div.className).toContain("hover:shadow-md");
  });

  it("merges a caller-provided className with the base classes", () => {
    const { container } = render(<Card className="bg-blue-100">x</Card>);
    const div = container.firstChild as HTMLElement;
    expect(div.className).toContain("rounded-xl");
    expect(div.className).toContain("bg-blue-100");
  });
});

describe("CardHeader", () => {
  it("renders title only when owner + right are omitted", () => {
    render(<CardHeader title="Revenue" />);
    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Revenue");
  });

  it("renders the owner sub-line when provided", () => {
    render(<CardHeader title="Revenue" owner="Sandy Collins" />);
    expect(screen.getByText("Sandy Collins")).toBeInTheDocument();
  });

  it("renders a right slot when provided", () => {
    render(<CardHeader title="Revenue" right={<button type="button">Edit</button>} />);
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });
});

describe("MetricCard", () => {
  it("renders label + value + sub", () => {
    render(<MetricCard label="MRR" value="$5.2M" sub="vs last month" />);
    expect(screen.getByText("MRR")).toBeInTheDocument();
    expect(screen.getByText("$5.2M")).toBeInTheDocument();
    expect(screen.getByText("vs last month")).toBeInTheDocument();
  });

  it.each([
    ["neutral", "text-slate-900"],
    ["good", "text-emerald-600"],
    ["warn", "text-amber-600"],
    ["bad", "text-red-600"],
  ] as const)("applies %s tone class to the value cell", (tone, expectedClass) => {
    render(<MetricCard label="L" value="42" tone={tone} />);
    const value = screen.getByText("42");
    expect(value.className).toContain(expectedClass);
  });

  it("uses neutral tone class when tone prop is omitted", () => {
    render(<MetricCard label="L" value="42" />);
    expect(screen.getByText("42").className).toContain("text-slate-900");
  });

  it("applies accent border + bg when accent=true", () => {
    const { container } = render(<MetricCard label="L" value="42" accent />);
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.className).toContain("border-indigo-200");
    expect(wrapper.className).toContain("bg-indigo-50");
  });

  it("renders default (non-accent) border + bg when accent prop is absent", () => {
    const { container } = render(<MetricCard label="L" value="42" />);
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.className).toContain("border-slate-200");
    expect(wrapper.className).toContain("bg-white");
  });

  it("renders the source slot inline next to the label when provided", () => {
    render(<MetricCard label="L" value="42" source={<span>FL · Ventra ✓</span>} />);
    expect(screen.getByText("FL · Ventra ✓")).toBeInTheDocument();
  });

  it("omits the sub line when sub prop is absent", () => {
    const { container } = render(<MetricCard label="L" value="42" />);
    // sub renders inside `mt-1 text-xs text-slate-500` — no element with that
    // text class structure should exist
    const subEls = container.querySelectorAll(".text-slate-500");
    // Only the label cell carries text-slate-500 (with uppercase) — sub
    // would add another with mt-1.text-xs
    const hasSubLine = Array.from(subEls).some(
      (e) => e.className.includes("text-xs") && !e.className.includes("uppercase"),
    );
    expect(hasSubLine).toBe(false);
  });
});

describe("AlertBanner", () => {
  it("renders nothing when alerts is empty", () => {
    const { container } = render(<AlertBanner alerts={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders one card per alert", () => {
    const alerts = [
      {
        id: "a1",
        severity: "red" as const,
        category: "finance" as const,
        owner: "Sandy",
        title: "Collections below target",
        detail: "Shortfall $44k/day",
      },
      {
        id: "a2",
        severity: "yellow" as const,
        category: "operations" as const,
        owner: "Crystal",
        title: "Census drift",
        detail: "Westside −12",
      },
    ];
    render(<AlertBanner alerts={alerts} />);
    expect(screen.getByText("Collections below target")).toBeInTheDocument();
    expect(screen.getByText("Census drift")).toBeInTheDocument();
    expect(screen.getByText("Shortfall $44k/day")).toBeInTheDocument();
    // Owner + category header rendered as a single line
    expect(screen.getByText(/finance · Sandy/i)).toBeInTheDocument();
  });

  it.each([
    ["red", "border-red-200"],
    ["yellow", "border-amber-200"],
    ["blue", "border-blue-200"],
  ] as const)("applies %s severity border color to the alert card", (severity, expectedClass) => {
    const alerts = [
      {
        id: `a-${severity}`,
        severity,
        category: "finance" as const,
        owner: "y",
        title: "t",
        detail: "d",
      },
    ];
    const { container } = render(<AlertBanner alerts={alerts} />);
    const card = container.querySelector(`div.${expectedClass.split(" ")[0]}`);
    expect(card).toBeInTheDocument();
  });
});

describe("PageHeader", () => {
  it("renders title in an h1", () => {
    render(<PageHeader title="Operations" />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Operations");
  });

  it("renders subtitle when provided", () => {
    render(<PageHeader title="Ops" subtitle="Daily census + alerts" />);
    expect(screen.getByText("Daily census + alerts")).toBeInTheDocument();
  });

  it("renders the today-label by default", () => {
    render(<PageHeader title="Ops" />);
    expect(screen.getByText("As of")).toBeInTheDocument();
    // The actual date label varies by day — assert the year is in the rendered text
    const yearString = String(new Date().getFullYear());
    expect(screen.getByText(new RegExp(yearString))).toBeInTheDocument();
  });

  it("omits the today-label when hideDate=true", () => {
    render(<PageHeader title="Ops" hideDate />);
    expect(screen.queryByText("As of")).toBeNull();
  });

  it("renders right slot when provided", () => {
    render(<PageHeader title="Ops" right={<button type="button">Refresh</button>} />);
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
  });
});
