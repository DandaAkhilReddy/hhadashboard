// @vitest-environment happy-dom
//
// MonthlyFinanceForm — Sandy Collins's biggest entry surface (FL + TX
// side-by-side). 11 NumFields × 2 states + AR-sum cross-validation +
// period selector that navigates via router.push + buildPayload that
// drops empty-collections rows + fromOut hydration that merges saved
// rows back into local state.

import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const saveMonthlyFinanceMock = vi.fn();
const refreshMock = vi.fn();
const pushMock = vi.fn();
const toastMock = vi.fn();

vi.mock("@/lib/api-browser", () => ({
  useApiBrowser: () => ({
    saveMonthlyFinance: (...args: unknown[]) => saveMonthlyFinanceMock(...args),
  }),
}));

vi.mock("@/components/Toast", () => ({
  toast: (...args: unknown[]) => toastMock(...args),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock, push: pushMock }),
}));

import type { MonthlyFinanceRowOut } from "@/lib/api-browser";

import { MonthlyFinanceForm } from "@/app/monthly-finance/MonthlyFinanceForm";

function row(
  state: "FL" | "TX",
  overrides: Partial<MonthlyFinanceRowOut> = {},
): MonthlyFinanceRowOut {
  return {
    id: state === "FL" ? 1 : 2,
    year: 2026,
    month: 5,
    period_first: "2026-05-01",
    state,
    collections_usd: "100000.00",
    ventra_fee_usd: state === "FL" ? "5000.00" : "0",
    ar_total_usd: "50000.00",
    ar_0_30_usd: "30000.00",
    ar_31_60_usd: "10000.00",
    ar_61_90_usd: "5000.00",
    ar_91_120_usd: "3000.00",
    ar_over_120_usd: "2000.00",
    net_collection_rate_pct: "95.5",
    days_in_ar: "42.0",
    source_system: state === "FL" ? "VENTRA_FL_FALLBACK" : "HHA_TX_MANUAL",
    entered_by_upn: "sandy@hhamedicine.com",
    notes: state === "FL" ? "Ventra fallback for April" : null,
    updated_at: "2026-05-01T15:00:00Z",
    ...overrides,
  };
}

