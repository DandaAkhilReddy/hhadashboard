// @vitest-environment happy-dom
//
// WeeklyClinicalForm — Dr. Aneja / Dr. Reddy entry surface. Distinct
// from the other forms: TWO state sections (FL + TX) side-by-side,
// each with its own quad-NumField + notes, plus the at-target hint
// labels that toggle based on the typed % values.

import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const saveWeeklyClinicalMock = vi.fn();
const refreshMock = vi.fn();
const pushMock = vi.fn();
const toastMock = vi.fn();

vi.mock("@/lib/api-browser", () => ({
  useApiBrowser: () => ({
    saveWeeklyClinical: (...args: unknown[]) => saveWeeklyClinicalMock(...args),
  }),
}));

vi.mock("@/components/Toast", () => ({
  toast: (...args: unknown[]) => toastMock(...args),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock, push: pushMock }),
}));

import type { WeeklyClinicalRowOut } from "@/lib/api-browser";

import { WeeklyClinicalForm } from "@/app/weekly-clinical/WeeklyClinicalForm";

const LAST_SUNDAY = "2026-05-10";

function row(
  state: "FL" | "TX",
  overrides: Partial<WeeklyClinicalRowOut> = {},
): WeeklyClinicalRowOut {
  return {
    week_ending: LAST_SUNDAY,
    state,
    hp_24h_pct: "96.5",
    dc_48h_pct: "88.0",
    avg_los_days: "4.2",
    charts_audited_count: 50,
    notes: null,
    entered_by_upn: null,
    updated_at: null,
    ...overrides,
  } as WeeklyClinicalRowOut;
}

