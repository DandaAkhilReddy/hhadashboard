// @vitest-environment happy-dom
//
// UploadDropZone — the drag-and-drop entry surface for vendor files
// (census PDF, finance/clinical/hr Excel). Covers four distinct concerns:
//   1. Filename → type inference regexes (4 file types × extensions)
//   2. Staging accumulator: add/remove/update-type, allReady gate
//   3. Submit loop: per-file try/catch, success counter, toast pluralization,
//      list refetch + router.refresh on any success
//   4. 30-second polling of listUploads (fake-timer driven) + table render
//      with the 5-state STATUS_LABEL switch + retry_count + error_message

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const stageUploadMock = vi.fn();
const listUploadsMock = vi.fn();
const toastMock = vi.fn();
const refreshMock = vi.fn();

vi.mock("@/lib/api-browser", async () => {
  // Re-export the real type module unchanged; only override useApiBrowser.
  const actual = await vi.importActual<typeof import("@/lib/api-browser")>("@/lib/api-browser");
  return {
    ...actual,
    useApiBrowser: () => ({
      stageUpload: (...args: unknown[]) => stageUploadMock(...args),
      listUploads: (...args: unknown[]) => listUploadsMock(...args),
    }),
  };
});

vi.mock("@/components/Toast", () => ({
  toast: (...args: unknown[]) => toastMock(...args),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

// FileDrop passthrough — surfaces an "Open picker" button that the test
// uses to dispatch synthetic files. The real DnD surface is covered by
// the dedicated FileDrop test file.
vi.mock("@/components/FileDrop", () => ({
  FileDrop: ({ onFiles, disabled }: { onFiles: (files: File[]) => void; disabled?: boolean }) => (
    <button
      type="button"
      data-testid="filedrop-stub"
      disabled={disabled}
      onClick={() => {
        const stash = (window as unknown as { __filedropFiles?: File[] }).__filedropFiles ?? [];
        onFiles(stash);
      }}
    >
      filedrop
    </button>
  ),
}));

import type { UploadRow } from "@/lib/api-browser";

import { UploadDropZone } from "@/app/uploads/UploadDropZone";

function fakeFile(name: string, sizeBytes = 1024, type = "application/pdf"): File {
  return new File([new Uint8Array(sizeBytes)], name, { type });
}

function dropFiles(files: File[]): void {
  (window as unknown as { __filedropFiles: File[] }).__filedropFiles = files;
  fireEvent.click(screen.getByTestId("filedrop-stub"));
}

function uploadRow(overrides: Partial<UploadRow> = {}): UploadRow {
  return {
    id: 1,
    uploaded_by_upn: "crystal@hhamedicine.com",
    uploaded_at: new Date().toISOString(),
    file_type: "census_pdf",
    original_filename: "census-westside-2026-05-13.pdf",
    blob_name: "uploads/1.pdf",
    size_bytes: 2_048_000,
    sha256: "a".repeat(64),
    status: "uploaded",
    processing_started_at: null,
    processing_finished_at: null,
    rows_written: null,
    error_message: null,
    retry_count: 0,
    ...overrides,
  };
}

describe("UploadDropZone — inference + staging", () => {
  beforeEach(() => {
    stageUploadMock.mockReset();
    listUploadsMock.mockReset();
    toastMock.mockReset();
    refreshMock.mockReset();
  });

  it("auto-detects census PDF and marks confidence", () => {
    render(<UploadDropZone initialUploads={[]} />);
    dropFiles([fakeFile("Census-Westside-2026-05-13.pdf")]);

    // The auto-detected select renders with the emerald confidence ring.
    const select = screen.getByDisplayValue(/Census PDF/i);
    expect(select.className).toContain("emerald");
  });

  it.each([
    ["FL-Collections-2026-04.xlsx", "Finance (Excel)"],
    ["FL-AR_aging-2026-04.xlsx", "Finance (Excel)"],
    ["site_revenue_summary.xlsx", "Finance (Excel)"],
    ["clinical-audit-week18.xlsx", "Clinical audit (Excel)"],
    ["HP_DC_summary.xlsx", "Clinical audit (Excel)"],
    ["hr-headcount-week18.xlsx", "HR export (Excel)"],
    ["turnover-2026-04.xlsx", "HR export (Excel)"],
    ["payroll_export.csv", "HR export (Excel)"],
  ])("infers %s as %s", (filename, expectedLabel) => {
    render(<UploadDropZone initialUploads={[]} />);
    dropFiles([fakeFile(filename)]);
    expect(screen.getByDisplayValue(expectedLabel)).toBeInTheDocument();
  });

  it("falls back to 'unknown' for unrecognized filenames and renders amber tone", () => {
    render(<UploadDropZone initialUploads={[]} />);
    dropFiles([fakeFile("random-file.pdf")]);

    // Locate the row's select via the disabled-default option; the select
    // value === "unknown" so its display matches the placeholder option.
    const select = screen.getByDisplayValue(/Pick type/i);
    expect(select.className).toContain("amber");
  });

  it("appends files across multiple drops (cumulative staged list)", () => {
    render(<UploadDropZone initialUploads={[]} />);
    dropFiles([fakeFile("Census1.pdf")]);
    dropFiles([fakeFile("Census2.pdf")]);

    expect(screen.getByText(/Staged \(2\)/)).toBeInTheDocument();
  });

  it("Remove ✕ filters the staged row by localId", () => {
    render(<UploadDropZone initialUploads={[]} />);
    dropFiles([fakeFile("Census1.pdf"), fakeFile("Census2.pdf")]);
    expect(screen.getByText(/Staged \(2\)/)).toBeInTheDocument();

    const removes = screen.getAllByRole("button", { name: "Remove" });
    fireEvent.click(removes[0] as HTMLElement);

    expect(screen.getByText(/Staged \(1\)/)).toBeInTheDocument();
  });

  it("changing the type select clears the auto-detected confidence ring", () => {
    render(<UploadDropZone initialUploads={[]} />);
    dropFiles([fakeFile("Census-westside.pdf")]);

    const select = screen.getByDisplayValue(/Census PDF/i) as HTMLSelectElement;
    expect(select.className).toContain("emerald");

    fireEvent.change(select, { target: { value: "finance_xlsx" } });
    // After manual override, the className loses emerald — it becomes neutral slate.
    expect(select.className).toContain("slate");
    expect(select.className).not.toContain("emerald");
  });
});

describe("UploadDropZone — allReady gate + Upload button", () => {
  beforeEach(() => {
    stageUploadMock.mockReset();
    listUploadsMock.mockReset();
    toastMock.mockReset();
    refreshMock.mockReset();
  });

  it("disables Upload when no files staged (button absent until staging)", () => {
    render(<UploadDropZone initialUploads={[]} />);
    expect(screen.queryByRole("button", { name: /Upload \d file/i })).toBeNull();
  });

  it("disables Upload when any staged row has type='unknown'", () => {
    render(<UploadDropZone initialUploads={[]} />);
    dropFiles([fakeFile("unknown-name.pdf")]);

    const btn = screen.getByRole("button", { name: /Upload 1 file/i });
    expect(btn).toBeDisabled();
    expect(screen.getByText(/Pick a type for each file/i)).toBeInTheDocument();
  });

  it("enables Upload once every staged row has a known type", () => {
    render(<UploadDropZone initialUploads={[]} />);
    dropFiles([fakeFile("Census-westside.pdf")]);

    const btn = screen.getByRole("button", { name: /Upload 1 file/i });
    expect(btn).not.toBeDisabled();
    expect(screen.getByText(/Ready to upload/i)).toBeInTheDocument();
  });

  it("pluralizes the Upload button label (1 file / N files)", () => {
    render(<UploadDropZone initialUploads={[]} />);
    dropFiles([fakeFile("Census1.pdf")]);
    expect(screen.getByRole("button", { name: "Upload 1 file" })).toBeInTheDocument();

    dropFiles([fakeFile("Census2.pdf")]);
    expect(screen.getByRole("button", { name: "Upload 2 files" })).toBeInTheDocument();
  });
});

describe("UploadDropZone — submit loop", () => {
  beforeEach(() => {
    stageUploadMock.mockReset();
    listUploadsMock.mockReset();
    toastMock.mockReset();
    refreshMock.mockReset();
  });

  it("uploads all staged files, shows pluralized toast, clears staged, refreshes router", async () => {
    stageUploadMock.mockResolvedValue({ id: 1, status: "uploaded", file_type: "census_pdf" });
    listUploadsMock.mockResolvedValue([]);

    render(<UploadDropZone initialUploads={[]} />);
    dropFiles([fakeFile("Census1.pdf"), fakeFile("Census2.pdf")]);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Upload 2 files" }));
    });

    expect(stageUploadMock).toHaveBeenCalledTimes(2);
    expect(toastMock).toHaveBeenCalledWith(
      expect.stringMatching(/2 file\(s\) uploaded\./),
      "success",
    );
    expect(refreshMock).toHaveBeenCalledTimes(1);
    // Staged section is gone after success
    expect(screen.queryByText(/Staged \(/)).toBeNull();
  });

  it("on per-file failure: emits an error toast for that file and continues the rest", async () => {
    stageUploadMock
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({ id: 2, status: "uploaded", file_type: "census_pdf" });
    listUploadsMock.mockResolvedValue([]);

    render(<UploadDropZone initialUploads={[]} />);
    dropFiles([fakeFile("Census1.pdf"), fakeFile("Census2.pdf")]);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Upload 2 files" }));
    });

    expect(stageUploadMock).toHaveBeenCalledTimes(2);
    expect(toastMock).toHaveBeenCalledWith("Upload failed: Census1.pdf", "error");
    // 1 succeeded -> pluralized success toast and router.refresh fire
    expect(toastMock).toHaveBeenCalledWith(
      expect.stringMatching(/1 file\(s\) uploaded\./),
      "success",
    );
    expect(refreshMock).toHaveBeenCalledTimes(1);
  });

  it("on zero successes: no router.refresh, no success toast, staged stays", async () => {
    stageUploadMock.mockRejectedValue(new Error("auth"));
    listUploadsMock.mockResolvedValue([]);

    render(<UploadDropZone initialUploads={[]} />);
    dropFiles([fakeFile("Census1.pdf")]);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Upload 1 file" }));
    });

    expect(toastMock).toHaveBeenCalledWith("Upload failed: Census1.pdf", "error");
    expect(refreshMock).not.toHaveBeenCalled();
    // Staged row survives
    expect(screen.getByText(/Staged \(1\)/)).toBeInTheDocument();
  });

  it("silently swallows a listUploads failure during post-success refresh", async () => {
    stageUploadMock.mockResolvedValue({ id: 1, status: "uploaded", file_type: "census_pdf" });
    listUploadsMock.mockRejectedValue(new Error("network blip"));

    render(<UploadDropZone initialUploads={[]} />);
    dropFiles([fakeFile("Census1.pdf")]);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Upload 1 file" }));
    });

    // Success toast and refresh still fire — listUploads catch is silent.
    expect(toastMock).toHaveBeenCalledWith(
      expect.stringMatching(/1 file\(s\) uploaded\./),
      "success",
    );
    expect(refreshMock).toHaveBeenCalledTimes(1);
  });
});

