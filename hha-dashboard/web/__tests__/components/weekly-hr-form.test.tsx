// @vitest-environment happy-dom
//
// WeeklyHrForm — Andrea's single-row HR snapshot. Distinct shape from
// DailyCensusForm: one form (not a table), week-ending date picker
// that pushes a query-string route on change, and a live "derived"
// panel showing total headcount + turnover% + W-2/1099 mix.

import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const saveWeeklyHrMock = vi.fn();
const refreshMock = vi.fn();
const pushMock = vi.fn();
const toastMock = vi.fn();

vi.mock("@/lib/api-browser", () => ({
  useApiBrowser: () => ({
    saveWeeklyHr: (...args: unknown[]) => saveWeeklyHrMock(...args),
  }),
}));

vi.mock("@/components/Toast", () => ({
  toast: (...args: unknown[]) => toastMock(...args),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock, push: pushMock }),
}));

import type { WeeklyHrOut } from "@/lib/api-browser";

import { WeeklyHrForm } from "@/app/weekly-hr/WeeklyHrForm";

// 2026-05-10 is a Sunday in real life; we anchor every test on it.
const LAST_SUNDAY = "2026-05-10";

function existing(overrides: Partial<WeeklyHrOut> = {}): WeeklyHrOut {
  return {
    week_ending: LAST_SUNDAY,
    headcount_w2: 100,
    headcount_1099: 25,
    open_positions_total: 5,
    terminations_90d_count: 8,
    below_fmv_count: 3,
    notes: null,
    entered_by_upn: null,
    updated_at: null,
    ...overrides,
  } as WeeklyHrOut;
}

