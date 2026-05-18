// @vitest-environment happy-dom
//
// Auth-flow page tests: /auth/sign-in and /auth/sign-out.
//
// Both pages are client components that fire side effects on mount.
// Mocks:
//   - @azure/msal-react useMsal: controls accounts + inProgress state +
//     instance.loginRedirect / logoutRedirect
//   - @/lib/auth/msal-config: isMsalConfigured + loginScopes
//   - next/navigation useRouter + useSearchParams: replace() and get()
//   - global fetch for /api/auth/session DELETE

import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// ----- Module mocks (must precede page imports) -----

const replaceMock = vi.fn();
const getMock = vi.fn();
const loginRedirectMock = vi.fn();
const logoutRedirectMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  useSearchParams: () => ({ get: getMock }),
}));

vi.mock("@azure/msal-react", () => ({
  useMsal: vi.fn(),
}));

vi.mock("@/lib/auth/msal-config", () => ({
  isMsalConfigured: vi.fn(),
  loginScopes: ["User.Read"],
}));

import { isMsalConfigured } from "@/lib/auth/msal-config";
import { useMsal } from "@azure/msal-react";

import SignInPage from "@/app/auth/sign-in/page";
import SignOutPage from "@/app/auth/sign-out/page";

function defaultMsal(overrides: Record<string, unknown> = {}) {
  return {
    accounts: [] as unknown[],
    inProgress: "none" as const,
    instance: {
      loginRedirect: loginRedirectMock,
      logoutRedirect: logoutRedirectMock,
    },
    ...overrides,
  };
}

// ----- /auth/sign-in -----

describe("SignInPage", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    getMock.mockReset();
    loginRedirectMock.mockReset().mockResolvedValue(undefined);
    vi.mocked(useMsal).mockReturnValue(defaultMsal() as never);
    vi.mocked(isMsalConfigured).mockReset();
  });

  it("redirects to returnTo immediately in dev mode (MSAL unconfigured)", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    getMock.mockReturnValue("/finance");

    render(<SignInPage />);

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/finance");
    });
    expect(loginRedirectMock).not.toHaveBeenCalled();
  });

  it("defaults returnTo to '/' when no ?return= param is present", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    getMock.mockReturnValue(null);

    render(<SignInPage />);

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/");
    });
  });

  it("redirects to returnTo when MSAL has cached accounts (already signed in)", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(true);
    vi.mocked(useMsal).mockReturnValue(
      defaultMsal({ accounts: [{ username: "alice@hha.com" }] }) as never,
    );
    getMock.mockReturnValue("/operations");

    render(<SignInPage />);

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/operations");
    });
    expect(loginRedirectMock).not.toHaveBeenCalled();
  });

  it("does nothing when MSAL is already mid-flow (inProgress != 'none')", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(true);
    vi.mocked(useMsal).mockReturnValue(defaultMsal({ inProgress: "login" }) as never);
    getMock.mockReturnValue("/");

    render(<SignInPage />);

    // Give the effect a tick to run
    await Promise.resolve();
    expect(loginRedirectMock).not.toHaveBeenCalled();
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("calls loginRedirect with the configured scopes and returnTo as redirectStartPage", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(true);
    getMock.mockReturnValue("/scorecards");

    render(<SignInPage />);

    await waitFor(() => {
      expect(loginRedirectMock).toHaveBeenCalledTimes(1);
    });
    expect(loginRedirectMock).toHaveBeenCalledWith({
      scopes: ["User.Read"],
      redirectStartPage: "/scorecards",
    });
  });

  it("renders the error message when loginRedirect rejects", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(true);
    getMock.mockReturnValue("/");
    loginRedirectMock.mockRejectedValueOnce(new Error("popup blocked"));

    const { findByText } = render(<SignInPage />);

    expect(await findByText(/Sign-in error: popup blocked/)).toBeInTheDocument();
  });

  it("renders 'Dev mode' copy when MSAL is unconfigured", () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    getMock.mockReturnValue("/");

    const { getByText } = render(<SignInPage />);

    expect(getByText(/Dev mode/)).toBeInTheDocument();
  });

  it("renders the redirecting copy when MSAL is configured + no cached account", () => {
    vi.mocked(isMsalConfigured).mockReturnValue(true);
    getMock.mockReturnValue("/");

    const { getByText } = render(<SignInPage />);

    expect(getByText(/Redirecting to Microsoft sign-in/)).toBeInTheDocument();
  });

  it("captures non-Error throws with the 'sign-in failed' fallback message", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(true);
    getMock.mockReturnValue("/");
    loginRedirectMock.mockRejectedValueOnce("oops not an Error");

    const { findByText } = render(<SignInPage />);

    expect(await findByText(/Sign-in error: sign-in failed/)).toBeInTheDocument();
  });
});

// ----- /auth/sign-out -----

describe("SignOutPage", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    logoutRedirectMock.mockReset().mockResolvedValue(undefined);
    vi.mocked(useMsal).mockReturnValue(defaultMsal() as never);
    vi.mocked(isMsalConfigured).mockReset();
    // Mock fetch so the session DELETE never tries the network
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
  });

  it("clears the session cookie via DELETE /api/auth/session", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);

    render(<SignOutPage />);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith("/api/auth/session", {
        method: "DELETE",
      });
    });
  });

  it("calls msal.logoutRedirect when MSAL is configured", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(true);

    render(<SignOutPage />);

    await waitFor(() => {
      expect(logoutRedirectMock).toHaveBeenCalledTimes(1);
    });
    expect(logoutRedirectMock).toHaveBeenCalledWith({
      postLogoutRedirectUri: "/",
    });
    // Router replace NOT called when MSAL handles the redirect itself
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("router.replace('/') when MSAL is NOT configured (dev mode)", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);

    render(<SignOutPage />);

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/");
    });
    expect(logoutRedirectMock).not.toHaveBeenCalled();
  });

  it("renders 'Signing you out…' copy while the effect runs", () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    const { getByText } = render(<SignOutPage />);
    expect(getByText(/Signing you out/)).toBeInTheDocument();
  });

  it("does NOT call logoutRedirect or router.replace if unmounted before clearSession resolves", async () => {
    vi.mocked(isMsalConfigured).mockReturnValue(false);
    // Make the fetch hang indefinitely
    let resolveFetch!: (r: Response) => void;
    vi.mocked(globalThis.fetch).mockReturnValue(
      new Promise<Response>((r) => {
        resolveFetch = r;
      }),
    );

    const { unmount } = render(<SignOutPage />);
    unmount();
    resolveFetch(new Response(null, { status: 204 }));
    // Let any microtasks settle
    await Promise.resolve();
    await Promise.resolve();

    expect(replaceMock).not.toHaveBeenCalled();
    expect(logoutRedirectMock).not.toHaveBeenCalled();
  });
});