describe("UploadDropZone — Recent uploads table", () => {
  beforeEach(() => {
    stageUploadMock.mockReset();
    listUploadsMock.mockReset();
    toastMock.mockReset();
    refreshMock.mockReset();
  });

  it("renders the empty-state copy when initialUploads is []", () => {
    render(<UploadDropZone initialUploads={[]} />);
    expect(screen.getByText(/No uploads yet/i)).toBeInTheDocument();
  });

  it.each([
    ["uploaded", /Queued/i],
    ["processing", /Processing/i],
    ["processed", /Processed/i],
    ["error", /Error/i],
    ["expired", /Expired/i],
  ] as const)("renders the %s status badge", (status, labelRegex) => {
    render(
      <UploadDropZone
        initialUploads={[uploadRow({ id: 1, status, original_filename: `f-${status}.pdf` })]}
      />,
    );
    // getAllByText: RTL cleanup between it.each iterations is occasionally
    // delayed; assert the badge exists at least once rather than exactly
    // once (the equivalent guard from the operations-detail page tests).
    expect(screen.getAllByText(labelRegex).length).toBeGreaterThan(0);
  });

  it("shows the error_message line only when status='error' AND error_message is set", () => {
    render(
      <UploadDropZone
        initialUploads={[
          uploadRow({
            id: 1,
            status: "error",
            original_filename: "bad.pdf",
            error_message: "schema drift in row 17",
          }),
        ]}
      />,
    );
    expect(screen.getByText(/schema drift in row 17/)).toBeInTheDocument();
  });

  it("does NOT show error_message when status is processed (even if message present)", () => {
    render(
      <UploadDropZone
        initialUploads={[
          uploadRow({
            id: 1,
            status: "processed",
            error_message: "stale - should not render",
          }),
        ]}
      />,
    );
    expect(screen.queryByText(/stale - should not render/)).toBeNull();
  });

  it("shows the retry counter when retry_count > 0 AND status != processed", () => {
    render(
      <UploadDropZone
        initialUploads={[
          uploadRow({ id: 1, status: "uploaded", retry_count: 2, original_filename: "r.pdf" }),
        ]}
      />,
    );
    expect(screen.getByText(/retry 2\/3/)).toBeInTheDocument();
  });

  it("suppresses the retry counter once status='processed'", () => {
    render(
      <UploadDropZone
        initialUploads={[
          uploadRow({ id: 1, status: "processed", retry_count: 3, original_filename: "r.pdf" }),
        ]}
      />,
    );
    expect(screen.queryByText(/retry 3\/3/)).toBeNull();
  });

  it("renders em-dash when rows_written is null", () => {
    render(
      <UploadDropZone
        initialUploads={[uploadRow({ id: 1, rows_written: null, original_filename: "nul.pdf" })]}
      />,
    );
    // The Rows column emits "—" when null.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("renders a row's rows_written number when present", () => {
    render(
      <UploadDropZone
        initialUploads={[uploadRow({ id: 1, rows_written: 42, original_filename: "ok.pdf" })]}
      />,
    );
    expect(screen.getByText("42")).toBeInTheDocument();
  });
});