describe("WeeklyHrForm", () => {
  beforeEach(() => {
    saveWeeklyHrMock.mockReset();
    refreshMock.mockReset();
    pushMock.mockReset();
    toastMock.mockReset();
  });

  it("renders empty inputs when initial is null", () => {
    render(<WeeklyHrForm initialWeekEnding={LAST_SUNDAY} initial={null} />);

    const numberInputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    // 5 NumField inputs: W-2, 1099, open_positions, terminations, below_fmv
    expect(numberInputs.length).toBe(5);
    expect(numberInputs.every((i) => i.value === "")).toBe(true);
  });

  it("hydrates inputs from an existing row when initial is non-null", () => {
    render(
      <WeeklyHrForm
        initialWeekEnding={LAST_SUNDAY}
        initial={existing({ headcount_w2: 187, headcount_1099: 42 })}
      />,
    );

    const numberInputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    expect(numberInputs[0]?.value).toBe("187");
    expect(numberInputs[1]?.value).toBe("42");
  });

  it("derived panel shows '—' for total + turnover when both headcounts are 0", () => {
    render(<WeeklyHrForm initialWeekEnding={LAST_SUNDAY} initial={null} />);

    // total = 0, turnoverPct = '—'
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("derived panel updates total + turnover live as the user types", () => {
    render(<WeeklyHrForm initialWeekEnding={LAST_SUNDAY} initial={null} />);

    const inputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    // W-2 = 100, 1099 = 25, terms = 5 -> total 125, turnover 4.0%
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "100" } });
    fireEvent.change(inputs[1] as HTMLInputElement, { target: { value: "25" } });
    fireEvent.change(inputs[3] as HTMLInputElement, { target: { value: "5" } });

    expect(screen.getByText("125")).toBeInTheDocument();
    expect(screen.getByText("4.0%")).toBeInTheDocument();
  });

  it("turnover tone flips to red when terms/total > 10%", () => {
    render(<WeeklyHrForm initialWeekEnding={LAST_SUNDAY} initial={null} />);

    const inputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    // total 100, terms 15 -> 15% -> red
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "100" } });
    fireEvent.change(inputs[3] as HTMLInputElement, { target: { value: "15" } });

    const turnover = screen.getByText("15.0%");
    expect(turnover.className).toContain("text-red-600");
  });

  it("turnover tone stays neutral (slate-900) when terms/total <= 10%", () => {
    render(<WeeklyHrForm initialWeekEnding={LAST_SUNDAY} initial={null} />);

    const inputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "100" } });
    fireEvent.change(inputs[3] as HTMLInputElement, { target: { value: "5" } });

    const turnover = screen.getByText("5.0%");
    expect(turnover.className).toContain("text-slate-900");
    expect(turnover.className).not.toContain("text-red-600");
  });

  it("renders W-2 / 1099 mix percentage from the live totals", () => {
    render(<WeeklyHrForm initialWeekEnding={LAST_SUNDAY} initial={null} />);

    const inputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "75" } }); // W-2
    fireEvent.change(inputs[1] as HTMLInputElement, { target: { value: "25" } }); // 1099

    expect(screen.getByText("75% / 25%")).toBeInTheDocument();
  });

  it("changing the date picker calls router.push with ?week_ending param", () => {
    render(<WeeklyHrForm initialWeekEnding={LAST_SUNDAY} initial={null} />);

    const dateInput = document.querySelector('input[type="date"]') as HTMLInputElement;
    fireEvent.change(dateInput, { target: { value: "2026-05-03" } });

    expect(pushMock).toHaveBeenCalledWith("/weekly-hr?week_ending=2026-05-03");
  });

  it("rejects save when both W-2 and 1099 are empty", () => {
    render(<WeeklyHrForm initialWeekEnding={LAST_SUNDAY} initial={null} />);

    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    expect(toastMock).toHaveBeenCalledWith(
      expect.stringMatching(/at least one headcount/),
      "error",
    );
    expect(saveWeeklyHrMock).not.toHaveBeenCalled();
  });

  it("rejects save when week_ending is not a Sunday", () => {
    // 2026-05-13 is a Wednesday
    render(<WeeklyHrForm initialWeekEnding="2026-05-13" initial={null} />);

    const inputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "100" } });
    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    expect(toastMock).toHaveBeenCalledWith(
      expect.stringMatching(/Week ending must be a Sunday/),
      "error",
    );
    expect(saveWeeklyHrMock).not.toHaveBeenCalled();
  });

  it("happy path: POSTs the full payload with parsed numbers + null notes when empty", async () => {
    saveWeeklyHrMock.mockResolvedValue(existing({ headcount_w2: 100 }));

    render(<WeeklyHrForm initialWeekEnding={LAST_SUNDAY} initial={null} />);

    const inputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "100" } }); // W-2
    fireEvent.change(inputs[1] as HTMLInputElement, { target: { value: "25" } });
    fireEvent.change(inputs[2] as HTMLInputElement, { target: { value: "5" } });
    fireEvent.change(inputs[3] as HTMLInputElement, { target: { value: "8" } });
    fireEvent.change(inputs[4] as HTMLInputElement, { target: { value: "3" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    expect(saveWeeklyHrMock).toHaveBeenCalledTimes(1);
    const payload = saveWeeklyHrMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(payload.week_ending).toBe(LAST_SUNDAY);
    expect(payload.headcount_w2).toBe(100);
    expect(payload.headcount_1099).toBe(25);
    expect(payload.open_positions_total).toBe(5);
    expect(payload.terminations_90d_count).toBe(8);
    expect(payload.below_fmv_count).toBe(3);
    expect(payload.notes).toBeNull();
  });

  it("happy path: sends trimmed notes when non-empty", async () => {
    saveWeeklyHrMock.mockResolvedValue(existing());

    render(<WeeklyHrForm initialWeekEnding={LAST_SUNDAY} initial={null} />);

    const inputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "100" } });

    const notesInput = screen.getByPlaceholderText(/Westside MD search active/) as HTMLInputElement;
    fireEvent.change(notesInput, {
      target: { value: "  active MD search at Westside  " },
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    const payload = saveWeeklyHrMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(payload.notes).toBe("active MD search at Westside");
  });

  it("on success: toast.success 'Saved.' + router.refresh + draft re-hydrates from server response", async () => {
    saveWeeklyHrMock.mockResolvedValue(
      existing({
        headcount_w2: 200,
        headcount_1099: 50,
        updated_at: "2026-05-10T18:00:00Z",
      }),
    );

    render(<WeeklyHrForm initialWeekEnding={LAST_SUNDAY} initial={null} />);

    const inputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "100" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    expect(toastMock).toHaveBeenCalledWith("Saved.", "success");
    expect(refreshMock).toHaveBeenCalledTimes(1);
    // Draft re-hydrated from server response
    const reInputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    expect(reInputs[0]?.value).toBe("200");
    expect(reInputs[1]?.value).toBe("50");
    // 'Last saved' line renders
    expect(screen.getByText(/Last saved/)).toBeInTheDocument();
  });

  it("on api error: toast.error with err.message + no router.refresh", async () => {
    saveWeeklyHrMock.mockRejectedValue(new Error("network down"));

    render(<WeeklyHrForm initialWeekEnding={LAST_SUNDAY} initial={null} />);

    const inputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "100" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    expect(toastMock).toHaveBeenCalledWith(expect.stringMatching(/network down/), "error");
    expect(refreshMock).not.toHaveBeenCalled();
  });

  it("shows 'Saving…' label + disables inputs while api call in flight", async () => {
    let resolveSave!: (v: WeeklyHrOut) => void;
    saveWeeklyHrMock.mockReturnValue(
      new Promise<WeeklyHrOut>((r) => {
        resolveSave = r;
      }),
    );

    render(<WeeklyHrForm initialWeekEnding={LAST_SUNDAY} initial={null} />);

    const inputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "100" } });

    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    // Mid-flight assertions
    expect(screen.getByRole("button", { name: /Saving/i })).toBeDisabled();
    expect(inputs[0]).toBeDisabled();
    // Date picker also disabled mid-flight
    const dateInput = document.querySelector('input[type="date"]') as HTMLInputElement;
    expect(dateInput).toBeDisabled();

    await act(async () => {
      resolveSave(existing({ headcount_w2: 100 }));
    });
  });

  it("payload uses 0 for fields the user left empty (not NaN)", async () => {
    saveWeeklyHrMock.mockResolvedValue(existing());

    render(<WeeklyHrForm initialWeekEnding={LAST_SUNDAY} initial={null} />);

    const inputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    // Only W-2; leave the rest blank
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "100" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    const payload = saveWeeklyHrMock.mock.calls[0]?.[0] as Record<string, unknown>;
    // All blank fields default to 0, not NaN
    expect(payload.headcount_1099).toBe(0);
    expect(payload.open_positions_total).toBe(0);
    expect(payload.terminations_90d_count).toBe(0);
    expect(payload.below_fmv_count).toBe(0);
  });

  it("renders 'Last saved' line only when draft.updated_at is non-null", () => {
    render(
      <WeeklyHrForm
        initialWeekEnding={LAST_SUNDAY}
        initial={existing({ updated_at: "2026-05-10T18:00:00Z" })}
      />,
    );

    expect(screen.getByText(/Last saved/)).toBeInTheDocument();
  });

  it("omits 'Last saved' line when updated_at is null", () => {
    render(<WeeklyHrForm initialWeekEnding={LAST_SUNDAY} initial={null} />);
    expect(screen.queryByText(/Last saved/)).toBeNull();
  });
});
