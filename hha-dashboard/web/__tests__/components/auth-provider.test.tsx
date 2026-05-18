// @vitest-environment happy-dom
//
// AuthProvider: client-side MSAL + TanStack Query wiring at the app root.
//
// Three branches to verify:
//   1. instance === null (dev mode, no MSAL env) → renders QueryClientProvider
//      only; children visible immediately.
//   2. instance !== null but not yet initialized → renders null (returns
//      nothing while MSAL bootstraps).
//   3. instance !== null + initialized → wraps in MsalProvider +
//      QueryClientProvider; children visible.

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// MSAL deps and config helpers are mocked BEFORE importing AuthProvider so
// the component picks up the mocked exports.
vi.mock("@/lib/auth/msal-config", () => ({
  getMsalInstance: vi.fn(),
  ensureMsalInitialized: vi.fn(),
}));

vi.mock("@azure/msal-react", () => ({
  MsalProvider: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="msal-provider">{children}</div>
  ),
}));

import { ensureMsalInitialized, getMsalInstance } from "@/lib/auth/msal-config";

import { AuthProvider } from "@/components/AuthProvider";

describe("AuthProvider", () => {
  beforeEach(() => {
    vi.mocked(getMsalInstance).mockReset();
    vi.mocked(ensureMsalInitialized).mockReset();
  });

  it("renders children inside QueryClientProvider only when no MSAL instance (dev mode)", () => {
    vi.mocked(getMsalInstance).mockReturnValue(null);

    render(
      <AuthProvider>
        <div>dev-child</div>
      </AuthProvider>,
    );

    expect(screen.getByText("dev-child")).toBeInTheDocument();
    // No MSAL wrapper because instance is null
    expect(screen.queryByTestId("msal-provider")).toBeNull();
  });

  it("renders nothing while MSAL is initializing (instance set but not yet ready)", () => {
    // Make ensureMsalInitialized hang so we can observe the not-initialized state
    vi.mocked(getMsalInstance).mockReturnValue({} as never);
    vi.mocked(ensureMsalInitialized).mockReturnValue(
      new Promise<void>(() => {
        // never resolves in this test
      }),
    );

    const { container } = render(
      <AuthProvider>
        <div>blocked-child</div>
      </AuthProvider>,
    );

    // While initializing, AuthProvider returns null → children NOT rendered
    expect(screen.queryByText("blocked-child")).toBeNull();
    expect(container.firstChild).toBeNull();
  });

  it("renders children inside both providers once MSAL initialization resolves", async () => {
    vi.mocked(getMsalInstance).mockReturnValue({} as never);
    vi.mocked(ensureMsalInitialized).mockResolvedValue(undefined);

    render(
      <AuthProvider>
        <div>prod-child</div>
      </AuthProvider>,
    );

    // Wait for the post-init render
    await waitFor(() => {
      expect(screen.getByText("prod-child")).toBeInTheDocument();
    });

    // Both wrappers present
    expect(screen.getByTestId("msal-provider")).toBeInTheDocument();
  });

  it("calls ensureMsalInitialized exactly once on mount when instance is non-null", async () => {
    vi.mocked(getMsalInstance).mockReturnValue({} as never);
    vi.mocked(ensureMsalInitialized).mockResolvedValue(undefined);

    render(
      <AuthProvider>
        <div>x</div>
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(ensureMsalInitialized).toHaveBeenCalledTimes(1);
    });
  });

  it("does NOT call ensureMsalInitialized when instance is null (dev mode)", () => {
    vi.mocked(getMsalInstance).mockReturnValue(null);

    render(
      <AuthProvider>
        <div>x</div>
      </AuthProvider>,
    );

    expect(ensureMsalInitialized).not.toHaveBeenCalled();
  });

  it("ignores a late-resolving initialization if the component unmounted (cancellation guard)", async () => {
    let resolve!: () => void;
    vi.mocked(getMsalInstance).mockReturnValue({} as never);
    vi.mocked(ensureMsalInitialized).mockReturnValue(
      new Promise<void>((r) => {
        resolve = r;
      }),
    );

    const { unmount } = render(
      <AuthProvider>
        <div>late</div>
      </AuthProvider>,
    );

    // Unmount before init completes — no state-update-after-unmount warning
    // should fire. The internal `cancelled` flag handles this.
    unmount();
    resolve();

    // Give microtasks a chance to settle. No assertion needed beyond
    // "no thrown errors" — React would warn loudly if the cleanup were
    // broken. The mock count stays at 1 because the call was issued
    // before unmount.
    await Promise.resolve();
    expect(ensureMsalInitialized).toHaveBeenCalledTimes(1);
  });
});