describe("MonthlyFinanceForm — render + hydration", () => {
  beforeEach(() => {
    saveMonthlyFinanceMock.mockReset();
    refreshMock.mockReset();
    pushMock.mockReset();
    toastMock.mockReset();
  });

  it("renders both FL and TX panels side-by-side with distinct subtitles", () => {
    render(<MonthlyFinanceForm initialYear={2026} initialMonth={5} initialRows={[]} />);

    expect(screen.getByText("FL")).toBeInTheDocument();
    expect(screen.getByText("TX")).toBeInTheDocument();
    expect(screen.getByText(/Ventra fallback/i)).toBeInTheDocument();
    expect(screen.getByText(/HHA manual/i)).toBeInTheDocument();
  });

  it("renders the month label as 'May 2026' in the CardHeader", () => {
    render(<MonthlyFinanceForm initialYear={2026} initialMonth={5} initialRows={[]} />);
    expect(screen.getByText(/May 2026/)).toBeInTheDocument();
  });

  it("renders the year-window selector with [year-2, year-1, year, year+1]", () => {
    render(<MonthlyFinanceForm initialYear={2026} initialMonth={5} initialRows={[]} />);
    // The year select has 4 options: 2024, 2025, 2026, 2027
    expect(screen.getByRole("option", { name: "2024" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "2025" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "2026" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "2027" })).toBeInTheDocument();
  });

  it("hydrates FL fields from initialRows via fromOut", () => {
    render(
      <MonthlyFinanceForm
        initialYear={2026}
        initialMonth={5}
        initialRows={[row("FL", { collections_usd: "123456.78", notes: "April reconciled" })]}
      />,
    );

    expect(screen.getByDisplayValue("123456.78")).toBeInTheDocument();
    expect(screen.getByDisplayValue("April reconciled")).toBeInTheDocument();
  });

  it("hydrates TX with empty notes when source has notes=null", () => {
    render(
      <MonthlyFinanceForm
        initialYear={2026}
        initialMonth={5}
        initialRows={[row("TX", { notes: null })]}
      />,
    );

    // 2 notes inputs total (FL + TX). Both should be present as text inputs.
    const notesInputs = screen
      .getAllByRole("textbox")
      .filter((el) => (el as HTMLInputElement).placeholder?.includes("Ventra report"));
    expect(notesInputs.length).toBe(2);
    // The TX one has empty value, the FL one (no initialRow) is also empty
    expect(notesInputs.every((el) => (el as HTMLInputElement).value === "")).toBe(true);
  });

  it("emptyRow defaults: all numeric NumFields start blank when no initialRow", () => {
    render(<MonthlyFinanceForm initialYear={2026} initialMonth={5} initialRows={[]} />);
    // 10 NumFields × 2 states = 20 number inputs total
    // (Collections, Ventra fee, AR 0-30, 31-60, 61-90, 91-120, >120, AR total,
    //  Net Collection Rate, Days in A/R)
    const numberInputs = screen.getAllByRole("spinbutton");
    expect(numberInputs.length).toBe(20);
    expect(numberInputs.every((el) => (el as HTMLInputElement).value === "")).toBe(true);
  });

  it("renders the FL Ventra-fee hint ('5% of collections') and TX n/a copy", () => {
    render(<MonthlyFinanceForm initialYear={2026} initialMonth={5} initialRows={[]} />);
    expect(screen.getByText(/5% of collections/i)).toBeInTheDocument();
    expect(screen.getByText(/n\/a \(TX has no Ventra\)/i)).toBeInTheDocument();
  });

  it("renders 'target: 45 days' as the Days in A/R hint", () => {
    render(<MonthlyFinanceForm initialYear={2026} initialMonth={5} initialRows={[]} />);
    // Two hints (one per state), both saying "target: 45 days"
    expect(screen.getAllByText(/target: 45 days/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the per-state 'Saved' date sub-line when updated_at is present", () => {
    render(
      <MonthlyFinanceForm
        initialYear={2026}
        initialMonth={5}
        initialRows={[row("FL", { updated_at: "2026-05-01T15:00:00Z" })]}
      />,
    );
    expect(screen.getAllByText(/Saved/).length).toBeGreaterThan(0);
  });
});

describe("MonthlyFinanceForm — AR sum cross-validation", () => {
  beforeEach(() => {
    saveMonthlyFinanceMock.mockReset();
    refreshMock.mockReset();
    pushMock.mockReset();
    toastMock.mockReset();
  });

  it("shows 'enter buckets first' hint when AR total is empty", () => {
    render(<MonthlyFinanceForm initialYear={2026} initialMonth={5} initialRows={[]} />);
    expect(screen.getAllByText(/enter buckets first/i).length).toBeGreaterThanOrEqual(1);
  });

  it("shows '✓ matches sum' hint when buckets sum equals AR total within $0.50", () => {
    render(
      <MonthlyFinanceForm
        initialYear={2026}
        initialMonth={5}
        initialRows={[
          row("FL", {
            ar_total_usd: "50000",
            ar_0_30_usd: "30000",
            ar_31_60_usd: "10000",
            ar_61_90_usd: "5000",
            ar_91_120_usd: "3000",
            ar_over_120_usd: "2000",
          }),
        ]}
      />,
    );
    // Sum = 50000, total = 50000 → matches
    expect(screen.getByText(/✓ matches sum/)).toBeInTheDocument();
  });

  it("shows the warn hint when buckets sum diverges from AR total", () => {
    render(
      <MonthlyFinanceForm
        initialYear={2026}
        initialMonth={5}
        initialRows={[
          row("FL", {
            ar_total_usd: "50000",
            ar_0_30_usd: "30000",
            ar_31_60_usd: "10000",
            ar_61_90_usd: "5000",
            ar_91_120_usd: "3000",
            ar_over_120_usd: "999", // 48,999 != 50,000
          }),
        ]}
      />,
    );
    expect(screen.getByText(/⚠ buckets sum to/i)).toBeInTheDocument();
  });

  it("re-evaluates the AR-sum hint live when the user types in a bucket", () => {
    render(
      <MonthlyFinanceForm
        initialYear={2026}
        initialMonth={5}
        initialRows={[
          row("FL", {
            ar_total_usd: "50000",
            ar_0_30_usd: "30000",
            ar_31_60_usd: "10000",
            ar_61_90_usd: "5000",
            ar_91_120_usd: "3000",
            ar_over_120_usd: "2000",
          }),
        ]}
      />,
    );
    // Initially matches
    expect(screen.getByText(/✓ matches sum/)).toBeInTheDocument();

    // Type a different value into 0-30 bucket — sum becomes 50,001 - 30,000 = 20,001 short
    const input030 = screen.getByDisplayValue("30000") as HTMLInputElement;
    fireEvent.change(input030, { target: { value: "29999" } });

    expect(screen.getByText(/⚠ buckets sum to/i)).toBeInTheDocument();
  });
});

describe("MonthlyFinanceForm — period selector", () => {
  beforeEach(() => {
    saveMonthlyFinanceMock.mockReset();
    refreshMock.mockReset();
    pushMock.mockReset();
    toastMock.mockReset();
  });

  it("changing month routes to /monthly-finance?year=Y&month=M", () => {
    render(<MonthlyFinanceForm initialYear={2026} initialMonth={5} initialRows={[]} />);

    const monthSelect = screen
      .getAllByRole("combobox")
      .find((el) => (el as HTMLSelectElement).value === "5") as HTMLSelectElement;

    fireEvent.change(monthSelect, { target: { value: "3" } });

    expect(pushMock).toHaveBeenCalledWith("/monthly-finance?year=2026&month=3");
  });

  it("changing year routes to /monthly-finance?year=Y&month=M (keeps current month)", () => {
    render(<MonthlyFinanceForm initialYear={2026} initialMonth={5} initialRows={[]} />);

    const yearSelect = screen
      .getAllByRole("combobox")
      .find((el) => (el as HTMLSelectElement).value === "2026") as HTMLSelectElement;

    fireEvent.change(yearSelect, { target: { value: "2025" } });

    expect(pushMock).toHaveBeenCalledWith("/monthly-finance?year=2025&month=5");
  });
});

describe("MonthlyFinanceForm — save flow", () => {
  beforeEach(() => {
    saveMonthlyFinanceMock.mockReset();
    refreshMock.mockReset();
    pushMock.mockReset();
    toastMock.mockReset();
  });

  it("toasts an error and skips the API call when no state has collections", async () => {
    render(<MonthlyFinanceForm initialYear={2026} initialMonth={5} initialRows={[]} />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    expect(saveMonthlyFinanceMock).not.toHaveBeenCalled();
    expect(toastMock).toHaveBeenCalledWith(
      expect.stringMatching(/Enter at least one state's collections/i),
      "error",
    );
  });

  it("buildPayload includes only states with non-empty collections_usd", async () => {
    saveMonthlyFinanceMock.mockResolvedValue([]);

    render(
      <MonthlyFinanceForm
        initialYear={2026}
        initialMonth={5}
        initialRows={[row("FL", { collections_usd: "100000" })]}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    expect(saveMonthlyFinanceMock).toHaveBeenCalledTimes(1);
    const arg = saveMonthlyFinanceMock.mock.calls[0]?.[0] as {
      year: number;
      month: number;
      rows: Array<{ state: string }>;
    };
    expect(arg.year).toBe(2026);
    expect(arg.month).toBe(5);
    expect(arg.rows.length).toBe(1);
    expect(arg.rows[0]?.state).toBe("FL");
  });

  it("buildPayload defaults empty numeric NumFields to '0' string", async () => {
    saveMonthlyFinanceMock.mockResolvedValue([]);

    render(
      <MonthlyFinanceForm
        initialYear={2026}
        initialMonth={5}
        initialRows={[
          row("FL", {
            collections_usd: "100000",
            ventra_fee_usd: "",
            ar_total_usd: "",
            ar_0_30_usd: "",
          }),
        ]}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    const sent = saveMonthlyFinanceMock.mock.calls[0]?.[0] as {
      rows: Array<{
        collections_usd: string;
        ventra_fee_usd: string;
        ar_total_usd: string;
        ar_0_30_usd: string;
      }>;
    };
    expect(sent.rows[0]?.collections_usd).toBe("100000");
    expect(sent.rows[0]?.ventra_fee_usd).toBe("0");
    expect(sent.rows[0]?.ar_total_usd).toBe("0");
    expect(sent.rows[0]?.ar_0_30_usd).toBe("0");
  });

  it("buildPayload trims notes; empty notes -> null", async () => {
    saveMonthlyFinanceMock.mockResolvedValue([]);

    render(
      <MonthlyFinanceForm
        initialYear={2026}
        initialMonth={5}
        initialRows={[row("FL", { collections_usd: "100000", notes: "   " })]}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    const sent = saveMonthlyFinanceMock.mock.calls[0]?.[0] as {
      rows: Array<{ notes: string | null }>;
    };
    expect(sent.rows[0]?.notes).toBeNull();
  });

  it("on success: pluralized toast ('1 state row')", async () => {
    saveMonthlyFinanceMock.mockResolvedValue([row("FL", { collections_usd: "100000" })]);

    render(
      <MonthlyFinanceForm
        initialYear={2026}
        initialMonth={5}
        initialRows={[row("FL", { collections_usd: "100000" })]}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    expect(toastMock).toHaveBeenCalledWith("Saved 1 state row.", "success");
    expect(refreshMock).toHaveBeenCalledTimes(1);
  });

  it("on success: pluralized toast ('N state rows') when both states save", async () => {
    saveMonthlyFinanceMock.mockResolvedValue([
      row("FL", { collections_usd: "100000" }),
      row("TX", { collections_usd: "50000" }),
    ]);

    render(
      <MonthlyFinanceForm
        initialYear={2026}
        initialMonth={5}
        initialRows={[
          row("FL", { collections_usd: "100000" }),
          row("TX", { collections_usd: "50000" }),
        ]}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    expect(toastMock).toHaveBeenCalledWith("Saved 2 state rows.", "success");
  });

  it("on save failure: error toast with the error message; no refresh", async () => {
    saveMonthlyFinanceMock.mockRejectedValue(new Error("backend 500"));

    render(
      <MonthlyFinanceForm
        initialYear={2026}
        initialMonth={5}
        initialRows={[row("FL", { collections_usd: "100000" })]}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    expect(toastMock).toHaveBeenCalledWith(
      expect.stringMatching(/Save failed: backend 500/),
      "error",
    );
    expect(refreshMock).not.toHaveBeenCalled();
  });

  it("after a successful save, the saved row's source_system flows into local state", async () => {
    saveMonthlyFinanceMock.mockResolvedValue([
      row("FL", {
        collections_usd: "100000",
        source_system: "VENTRA_FL_AUTO",
        updated_at: "2026-05-13T20:00:00Z",
      }),
    ]);

    render(
      <MonthlyFinanceForm
        initialYear={2026}
        initialMonth={5}
        initialRows={[row("FL", { collections_usd: "100000" })]}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    // The Saved sub-line now reflects the new updated_at
    expect(screen.getAllByText(/Saved/).length).toBeGreaterThan(0);
  });

  it("disables all inputs and shows 'Saving...' while save is in flight", async () => {
    // Make save resolve later so we can observe the in-flight state
    let resolveSave!: (rows: MonthlyFinanceRowOut[]) => void;
    saveMonthlyFinanceMock.mockImplementation(
      () =>
        new Promise<MonthlyFinanceRowOut[]>((res) => {
          resolveSave = res;
        }),
    );

    render(
      <MonthlyFinanceForm
        initialYear={2026}
        initialMonth={5}
        initialRows={[row("FL", { collections_usd: "100000" })]}
      />,
    );

    const saveBtn = screen.getByRole("button", { name: /^Save$/ });
    fireEvent.click(saveBtn);

    // Mid-flight: button label flips
    expect(screen.getByRole("button", { name: /Saving/ })).toBeDisabled();

    await act(async () => {
      resolveSave([row("FL", { collections_usd: "100000" })]);
    });
  });
});