describe("WeeklyClinicalForm", () => {
  beforeEach(() => {
    saveWeeklyClinicalMock.mockReset();
    refreshMock.mockReset();
    pushMock.mockReset();
    toastMock.mockReset();
  });

  it("renders both state sections (FL + TX) with empty inputs when initialRows is empty", () => {
    render(<WeeklyClinicalForm initialWeekEnding={LAST_SUNDAY} initialRows={[]} />);

    // Two h3 headings — 'FL' and 'TX'
    const headings = screen.getAllByRole("heading", { level: 3 });
    expect(headings.map((h) => h.textContent)).toEqual(["FL", "TX"]);
  });

  it("hydrates FL section from initialRows.find(state==='FL')", () => {
    render(
      <WeeklyClinicalForm
        initialWeekEnding={LAST_SUNDAY}
        initialRows={[row("FL", { hp_24h_pct: "97.0", avg_los_days: "4.0" })]}
      />,
    );

    const inputs = document.querySelectorAll(
      'input[type="number"]',
    ) as NodeListOf<HTMLInputElement>;
    // 8 NumFields total: 4 per state * 2 states
    expect(inputs.length).toBe(8);
    // First 4 inputs are FL (hp, dc, los, charts)
    expect(inputs[0]?.value).toBe("97.0");
    expect(inputs[2]?.value).toBe("4.0");
  });

  it("hydrates TX section independently from initialRows.find(state==='TX')", () => {
    render(
      <WeeklyClinicalForm
        initialWeekEnding={LAST_SUNDAY}
        initialRows={[row("TX", { hp_24h_pct: "92.0", charts_audited_count: 25 })]}
      />,
    );

    const inputs = document.querySelectorAll(
      'input[type="number"]',
    ) as NodeListOf<HTMLInputElement>;
    // TX inputs start at index 4
    expect(inputs[4]?.value).toBe("92.0");
    expect(inputs[7]?.value).toBe("25");
  });

  it("renders 'Saved' badge when a state row carries updated_at", () => {
    render(
      <WeeklyClinicalForm
        initialWeekEnding={LAST_SUNDAY}
        initialRows={[row("FL", { updated_at: "2026-05-10T18:00:00Z" })]}
      />,
    );

    expect(screen.getByText("Saved")).toBeInTheDocument();
  });

  it("renders ✓-at-target hint when hp_24h_pct >= 95", () => {
    render(
      <WeeklyClinicalForm
        initialWeekEnding={LAST_SUNDAY}
        initialRows={[row("FL", { hp_24h_pct: "96.5" })]}
      />,
    );

    // Both H&P (96.5 >= 95) and DC (88 < 90) hints present
    const atTargets = screen.getAllByText("✓ at target");
    expect(atTargets.length).toBeGreaterThanOrEqual(1);
  });

  it("renders ⚠ below-target hint when hp_24h_pct < 95", () => {
    render(
      <WeeklyClinicalForm
        initialWeekEnding={LAST_SUNDAY}
        initialRows={[row("FL", { hp_24h_pct: "92.0" })]}
      />,
    );

    expect(screen.getByText(/⚠ below 95% target/)).toBeInTheDocument();
  });

  it("renders DC ⚠ below-90% hint when dc_48h_pct < 90", () => {
    render(
      <WeeklyClinicalForm
        initialWeekEnding={LAST_SUNDAY}
        initialRows={[row("FL", { dc_48h_pct: "85.0" })]}
      />,
    );

    expect(screen.getByText(/⚠ below 90% target/)).toBeInTheDocument();
  });

  it("hints are absent when the user has not typed any value yet (empty inputs)", () => {
    render(<WeeklyClinicalForm initialWeekEnding={LAST_SUNDAY} initialRows={[]} />);

    expect(screen.queryByText(/at target/)).toBeNull();
    expect(screen.queryByText(/below 95%/)).toBeNull();
  });

  it("changing the date picker calls router.push with ?week_ending param", () => {
    render(<WeeklyClinicalForm initialWeekEnding={LAST_SUNDAY} initialRows={[]} />);

    const dateInput = document.querySelector('input[type="date"]') as HTMLInputElement;
    fireEvent.change(dateInput, { target: { value: "2026-05-03" } });

    expect(pushMock).toHaveBeenCalledWith("/weekly-clinical?week_ending=2026-05-03");
  });

  it("rejects save when both states have empty hp + dc (no rows to submit)", () => {
    render(<WeeklyClinicalForm initialWeekEnding={LAST_SUNDAY} initialRows={[]} />);

    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    expect(toastMock).toHaveBeenCalledWith(
      expect.stringMatching(/at least one state's H&P or DC/i),
      "error",
    );
    expect(saveWeeklyClinicalMock).not.toHaveBeenCalled();
  });

  it("rejects save when week_ending is not a Sunday", () => {
    // 2026-05-13 is Wednesday
    render(<WeeklyClinicalForm initialWeekEnding="2026-05-13" initialRows={[]} />);

    const inputs = document.querySelectorAll(
      'input[type="number"]',
    ) as NodeListOf<HTMLInputElement>;
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "96" } });

    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    expect(toastMock).toHaveBeenCalledWith(
      expect.stringMatching(/Week ending must be a Sunday/),
      "error",
    );
    expect(saveWeeklyClinicalMock).not.toHaveBeenCalled();
  });

  it("buildPayload filters out states with both hp + dc empty (sends only filled state rows)", async () => {
    saveWeeklyClinicalMock.mockResolvedValue([]);

    render(<WeeklyClinicalForm initialWeekEnding={LAST_SUNDAY} initialRows={[]} />);

    const inputs = document.querySelectorAll(
      'input[type="number"]',
    ) as NodeListOf<HTMLInputElement>;
    // Fill only FL (inputs 0-3), leave TX (inputs 4-7) empty
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "96.5" } });
    fireEvent.change(inputs[1] as HTMLInputElement, { target: { value: "88.0" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    const payload = saveWeeklyClinicalMock.mock.calls[0]?.[0] as {
      week_ending: string;
      rows: Array<{ state: string }>;
    };
    expect(payload.week_ending).toBe(LAST_SUNDAY);
    expect(payload.rows).toHaveLength(1);
    expect(payload.rows[0]?.state).toBe("FL");
  });

  it("sends both rows when both states are filled", async () => {
    saveWeeklyClinicalMock.mockResolvedValue([]);

    render(<WeeklyClinicalForm initialWeekEnding={LAST_SUNDAY} initialRows={[]} />);

    const inputs = document.querySelectorAll(
      'input[type="number"]',
    ) as NodeListOf<HTMLInputElement>;
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "96.5" } }); // FL hp
    fireEvent.change(inputs[4] as HTMLInputElement, { target: { value: "94.0" } }); // TX hp

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    const payload = saveWeeklyClinicalMock.mock.calls[0]?.[0] as {
      rows: Array<{ state: string }>;
    };
    expect(payload.rows.map((r) => r.state).sort()).toEqual(["FL", "TX"]);
  });

  it("empty hp_24h_pct in payload defaults to '0' string (server expects Decimal-string)", async () => {
    saveWeeklyClinicalMock.mockResolvedValue([]);

    render(<WeeklyClinicalForm initialWeekEnding={LAST_SUNDAY} initialRows={[]} />);

    const inputs = document.querySelectorAll(
      'input[type="number"]',
    ) as NodeListOf<HTMLInputElement>;
    // Fill only DC for FL (leaves hp empty); buildPayload should still
    // include this row (dc has a value) with hp_24h_pct: '0'
    fireEvent.change(inputs[1] as HTMLInputElement, { target: { value: "88.0" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    const payload = saveWeeklyClinicalMock.mock.calls[0]?.[0] as {
      rows: Array<{ hp_24h_pct: string; dc_48h_pct: string }>;
    };
    expect(payload.rows[0]?.hp_24h_pct).toBe("0");
    expect(payload.rows[0]?.dc_48h_pct).toBe("88.0");
  });

  it("charts_audited_count parses to int; empty becomes 0", async () => {
    saveWeeklyClinicalMock.mockResolvedValue([]);

    render(<WeeklyClinicalForm initialWeekEnding={LAST_SUNDAY} initialRows={[]} />);

    const inputs = document.querySelectorAll(
      'input[type="number"]',
    ) as NodeListOf<HTMLInputElement>;
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "96.5" } });
    fireEvent.change(inputs[3] as HTMLInputElement, { target: { value: "47" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    const payload = saveWeeklyClinicalMock.mock.calls[0]?.[0] as {
      rows: Array<{ charts_audited_count: number }>;
    };
    expect(payload.rows[0]?.charts_audited_count).toBe(47);
  });

  it("notes trimmed + null when empty", async () => {
    saveWeeklyClinicalMock.mockResolvedValue([]);

    render(<WeeklyClinicalForm initialWeekEnding={LAST_SUNDAY} initialRows={[]} />);

    const inputs = document.querySelectorAll(
      'input[type="number"]',
    ) as NodeListOf<HTMLInputElement>;
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "96.5" } });

    const flNotes = screen.getAllByPlaceholderText(
      /Woodmont LOS still 5.8d/,
    )[0] as HTMLInputElement;
    fireEvent.change(flNotes, { target: { value: "  reviewed 3 outliers  " } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    const payload = saveWeeklyClinicalMock.mock.calls[0]?.[0] as {
      rows: Array<{ notes: string | null }>;
    };
    expect(payload.rows[0]?.notes).toBe("reviewed 3 outliers");
  });

  it("on success: toast 'Saved N state row(s)' pluralized + router.refresh + draft re-hydrates", async () => {
    saveWeeklyClinicalMock.mockResolvedValue([
      row("FL", { hp_24h_pct: "96.5", updated_at: "2026-05-10T18:00Z" }),
      row("TX", { hp_24h_pct: "94.0", updated_at: "2026-05-10T18:00Z" }),
    ]);

    render(<WeeklyClinicalForm initialWeekEnding={LAST_SUNDAY} initialRows={[]} />);

    const inputs = document.querySelectorAll(
      'input[type="number"]',
    ) as NodeListOf<HTMLInputElement>;
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "96.5" } });
    fireEvent.change(inputs[4] as HTMLInputElement, { target: { value: "94.0" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    expect(toastMock).toHaveBeenCalledWith(
      expect.stringMatching(/Saved 2 state rows\./),
      "success",
    );
    expect(refreshMock).toHaveBeenCalledTimes(1);
    // Both sections now show 'Saved' badge
    expect(screen.getAllByText("Saved").length).toBe(2);
  });

  it("single-row save: toast 'Saved 1 state row.' (singular)", async () => {
    saveWeeklyClinicalMock.mockResolvedValue([
      row("FL", { hp_24h_pct: "96.5", updated_at: "2026-05-10T18:00Z" }),
    ]);

    render(<WeeklyClinicalForm initialWeekEnding={LAST_SUNDAY} initialRows={[]} />);

    const inputs = document.querySelectorAll(
      'input[type="number"]',
    ) as NodeListOf<HTMLInputElement>;
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "96.5" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    expect(toastMock).toHaveBeenCalledWith(
      expect.stringMatching(/Saved 1 state row\.$/),
      "success",
    );
  });

  it("on api error: toast.error with err.message + no router.refresh", async () => {
    saveWeeklyClinicalMock.mockRejectedValue(new Error("network down"));

    render(<WeeklyClinicalForm initialWeekEnding={LAST_SUNDAY} initialRows={[]} />);

    const inputs = document.querySelectorAll(
      'input[type="number"]',
    ) as NodeListOf<HTMLInputElement>;
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "96.5" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    expect(toastMock).toHaveBeenCalledWith(expect.stringMatching(/network down/), "error");
    expect(refreshMock).not.toHaveBeenCalled();
  });

  it("shows 'Saving…' + disables date picker + all 8 number inputs while api in flight", async () => {
    let resolveSave!: (v: WeeklyClinicalRowOut[]) => void;
    saveWeeklyClinicalMock.mockReturnValue(
      new Promise<WeeklyClinicalRowOut[]>((r) => {
        resolveSave = r;
      }),
    );

    render(<WeeklyClinicalForm initialWeekEnding={LAST_SUNDAY} initialRows={[]} />);

    const numberInputs = document.querySelectorAll(
      'input[type="number"]',
    ) as NodeListOf<HTMLInputElement>;
    fireEvent.change(numberInputs[0] as HTMLInputElement, { target: { value: "96.5" } });

    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    expect(screen.getByRole("button", { name: /Saving/i })).toBeDisabled();
    expect(document.querySelector('input[type="date"]')).toBeDisabled();
    // All 8 number inputs disabled
    for (const inp of numberInputs) {
      expect(inp).toBeDisabled();
    }

    await act(async () => {
      resolveSave([]);
    });
  });
});
