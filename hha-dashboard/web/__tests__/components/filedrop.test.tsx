// @vitest-environment happy-dom
//
// FileDrop interaction tests — drop, click, keyboard, file-size guard,
// disabled state. RTL + happy-dom; constructs File objects directly so
// no fs/network involved.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FileDrop } from "@/components/FileDrop";

function makeFile(name: string, sizeBytes: number, type = "application/pdf"): File {
  // happy-dom's File constructor honors `size` from the byte content. Build
  // a Blob-sized array buffer so f.size matches what we want to assert on.
  const buf = new Uint8Array(sizeBytes);
  return new File([buf], name, { type });
}

describe("FileDrop", () => {
  it("renders the documented helper copy + extension hint", () => {
    render(<FileDrop onFiles={() => {}} />);
    expect(screen.getByText(/Drop files here or click to browse/i)).toBeInTheDocument();
    expect(screen.getByText(/PDFs, Excel/i)).toBeInTheDocument();
    expect(screen.getByText(/Max 25 MB per file/i)).toBeInTheDocument();
  });

  it("uses caller-provided maxBytes in the helper copy", () => {
    render(<FileDrop onFiles={() => {}} maxBytes={10 * 1024 * 1024} />);
    expect(screen.getByText(/Max 10 MB per file/i)).toBeInTheDocument();
  });

  it("forwards dropped files under maxBytes to the onFiles callback", () => {
    const onFiles = vi.fn();
    render(<FileDrop onFiles={onFiles} maxBytes={5 * 1024 * 1024} />);

    const file = makeFile("ok.pdf", 1024);
    const dropZone = screen.getByRole("button");
    fireEvent.drop(dropZone, {
      dataTransfer: { files: [file] },
    });

    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles).toHaveBeenCalledWith([file]);
  });

  it("rejects oversized files with the documented error string + name list", () => {
    const onFiles = vi.fn();
    render(<FileDrop onFiles={onFiles} maxBytes={1024} />);

    const big = makeFile("huge.pdf", 4096);
    fireEvent.drop(screen.getByRole("button"), {
      dataTransfer: { files: [big] },
    });

    expect(onFiles).not.toHaveBeenCalled();
    expect(screen.getByText(/1 file\(s\) exceed 0 MB limit: huge.pdf/)).toBeInTheDocument();
  });

  it("forwards good files AND surfaces error for the bad ones in the same drop", () => {
    const onFiles = vi.fn();
    render(<FileDrop onFiles={onFiles} maxBytes={2048} />);

    const ok = makeFile("ok.pdf", 1024);
    const big = makeFile("huge.pdf", 4096);
    fireEvent.drop(screen.getByRole("button"), {
      dataTransfer: { files: [ok, big] },
    });

    expect(onFiles).toHaveBeenCalledWith([ok]);
    expect(screen.getByText(/1 file\(s\) exceed/)).toBeInTheDocument();
  });

  it("clears the previous error on the next clean drop", () => {
    const onFiles = vi.fn();
    render(<FileDrop onFiles={onFiles} maxBytes={2048} />);
    const dropZone = screen.getByRole("button");

    // First drop: oversized → error appears
    fireEvent.drop(dropZone, {
      dataTransfer: { files: [makeFile("big.pdf", 4096)] },
    });
    expect(screen.getByText(/exceed/)).toBeInTheDocument();

    // Second drop: under limit → error cleared
    fireEvent.drop(dropZone, {
      dataTransfer: { files: [makeFile("ok.pdf", 1024)] },
    });
    expect(screen.queryByText(/exceed/)).toBeNull();
  });

  it("toggles drag-over highlight class on dragover/dragleave", () => {
    render(<FileDrop onFiles={() => {}} />);
    const dropZone = screen.getByRole("button");

    expect(dropZone.className).not.toContain("border-indigo-500");

    fireEvent.dragOver(dropZone);
    expect(dropZone.className).toContain("border-indigo-500");
    expect(dropZone.className).toContain("bg-indigo-50");

    fireEvent.dragLeave(dropZone);
    expect(dropZone.className).not.toContain("border-indigo-500");
  });

  it("clicks the hidden file input when the button is clicked", () => {
    const { container } = render(<FileDrop onFiles={() => {}} />);
    const hiddenInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const inputClickSpy = vi.spyOn(hiddenInput, "click");

    fireEvent.click(screen.getByRole("button"));

    expect(inputClickSpy).toHaveBeenCalledTimes(1);
  });

  it("clicks the hidden file input on Enter and Space keys", () => {
    const { container } = render(<FileDrop onFiles={() => {}} />);
    const hiddenInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const inputClickSpy = vi.spyOn(hiddenInput, "click");

    fireEvent.keyDown(screen.getByRole("button"), { key: "Enter" });
    expect(inputClickSpy).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(screen.getByRole("button"), { key: " " });
    expect(inputClickSpy).toHaveBeenCalledTimes(2);
  });

  it("ignores other keys so accessibility tab navigation works", () => {
    const { container } = render(<FileDrop onFiles={() => {}} />);
    const hiddenInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const inputClickSpy = vi.spyOn(hiddenInput, "click");

    fireEvent.keyDown(screen.getByRole("button"), { key: "Tab" });
    fireEvent.keyDown(screen.getByRole("button"), { key: "ArrowDown" });

    expect(inputClickSpy).not.toHaveBeenCalled();
  });

  it("disabled state prevents click + drop from doing anything", () => {
    const onFiles = vi.fn();
    const { container } = render(<FileDrop onFiles={onFiles} disabled />);
    const dropZone = screen.getByRole("button");
    const hiddenInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const inputClickSpy = vi.spyOn(hiddenInput, "click");

    expect(dropZone.getAttribute("aria-disabled")).toBe("true");
    expect(dropZone.className).toContain("cursor-not-allowed");
    expect(dropZone.className).toContain("opacity-50");

    fireEvent.click(dropZone);
    fireEvent.keyDown(dropZone, { key: "Enter" });
    fireEvent.drop(dropZone, {
      dataTransfer: { files: [makeFile("ok.pdf", 100)] },
    });

    expect(inputClickSpy).not.toHaveBeenCalled();
    expect(onFiles).not.toHaveBeenCalled();
  });

  it("disabled state still skips the drag-over highlight", () => {
    render(<FileDrop onFiles={() => {}} disabled />);
    const dropZone = screen.getByRole("button");

    fireEvent.dragOver(dropZone);
    expect(dropZone.className).not.toContain("border-indigo-500");
  });

  it("forwards files selected via the hidden input onChange handler", () => {
    const onFiles = vi.fn();
    const { container } = render(<FileDrop onFiles={onFiles} maxBytes={5 * 1024 * 1024} />);
    const hiddenInput = container.querySelector('input[type="file"]') as HTMLInputElement;

    const file = makeFile("clicked.pdf", 1024);
    // Simulate a change event with files attached
    fireEvent.change(hiddenInput, { target: { files: [file] } });

    expect(onFiles).toHaveBeenCalledWith([file]);
    // input.value is reset to '' so selecting the same file twice still fires
    expect(hiddenInput.value).toBe("");
  });

  it("respects the accept + multiple props on the hidden input", () => {
    const { container } = render(
      <FileDrop onFiles={() => {}} accept=".pdf,.png" multiple={false} />,
    );
    const hiddenInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(hiddenInput.getAttribute("accept")).toBe(".pdf,.png");
    expect(hiddenInput.hasAttribute("multiple")).toBe(false);
  });

  it("uses default accept + multiple when not provided", () => {
    const { container } = render(<FileDrop onFiles={() => {}} />);
    const hiddenInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(hiddenInput.getAttribute("accept")).toBe(".pdf,.xlsx,.xls,.csv");
    expect(hiddenInput.hasAttribute("multiple")).toBe(true);
  });
});