describe("UploadDropZone — polling timer", () => {
  beforeEach(() => {
    stageUploadMock.mockReset();
    listUploadsMock.mockReset();
    toastMock.mockReset();
    refreshMock.mockReset();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls listUploads every 30 seconds and merges the fresh response", async () => {
    listUploadsMock.mockResolvedValue([
      uploadRow({ id: 99, status: "processed", original_filename: "post-poll.pdf" }),
    ]);

    render(<UploadDropZone initialUploads={[]} />);

    await act(async () => {
      vi.advanceTimersByTime(30_000);
      await Promise.resolve(); // let the fetch promise settle
    });

    expect(listUploadsMock).toHaveBeenCalledTimes(1);
    expect(screen.getByText("post-poll.pdf")).toBeInTheDocument();
  });

  it("absorbs poll failures silently (next tick retries)", async () => {
    listUploadsMock.mockRejectedValue(new Error("transient"));

    render(<UploadDropZone initialUploads={[uploadRow({ id: 1, original_filename: "a.pdf" })]} />);

    await act(async () => {
      vi.advanceTimersByTime(30_000);
      await Promise.resolve();
    });

    // No toast, no console error, no router.refresh — the catch is silent.
    expect(toastMock).not.toHaveBeenCalled();
    // Original row still visible.
    expect(screen.getByText("a.pdf")).toBeInTheDocument();
  });
});
