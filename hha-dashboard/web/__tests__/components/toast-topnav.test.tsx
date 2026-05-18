// @vitest-environment happy-dom
//
// Toast subscriber pattern + Toaster component + TopNav navigation
// rendering. TopNav has non-trivial dependencies (next/navigation,
// use-user hook) — both mocked so the tests stay in unit territory.

import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Toaster, toast } from "@/components/Toast";

// ---------- Toast / Toaster ----------

describe("Toast (subscriber-pattern + Toaster component)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders nothing when there are no toasts", () => {
    const { container } = render(<Toaster />);
    // Toaster always mounts a wrapper div; just check no toast rows
    expect(container.querySelectorAll("[class*='pointer-events-auto']").length).toBe(0);
  });

  it("renders a toast on the next render after toast() is called", () => {
    render(<Toaster />);
    act(() => {
      toast("Saved", "success");
    });
    expect(screen.getByText("Saved")).toBeInTheDocument();
    expect(screen.getByText("✓")).toBeInTheDocument();
  });

  it.each([
    ["success", "✓", "bg-emerald-50"],
    ["error", "✗", "bg-red-50"],
    ["info", "ℹ", "bg-white"],
  ] as const)("applies %s variant icon + class", (variant, icon, bgClass) => {
    // Use a unique message + flush any prior toasts so this assertion
    // only sees the current test's toast (the module-level `current`
    // array is shared across tests).
    const message = `variant-test-${variant}-${Math.random()}`;
    render(<Toaster />);
    act(() => {
      toast(message, variant);
    });
    const row = screen.getByText(message).parentElement as HTMLElement;
    expect(row.className).toContain(bgClass);
    // The icon will appear on the SAME row as our unique message.
    const icons = row.querySelectorAll("span");
    const iconSpan = Array.from(icons).find((s) => s.textContent === icon);
    expect(iconSpan).toBeDefined();
  });

  it("defaults variant to info when omitted", () => {
    const message = `default-variant-${Math.random()}`;
    render(<Toaster />);
    act(() => {
      toast(message);
    });
    const row = screen.getByText(message).parentElement as HTMLElement;
    expect(row.className).toContain("bg-white"); // info variant background
  });

  it("removes the toast after the timeout elapses", () => {
    render(<Toaster />);
    act(() => {
      toast("will-vanish", "info", 1000);
    });
    expect(screen.getByText("will-vanish")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1100);
    });

    expect(screen.queryByText("will-vanish")).toBeNull();
  });

  it("supports multiple concurrent toasts and dismisses them independently", () => {
    render(<Toaster />);
    act(() => {
      toast("first", "success", 500);
      toast("second", "error", 1500);
    });
    expect(screen.getByText("first")).toBeInTheDocument();
    expect(screen.getByText("second")).toBeInTheDocument();

    // Advance past first timeout — first gone, second still visible
    act(() => {
      vi.advanceTimersByTime(700);
    });
    expect(screen.queryByText("first")).toBeNull();
    expect(screen.getByText("second")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.queryByText("second")).toBeNull();
  });
});

// ---------- TopNav ----------

// Mock next/navigation + the auth hook BEFORE importing TopNav.
vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/"),
}));

vi.mock("@/lib/auth/use-user", () => ({
  useUser: vi.fn(() => ({ user: undefined, isLoading: true })),
}));

