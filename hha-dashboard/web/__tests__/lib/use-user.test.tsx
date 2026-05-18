// @vitest-environment happy-dom
//
// useUser hook tests — wraps TanStack Query around the /api/auth/me
// endpoint with a 60s staleTime. Covers:
//   - 401 returns the parsed UnauthenticatedUser body (not throw).
//   - other non-OK throws (so DevTools surfaces config bugs).
//   - 200 returns the parsed CurrentUser.
//   - isLoading toggles during fetch.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useUser } from "@/lib/auth/use-user";

function withQueryClient(children: ReactNode): { wrapped: ReactNode; client: QueryClient } {
  // Fresh QueryClient per test prevents cache hits across tests.
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
    },
  });
  return {
    wrapped: <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    client,
  };
}

function UserProbe() {
  const { user, isLoading } = useUser();
  return (
    <div>
      <div data-testid="loading">{String(isLoading)}</div>
      <div data-testid="user">{user === undefined ? "<undef>" : JSON.stringify(user)}</div>
    </div>
  );
}

describe("useUser", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns the AuthenticatedUser body on 200", async () => {
    const body = {
      authenticated: true,
      upn: "alice@hha.com",
      name: "Alice",
      roles: ["exec"],
      comp_viewer: false,
    };
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const { wrapped } = withQueryClient(<UserProbe />);
    render(wrapped);

    await waitFor(() => {
      expect(screen.getByTestId("user").textContent).toContain("alice@hha.com");
    });
    expect(JSON.parse(screen.getByTestId("user").textContent || "{}")).toEqual(body);
  });

  it("hits /api/auth/me with cache: 'no-store'", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify({ authenticated: false, mode: "dev" }), { status: 200 }),
    );

    const { wrapped } = withQueryClient(<UserProbe />);
    render(wrapped);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalled();
    });

    const [url, init] = vi.mocked(globalThis.fetch).mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/auth/me");
    expect(init.cache).toBe("no-store");
  });

  it("returns the UnauthenticatedUser body on 401 (does NOT throw)", async () => {
    const body = { authenticated: false, mode: "prod" };
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify(body), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const { wrapped } = withQueryClient(<UserProbe />);
    render(wrapped);

    await waitFor(() => {
      expect(screen.getByTestId("user").textContent).toContain("authenticated");
    });
    const parsed = JSON.parse(screen.getByTestId("user").textContent || "{}");
    expect(parsed).toEqual(body);
  });

  it("throws on non-401 non-OK responses (surfaces config bugs in DevTools)", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(new Response("server-error", { status: 500 }));

    const { wrapped } = withQueryClient(<UserProbe />);
    render(wrapped);

    // React Query catches the throw; isLoading transitions to false but
    // user stays undefined (no successful body to render).
    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
    });
    expect(screen.getByTestId("user").textContent).toBe("<undef>");
  });

  it("isLoading starts true and toggles to false after fetch resolves", async () => {
    let resolveFetch!: (r: Response) => void;
    vi.mocked(globalThis.fetch).mockReturnValue(
      new Promise<Response>((r) => {
        resolveFetch = r;
      }),
    );

    const { wrapped } = withQueryClient(<UserProbe />);
    render(wrapped);

    // Initial state: loading
    expect(screen.getByTestId("loading").textContent).toBe("true");
    expect(screen.getByTestId("user").textContent).toBe("<undef>");

    // Resolve the fetch
    resolveFetch(
      new Response(JSON.stringify({ authenticated: false, mode: "dev" }), { status: 200 }),
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
    });
  });
});
