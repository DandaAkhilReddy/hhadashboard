// @vitest-environment happy-dom
//
// SiteCensusForm — the inline entry form on `/operations/[siteId]`. Smaller
// than the dashboard-level DailyCensusForm: a single site, two number
// fields + notes, range validation, and a router.refresh on success.

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

import { SiteCensusForm } from "@/app/operations/[siteId]/SiteCensusForm";

describe("SiteCensusForm — hydration", () => {
  beforeEach(() => {
    saveDailyCensusMock.mockReset();
    refreshMock.mockReset();
    toastMock.mockReset();
  });

  it("renders empty strings when initialCensus + initialOpenShifts are null", () => {
    render(
      <SiteCensusForm
        siteId={42}
        initialCensus={null}
        initialOpenShifts={null}
        initialNotes={null}
      />,
    );

    const inputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    expect(inputs.length).toBe(2);
    expect(inputs[0]?.value).toBe("");
    expect(inputs[1]?.value).toBe("");
  });

  it("hydrates census and openShifts from non-null props", () => {
    render(
      <SiteCensusForm siteId={42} initialCensus={198} initialOpenShifts={2} initialNotes={null} />,
    );

    expect(screen.getByDisplayValue("198")).toBeInTheDocument();
    expect(screen.getByDisplayValue("2")).toBeInTheDocument();
  });

  it("hydrates notes from a non-null prop", () => {
    render(
      <SiteCensusForm
        siteId={42}
        initialCensus={null}
        initialOpenShifts={null}
        initialNotes="surge unit closed for cleaning"
      />,
    );

    expect(screen.getByDisplayValue("surge unit closed for cleaning")).toBeInTheDocument();
  });

  it("hydrates notes as empty string when initialNotes is null", () => {
    render(
      <SiteCensusForm
        siteId={42}
        initialCensus={null}
        initialOpenShifts={null}
        initialNotes={null}
      />,
    );

    const notesInput = screen.getByRole("textbox") as HTMLInputElement;
    expect(notesInput.value).toBe("");
  });
});

describe("SiteCensusForm — validation", () => {
  beforeEach(() => {
    saveDailyCensusMock.mockReset();
    refreshMock.mockReset();
    toastMock.mockReset();
  });

  it("rejects empty census with an error toast (NaN parse path)", async () => {
    render(
      <SiteCensusForm
        siteId={42}
        initialCensus={null}
        initialOpenShifts={null}
        initialNotes={null}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    expect(saveDailyCensusMock).not.toHaveBeenCalled();
    expect(toastMock).toHaveBeenCalledWith(
      expect.stringMatching(/Census must be between 0 and 2000/),
      "error",
    );
  });

  it("rejects census > 2000", async () => {
    render(
      <SiteCensusForm siteId={42} initialCensus={2001} initialOpenShifts={0} initialNotes={null} />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    expect(saveDailyCensusMock).not.toHaveBeenCalled();
    expect(toastMock).toHaveBeenCalledWith(
      expect.stringMatching(/Census must be between 0 and 2000/),
      "error",
    );
  });

  it("accepts census = 0 (lower boundary inclusive)", async () => {
    saveDailyCensusMock.mockResolvedValue(undefined);

    render(
      <SiteCensusForm siteId={42} initialCensus={0} initialOpenShifts={0} initialNotes={null} />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    expect(saveDailyCensusMock).toHaveBeenCalledTimes(1);
  });

  it("accepts census = 2000 (upper boundary inclusive)", async () => {
    saveDailyCensusMock.mockResolvedValue(undefined);

    render(
      <SiteCensusForm siteId={42} initialCensus={2000} initialOpenShifts={0} initialNotes={null} />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    expect(saveDailyCensusMock).toHaveBeenCalledTimes(1);
  });

  it("rejects open_shifts > 50", async () => {
    render(
      <SiteCensusForm siteId={42} initialCensus={100} initialOpenShifts={51} initialNotes={null} />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    expect(saveDailyCensusMock).not.toHaveBeenCalled();
    expect(toastMock).toHaveBeenCalledWith(
      expect.stringMatching(/Open shifts must be between 0 and 50/),
      "error",
    );
  });

  it("defaults open_shifts to 0 when the input is empty (trim path)", async () => {
    saveDailyCensusMock.mockResolvedValue(undefined);

    render(
      <SiteCensusForm
        siteId={42}
        initialCensus={100}
        initialOpenShifts={null}
        initialNotes={null}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    const sent = saveDailyCensusMock.mock.calls[0]?.[0] as {
      rows: Array<{ open_shifts: number }>;
    };
    expect(sent.rows[0]?.open_shifts).toBe(0);
  });
});

describe("SiteCensusForm — save flow", () => {
  beforeEach(() => {
    saveDailyCensusMock.mockReset();
    refreshMock.mockReset();
    toastMock.mockReset();
  });

  it("sends entry_date as today's ISO YYYY-MM-DD + the row shape", async () => {
    saveDailyCensusMock.mockResolvedValue(undefined);

    render(
      <SiteCensusForm
        siteId={42}
        initialCensus={198}
        initialOpenShifts={2}
        initialNotes="surge unit closed"
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    expect(saveDailyCensusMock).toHaveBeenCalledTimes(1);
    const arg = saveDailyCensusMock.mock.calls[0]?.[0] as {
      entry_date: string;
      rows: Array<{ site_id: number; census: number; open_shifts: number; notes: string | null }>;
    };
    expect(arg.entry_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(arg.rows.length).toBe(1);
    expect(arg.rows[0]?.site_id).toBe(42);
    expect(arg.rows[0]?.census).toBe(198);
    expect(arg.rows[0]?.open_shifts).toBe(2);
    expect(arg.rows[0]?.notes).toBe("surge unit closed");
  });

  it("maps empty notes -> null in the payload", async () => {
    saveDailyCensusMock.mockResolvedValue(undefined);

    render(
      <SiteCensusForm siteId={42} initialCensus={100} initialOpenShifts={0} initialNotes={null} />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    const arg = saveDailyCensusMock.mock.calls[0]?.[0] as {
      rows: Array<{ notes: string | null }>;
    };
    expect(arg.rows[0]?.notes).toBeNull();
  });

  it("on success: toast + router.refresh", async () => {
    saveDailyCensusMock.mockResolvedValue(undefined);

    render(
      <SiteCensusForm siteId={42} initialCensus={100} initialOpenShifts={0} initialNotes={null} />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    expect(toastMock).toHaveBeenCalledWith("Saved.", "success");
    expect(refreshMock).toHaveBeenCalledTimes(1);
  });

  it("on save failure: error toast carrying (err as Error).message; no router.refresh", async () => {
    saveDailyCensusMock.mockRejectedValue(new Error("auth expired"));

    render(
      <SiteCensusForm siteId={42} initialCensus={100} initialOpenShifts={0} initialNotes={null} />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    });

    expect(toastMock).toHaveBeenCalledWith(
      expect.stringMatching(/Save failed: auth expired/),
      "error",
    );
    expect(refreshMock).not.toHaveBeenCalled();
  });

  it("disables inputs + button + shows 'Saving...' while save is in flight", async () => {
    let resolveSave!: () => void;
    saveDailyCensusMock.mockImplementation(
      () =>
        new Promise<void>((res) => {
          resolveSave = res;
        }),
    );

    render(
      <SiteCensusForm siteId={42} initialCensus={100} initialOpenShifts={0} initialNotes={null} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));

    expect(screen.getByRole("button", { name: /Saving/ })).toBeDisabled();
    const inputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    expect(inputs[0]).toBeDisabled();

    await act(async () => {
      resolveSave();
    });
  });
});