// next/link in app router renders an <a>. Mock with a passthrough.
vi.mock("next/link", () => ({
  __esModule: true,
  default: ({
    href,
    children,
    className,
  }: {
    href: string;
    children: React.ReactNode;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

// Imports MUST come AFTER vi.mock() declarations above so the mocked
// modules are wired before TopNav resolves them.
import { useUser } from "@/lib/auth/use-user";
import { usePathname } from "next/navigation";

import { TopNav } from "@/components/TopNav";

describe("TopNav", () => {
  beforeEach(() => {
    vi.mocked(usePathname).mockReturnValue("/");
    vi.mocked(useUser).mockReturnValue({ user: undefined, isLoading: true });
  });

  function findTabByHref(href: string): HTMLAnchorElement {
    // The accessible name concatenates badge text ("Enter Financeowners"),
    // and short labels like "Finance" also match "Enter Finance" by
    // substring. Use href to disambiguate — it's the unique key the
    // component maps from.
    const links = Array.from(document.querySelectorAll<HTMLAnchorElement>("a[href]"));
    const link = links.find((a) => a.getAttribute("href") === href);
    if (!link) {
      throw new Error(`No link found with href="${href}"`);
    }
    return link;
  }

  it("renders all top-level dashboard tabs", () => {
    render(<TopNav />);
    for (const href of ["/", "/operations", "/finance", "/clinical", "/people", "/scorecards"]) {
      expect(findTabByHref(href)).toBeInTheDocument();
    }
  });

  it("renders the brand title", () => {
    render(<TopNav />);
    expect(screen.getByText("HHA Medicine")).toBeInTheDocument();
    expect(screen.getByText(/Operations Dashboard/)).toBeInTheDocument();
  });

  it("returns null on /census/* paths (separate auth surface)", () => {
    vi.mocked(usePathname).mockReturnValue("/census/login");
    const { container } = render(<TopNav />);
    expect(container.firstChild).toBeNull();
  });

  it("returns null on a nested /census/* path", () => {
    vi.mocked(usePathname).mockReturnValue("/census/2026-05-13");
    const { container } = render(<TopNav />);
    expect(container.firstChild).toBeNull();
  });

  it("marks the active tab with indigo background when pathname matches", () => {
    vi.mocked(usePathname).mockReturnValue("/finance");
    render(<TopNav />);
    expect(findTabByHref("/finance").className).toContain("bg-indigo-500");
  });

  it("marks a nested path as active under its top tab (startsWith)", () => {
    vi.mocked(usePathname).mockReturnValue("/operations/sites/3");
    render(<TopNav />);
    expect(findTabByHref("/operations").className).toContain("bg-indigo-500");
  });

  it("does NOT treat root '/' as a startsWith match for other tabs", () => {
    vi.mocked(usePathname).mockReturnValue("/");
    render(<TopNav />);
    expect(findTabByHref("/").className).toContain("bg-indigo-500");
    expect(findTabByHref("/finance").className).not.toContain("bg-indigo-500");
  });

  it("renders dev-default user label + initials when in dev mode", () => {
    vi.mocked(useUser).mockReturnValue({
      user: { authenticated: false, mode: "dev" },
      isLoading: false,
    });
    render(<TopNav />);
    expect(screen.getByText("dev-default@local")).toBeInTheDocument();
    expect(screen.getByText("admin · dev")).toBeInTheDocument();
  });

  it("renders authenticated user's name + roles when signed in", () => {
    vi.mocked(useUser).mockReturnValue({
      user: {
        authenticated: true,
        upn: "alice@hha.com",
        name: "Alice Smith",
        roles: ["exec", "comp_viewer"],
        comp_viewer: true,
      },
      isLoading: false,
    });
    render(<TopNav />);
    expect(screen.getByText("Alice Smith")).toBeInTheDocument();
    expect(screen.getByText("exec · comp_viewer")).toBeInTheDocument();
    // Initials: A + S → "AS"
    expect(screen.getByText("AS")).toBeInTheDocument();
  });

  it("falls back to upn when authenticated user has no name", () => {
    vi.mocked(useUser).mockReturnValue({
      user: {
        authenticated: true,
        upn: "bob@hha.com",
        name: "",
        roles: [],
        comp_viewer: false,
      },
      isLoading: false,
    });
    render(<TopNav />);
    expect(screen.getByText("bob@hha.com")).toBeInTheDocument();
    expect(screen.getByText("no roles")).toBeInTheDocument();
  });

  it("renders 'signed out' subtext when user is not authenticated in prod mode", () => {
    vi.mocked(useUser).mockReturnValue({
      user: { authenticated: false, mode: "prod" },
      isLoading: false,
    });
    render(<TopNav />);
    expect(screen.getByText("signed out")).toBeInTheDocument();
    // Both the displayName cell and the initials avatar render an em-dash
    // when user is signed out — assert ≥1 rather than exact uniqueness.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1);
  });

  it("renders owner-only badges on entry-form tabs", () => {
    render(<TopNav />);
    const ownerBadges = screen.getAllByText("owners");
    // Per TABS list: 5 entry forms carry the owners badge
    expect(ownerBadges.length).toBe(5);
  });

  it("renders the exec-only badge on Doctor Scorecards tab", () => {
    render(<TopNav />);
    expect(screen.getByText("exec-only")).toBeInTheDocument();
  });
});
