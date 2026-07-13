// @vitest-environment happy-dom
//
// DailyCensusForm — client component, 210 LOC, the daily entry surface
// Crystal uses every morning. Covers the full lifecycle:
//   - initial state derivation from server rows
//   - per-input draft updates + filled-state styling
//   - save button enable/disable + saving-pill copy
//   - client-side validation (census range, empty submit)
//   - happy-path save -> api + toast.success + router.refresh
//   - server response merge back into drafts (source/updated_at)
//   - api error -> toast.error
//   - empty initial state -> 'Could not load site list' hint
//   - status badge branches: manual / pdf_extract / null

import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const saveDailyCensusMock = vi.fn();
const refreshMock = vi.fn();
const toastMock = vi.fn();

vi.mock("@/lib/api-browser", () => ({
  useApiBrowser: () => ({
    saveDailyCensus: (...args: unknown[]) => saveDailyCensusMock(...args),
  }),
}));

vi.mock("@/components/Toast", () => ({
  toast: (...args: unknown[]) => toastMock(...args),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

import type { DailyEntryOut } from "@/lib/api-browser";

import { DailyCensusForm } from "@/app/daily-census/DailyCensusForm";

function row(overrides: Partial<DailyEntryOut> = {}): DailyEntryOut {
  return {
    site_id: 1,
    site_name: "Westside Regional",
    state: "FL",
    entry_date: "2026-05-14",
    census: null,
    open_shifts: 0,
    entered_by_upn: null,
    source: null,
    notes: null,
    updated_at: null,
    ...overrides,
  } as DailyEntryOut;
}

describe("DailyCensusForm", () => {
  beforeEach(() => {
    saveDailyCensusMock.mockReset();
    refreshMock.mockReset();
    toastMock.mockReset();
  });

  it("renders empty-state hint when initialRows is empty", () => {
    render(<DailyCensusForm initialRows={[]} />);
    expect(screen.getByText(/Could not load site list/)).toBeInTheDocument();
    expect(screen.getByText(/masters.sites/)).toBeInTheDocument();
  });

  it("renders one row per site with name + state + census input + open-shifts input", () => {
    render(
      <DailyCensusForm
        initialRows={[
          row({ site_id: 1, site_name: "Westside Regional", state: "FL" }),
          row({ site_id: 2, site_name: "Woodmont", state: "FL" }),
        ]}
      />,
    );

    expect(screen.getByText("Westside Regional")).toBeInTheDocument();
    expect(screen.getByText("Woodmont")).toBeInTheDocument();
    expect(screen.getAllByText("FL").length).toBe(2);
  });

  it("renders header copy with entered/total count (0 of N when nothing filled)", () => {
    render(
      <DailyCensusForm
        initialRows={[row({ site_id: 1 }), row({ site_id: 2 }), row({ site_id: 3 })]}
      />,
    );

    // Header text format: 'YYYY-MM-DD · 0 of 3 sites entered'
    expect(screen.getByText(/0 of 3 sites entered/)).toBeInTheDocument();
  });

  it("increments the entered count as the user types census values", () => {
    render(<DailyCensusForm initialRows={[row({ site_id: 1 }), row({ site_id: 2 })]} />);

    const inputs = screen.getAllByPlaceholderText("—");
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "100" } });

    expect(screen.getByText(/1 of 2 sites entered/)).toBeInTheDocument();
  });

  it("applies emerald 'filled' styling to census input once a value is typed", () => {
    render(<DailyCensusForm initialRows={[row({ site_id: 1 })]} />);

    const input = screen.getByPlaceholderText("—") as HTMLInputElement;
    expect(input.className).toContain("border-slate-300");

    fireEvent.change(input, { target: { value: "200" } });

    expect(input.className).toContain("border-emerald-300");
    expect(input.className).toContain("bg-emerald-50");
  });

  it("disables the save button when no rows are loaded (initialRows=[])", () => {
    render(<DailyCensusForm initialRows={[]} />);
    const button = screen.getByRole("button", { name: /Save/i });
    expect(button).toBeDisabled();
  });

  it("save button is enabled by default when rows are loaded (even with nothing filled)", () => {
    // Server-side validation handles the empty-submit case; the button stays enabled.
    render(<DailyCensusForm initialRows={[row()]} />);
    const button = screen.getByRole("button", { name: /Save/i });
    expect(button).not.toBeDisabled();
  });

  it("shows 'Saving…' label while the api call is in flight + disables inputs", async () => {
    let resolveSave!: (v: unknown[]) => void;
    saveDailyCensusMock.mockReturnValue(
      new Promise<unknown[]>((r) => {
        resolveSave = r;
      }),
    );

    render(<DailyCensusForm initialRows={[row({ site_id: 1 })]} />);

    const input = screen.getByPlaceholderText("—") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "150" } });
    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    // Mid-flight: button shows 'Saving…' and disabled, inputs disabled
    expect(screen.getByRole("button", { name: /Saving/i })).toBeDisabled();
    expect(input).toBeDisabled();

    // Resolve to clean up
    await act(async () => {
      resolveSave([
        row({ site_id: 1, census: 150, source: "manual", updated_at: "2026-05-14T12:00Z" }),
      ]);
    });
  });

  it("rejects empty submit with a toast.error and does NOT call the api", () => {
    render(<DailyCensusForm initialRows={[row()]} />);
    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    expect(toastMock).toHaveBeenCalledWith(expect.stringMatching(/Nothing to save/), "error");
    expect(saveDailyCensusMock).not.toHaveBeenCalled();
  });

  it("rejects out-of-range census (negative) with a toast.error", () => {
    render(<DailyCensusForm initialRows={[row({ site_id: 1 })]} />);

    const input = screen.getByPlaceholderText("—") as HTMLInputElement;
    // type='number' clamps min=0 in some browsers; force the value to bypass via change
    fireEvent.change(input, { target: { value: "-5" } });
    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    expect(toastMock).toHaveBeenCalledWith(expect.stringMatching(/Invalid census value/), "error");
    expect(saveDailyCensusMock).not.toHaveBeenCalled();
  });

  it("rejects out-of-range census (> 2000) with a toast.error", () => {
    render(<DailyCensusForm initialRows={[row({ site_id: 1 })]} />);

    fireEvent.change(screen.getByPlaceholderText("—"), { target: { value: "9999" } });
    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    expect(toastMock).toHaveBeenCalledWith(expect.stringMatching(/Invalid census value/), "error");
    expect(saveDailyCensusMock).not.toHaveBeenCalled();
  });

  it("filters out empty-census rows before sending — submits only filled rows", async () => {
    saveDailyCensusMock.mockResolvedValue([]);

    render(
      <DailyCensusForm
        initialRows={[
          row({ site_id: 1, site_name: "A" }),
          row({ site_id: 2, site_name: "B" }),
          row({ site_id: 3, site_name: "C" }),
        ]}
      />,
    );

    const inputs = screen.getAllByPlaceholderText("—");
    // Fill only sites 1 and 3
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "100" } });
    fireEvent.change(inputs[2] as HTMLInputElement, { target: { value: "300" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    expect(saveDailyCensusMock).toHaveBeenCalledTimes(1);
    const payload = saveDailyCensusMock.mock.calls[0]?.[0] as {
      entry_date: string;
      rows: Array<{ site_id: number; census: number }>;
    };
    expect(payload.rows.map((r) => r.site_id)).toEqual([1, 3]);
    expect(payload.rows.map((r) => r.census)).toEqual([100, 300]);
  });

  it("defaults open_shifts to 0 when the field is cleared by the user", async () => {
    saveDailyCensusMock.mockResolvedValue([]);

    render(<DailyCensusForm initialRows={[row({ site_id: 1, open_shifts: 0 })]} />);

    // Clear the open-shifts field
    const openShiftsInput = screen.getAllByRole("spinbutton")[1] as HTMLInputElement;
    fireEvent.change(openShiftsInput, { target: { value: "" } });
    fireEvent.change(screen.getByPlaceholderText("—"), { target: { value: "100" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    const payload = saveDailyCensusMock.mock.calls[0]?.[0] as {
      rows: Array<{ open_shifts: number }>;
    };
    expect(payload.rows[0]?.open_shifts).toBe(0);
  });

  it("sends notes as null when the field is empty (server expects null, not '')", async () => {
    saveDailyCensusMock.mockResolvedValue([]);

    render(<DailyCensusForm initialRows={[row({ site_id: 1 })]} />);

    fireEvent.change(screen.getByPlaceholderText("—"), { target: { value: "100" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    const payload = saveDailyCensusMock.mock.calls[0]?.[0] as {
      rows: Array<{ notes: string | null }>;
    };
    expect(payload.rows[0]?.notes).toBeNull();
  });

  it("on success: toast.success with count, merge server response, router.refresh()", async () => {
    const saved = [
      row({
        site_id: 1,
        census: 100,
        source: "manual",
        updated_at: "2026-05-14T12:00:00Z",
      }),
    ];
    saveDailyCensusMock.mockResolvedValue(saved);

    render(<DailyCensusForm initialRows={[row({ site_id: 1 })]} />);

    fireEvent.change(screen.getByPlaceholderText("—"), { target: { value: "100" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    expect(toastMock).toHaveBeenCalledWith(expect.stringMatching(/Saved 1 site/), "success");
    expect(refreshMock).toHaveBeenCalledTimes(1);

    // After merge: status badge for site_id=1 flipped to '✓ Manual'
    expect(screen.getByText("✓ Manual")).toBeInTheDocument();
  });

  it("on success with multiple sites: pluralized 'sites' in toast", async () => {
    const saved = [row({ site_id: 1, census: 100 }), row({ site_id: 2, census: 200 })];
    saveDailyCensusMock.mockResolvedValue(saved);

    render(<DailyCensusForm initialRows={[row({ site_id: 1 }), row({ site_id: 2 })]} />);

    const inputs = screen.getAllByPlaceholderText("—");
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: "100" } });
    fireEvent.change(inputs[1] as HTMLInputElement, { target: { value: "200" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    expect(toastMock).toHaveBeenCalledWith(expect.stringMatching(/Saved 2 sites\./), "success");
  });

  it("on api error: toast.error with the error message + does not refresh", async () => {
    saveDailyCensusMock.mockRejectedValue(new Error("network down"));

    render(<DailyCensusForm initialRows={[row({ site_id: 1 })]} />);

    fireEvent.change(screen.getByPlaceholderText("—"), { target: { value: "100" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Save/i }));
    });

    expect(toastMock).toHaveBeenCalledWith(expect.stringMatching(/network down/), "error");
    expect(refreshMock).not.toHaveBeenCalled();
  });

  it("renders status badge branches: '✓ Manual' / 'PDF' / '—'", () => {
    render(
      <DailyCensusForm
        initialRows={[
          row({ site_id: 1, source: "manual", census: 100 }),
          row({ site_id: 2, source: "pdf_extract", census: 200 }),
          row({ site_id: 3, source: null, census: null }),
        ]}
      />,
    );

    expect(screen.getByText("✓ Manual")).toBeInTheDocument();
    expect(screen.getByText("PDF")).toBeInTheDocument();
    // The '—' appears as both the input placeholder (3 inputs) AND the status cell.
    // Use getAllByText and assert >= 1.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1);
  });
});
