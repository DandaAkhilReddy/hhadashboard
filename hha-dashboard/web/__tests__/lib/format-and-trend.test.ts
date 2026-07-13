// Node-environment unit tests for pure utility modules.
// No DOM needed — keeping environment: 'node' default keeps these fast.

import { describe, expect, it } from "vitest";

import { cn, dateFull, dateShort, num, pct, signed, usd } from "@/lib/format";
import { type DayPoint, buildTrendPoints } from "@/lib/trend-points";

// ----- usd() -----

describe("usd()", () => {
  it("formats with thousands separators when compact=false (default)", () => {
    expect(usd(0)).toBe("$0");
    expect(usd(1234)).toBe("$1,234");
    expect(usd(1_234_567)).toBe("$1,234,567");
  });

  it("formats millions as $X.XXM when compact=true", () => {
    expect(usd(1_000_000, true)).toBe("$1.00M");
    expect(usd(5_432_100, true)).toBe("$5.43M");
  });

  it("formats thousands as $X.XK when compact=true and < 1M", () => {
    expect(usd(1000, true)).toBe("$1.0K");
    expect(usd(44_700, true)).toBe("$44.7K");
  });

  it("falls through to full thousands separator when compact value < 1K", () => {
    expect(usd(500, true)).toBe("$500");
    expect(usd(999, true)).toBe("$999");
  });

  it("handles negatives via Math.abs in compact mode", () => {
    expect(usd(-2_500_000, true)).toBe("$-2.50M");
    expect(usd(-50_000, true)).toBe("$-50.0K");
  });
});

// ----- pct() -----

describe("pct()", () => {
  it("defaults to 1 decimal place", () => {
    expect(pct(45.678)).toBe("45.7%");
  });

  it("honors a caller-specified digits count", () => {
    expect(pct(45.678, 0)).toBe("46%");
    expect(pct(45.678, 3)).toBe("45.678%");
  });

  it("handles zero and negatives", () => {
    expect(pct(0)).toBe("0.0%");
    expect(pct(-5.5)).toBe("-5.5%");
  });
});

// ----- num() -----

describe("num()", () => {
  it("inserts en-US thousands separators", () => {
    expect(num(0)).toBe("0");
    expect(num(1234)).toBe("1,234");
    expect(num(1_234_567)).toBe("1,234,567");
  });

  it("handles negatives", () => {
    expect(num(-12345)).toBe("-12,345");
  });
});

// ----- dateShort() -----

describe("dateShort()", () => {
  it("formats an ISO date as 'Mon D, YYYY' in en-US", () => {
    // Use a stable timezone-agnostic ISO date — 2026-04-26 noon UTC
    // formats to "Apr 26, 2026" regardless of the test runner's TZ
    // because Date with YYYY-MM-DD is parsed as UTC midnight and the
    // toLocaleDateString uses local TZ for display. We assert on the
    // year + month + day pieces individually to stay TZ-independent.
    const out = dateShort("2026-04-26T12:00:00Z");
    expect(out).toContain("2026");
    expect(out).toMatch(/Apr/);
    expect(out).toMatch(/\b26\b/);
  });
});

// ----- dateFull() -----

describe("dateFull()", () => {
  it("formats a date with weekday + month + day + year", () => {
    const out = dateFull(new Date("2026-04-26T12:00:00Z"));
    // April 26 2026 is a Sunday
    expect(out).toMatch(/Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday/);
    expect(out).toContain("2026");
  });

  it("defaults to today when no arg is passed", () => {
    const out = dateFull();
    const year = String(new Date().getFullYear());
    expect(out).toContain(year);
  });
});

// ----- signed() -----

describe("signed()", () => {
  it("prefixes positives with +", () => {
    expect(signed(0)).toBe("+0");
    expect(signed(42)).toBe("+42");
    expect(signed(1234)).toBe("+1,234");
  });

  it("uses the minus sign on negatives (no double-prefix)", () => {
    expect(signed(-1)).toBe("-1");
    expect(signed(-1234)).toBe("-1,234");
  });
});

// ----- cn() -----

describe("cn()", () => {
  it("joins truthy strings with a single space", () => {
    expect(cn("a", "b", "c")).toBe("a b c");
  });

  it("drops false / null / undefined entries", () => {
    expect(cn("a", false, "b", null, "c", undefined)).toBe("a b c");
  });

  it("returns empty string when no truthy parts", () => {
    expect(cn(false, null, undefined)).toBe("");
  });

  it("preserves the order of inputs", () => {
    expect(cn("c", "b", "a")).toBe("c b a");
  });
});

// ----- buildTrendPoints() -----

describe("buildTrendPoints()", () => {
  it("produces N points ending today (default 14)", () => {
    const today = new Date("2026-05-14T12:00:00Z");
    const out = buildTrendPoints([], today);

    expect(out).toHaveLength(14);
    expect(out[out.length - 1]?.isToday).toBe(true);
    expect(out.slice(0, -1).every((p) => !p.isToday)).toBe(true);
  });

  it("honors a custom days count", () => {
    const today = new Date("2026-05-14T12:00:00Z");
    const out = buildTrendPoints([], today, 7);
    expect(out).toHaveLength(7);
  });

  it("dates are ISO YYYY-MM-DD strings in chronological order", () => {
    const today = new Date("2026-05-14T12:00:00Z");
    const out = buildTrendPoints([], today, 5);
    expect(out[0]?.date).toBe("2026-05-10");
    expect(out[4]?.date).toBe("2026-05-14");
    // Strictly increasing
    for (let i = 1; i < out.length; i++) {
      const prev = out[i - 1] as DayPoint;
      const curr = out[i] as DayPoint;
      expect(curr.date > prev.date).toBe(true);
    }
  });

  it("fills census from the input entries by ISO date match", () => {
    const today = new Date("2026-05-14T12:00:00Z");
    const out = buildTrendPoints(
      [
        { entry_date: "2026-05-13", census: 198 },
        { entry_date: "2026-05-14", census: 201 },
      ],
      today,
      3,
    );

    expect(out[0]?.census).toBeNull();
    expect(out[1]?.census).toBe(198);
    expect(out[2]?.census).toBe(201);
    expect(out[2]?.isToday).toBe(true);
  });

  it("returns census=null for days without a matching entry (gap rendering)", () => {
    const today = new Date("2026-05-14T12:00:00Z");
    const out = buildTrendPoints([{ entry_date: "2026-05-10", census: 100 }], today, 5);

    // Only 2026-05-10 should have data; the other 4 days are null
    const nonNull = out.filter((p) => p.census !== null);
    expect(nonNull).toHaveLength(1);
    expect(nonNull[0]?.date).toBe("2026-05-10");
    expect(nonNull[0]?.census).toBe(100);
  });

  it("defaults today to new Date() when omitted", () => {
    const out = buildTrendPoints([], undefined as never, 3);
    expect(out).toHaveLength(3);
    // The last point should be 'today' relative to wall clock
    expect(out[out.length - 1]?.isToday).toBe(true);
    const todayIso = new Date().toISOString().slice(0, 10);
    expect(out[out.length - 1]?.date).toBe(todayIso);
  });

  it("ignores entries with dates outside the window", () => {
    const today = new Date("2026-05-14T12:00:00Z");
    const out = buildTrendPoints(
      [
        { entry_date: "2025-01-01", census: 999 }, // way outside the 5-day window
        { entry_date: "2026-05-14", census: 100 },
      ],
      today,
      5,
    );

    const found = out.find((p) => p.census === 999);
    expect(found).toBeUndefined();
    // The in-window entry still applies
    expect(out[out.length - 1]?.census).toBe(100);
  });
});
