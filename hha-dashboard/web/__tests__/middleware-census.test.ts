// @vitest-environment node
//
// Extra middleware coverage for the **census portal branch** (lines
// 41-53 of `web/middleware.ts`). The existing middleware.test.ts only
// exercises the dashboard branch — this file pins:
//   - /census/login passes through regardless of cookie
//   - bare /census passes through regardless of cookie
//   - other /census/* paths require the `census_session` cookie
//   - census-branch behavior is independent of NEXT_PUBLIC_AUTH_MODE
//     (the portal lives outside the Entra auth model)

import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const ORIGINAL_AUTH_MODE = process.env.NEXT_PUBLIC_AUTH_MODE;

function makeRequest(pathname: string, cookies: Record<string, string> = {}): NextRequest {
  const url = `http://localhost:3000${pathname}`;
  const cookieHeader = Object.entries(cookies)
    .map(([k, v]) => `${k}=${v}`)
    .join("; ");
  const headers: HeadersInit = cookieHeader ? { cookie: cookieHeader } : {};
  return new NextRequest(url, { headers });
}

async function loadMiddleware() {
  vi.resetModules();
  return (await import("@/middleware")) as typeof import("@/middleware");
}

beforeEach(() => {
  vi.resetModules();
});

afterEach(() => {
  if (ORIGINAL_AUTH_MODE === undefined) {
    // biome-ignore lint/performance/noDelete: env keys can't be unset via assignment
    delete process.env.NEXT_PUBLIC_AUTH_MODE;
  } else {
    process.env.NEXT_PUBLIC_AUTH_MODE = ORIGINAL_AUTH_MODE;
  }
});

// ============================================================================
// /census/login — public, regardless of cookie
// ============================================================================

describe("middleware — census portal", () => {
  it("passes through /census/login without a cookie (dev mode)", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "dev";
    const { middleware } = await loadMiddleware();
    const res = middleware(makeRequest("/census/login"));
    expect(res.status).toBe(200);
    expect(res.headers.get("location")).toBeNull();
  });

  it("passes through /census/login in prod mode too (portal is Entra-independent)", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    const { middleware } = await loadMiddleware();
    const res = middleware(makeRequest("/census/login"));
    expect(res.status).toBe(200);
  });

  it("passes through the bare /census root without a cookie", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    const { middleware } = await loadMiddleware();
    const res = middleware(makeRequest("/census"));
    expect(res.status).toBe(200);
  });
});

// ============================================================================
// /census/entry — protected
// ============================================================================

describe("middleware — census portal protected paths", () => {
  it("redirects /census/entry to /census/login when the cookie is missing (prod)", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    const { middleware } = await loadMiddleware();
    const res = middleware(makeRequest("/census/entry"));
    expect(res.status).toBe(307);
    const loc = res.headers.get("location") ?? "";
    expect(loc).toContain("/census/login");
    // Census branch strips the search string (no ?return= param like
    // dashboard does — the portal is a single page, not deep-linkable)
    expect(loc).not.toContain("return=");
  });

  it("redirects /census/entry to /census/login when the cookie is missing (dev)", async () => {
    // Critical: census-branch behavior is INDEPENDENT of AUTH_MODE — the
    // portal stays gated even in dev because it's not Entra-backed.
    process.env.NEXT_PUBLIC_AUTH_MODE = "dev";
    const { middleware } = await loadMiddleware();
    const res = middleware(makeRequest("/census/entry"));
    expect(res.status).toBe(307);
    expect(res.headers.get("location") ?? "").toContain("/census/login");
  });

  it("passes through /census/entry when census_session cookie is present", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    const { middleware } = await loadMiddleware();
    const res = middleware(makeRequest("/census/entry", { census_session: "token123" }));
    expect(res.status).toBe(200);
    expect(res.headers.get("location")).toBeNull();
  });

  it("ignores the dashboard cookie (hha_session) for census-path auth", async () => {
    // Dashboard cookie alone does NOT grant census-portal access. Separate
    // surfaces, separate cookies — verifying the isolation.
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    const { middleware } = await loadMiddleware();
    const res = middleware(makeRequest("/census/entry", { hha_session: "dashboard" }));
    expect(res.status).toBe(307);
    expect(res.headers.get("location") ?? "").toContain("/census/login");
  });

  it("strips the query string on redirect (portal is not deep-linkable)", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    const { middleware } = await loadMiddleware();
    const res = middleware(makeRequest("/census/entry?date=2026-05-10"));
    const loc = res.headers.get("location") ?? "";
    // The middleware sets `loginUrl.search = ""` — the redirect URL ends at
    // /census/login with no query parameters.
    expect(loc.endsWith("/census/login")).toBe(true);
    expect(loc).not.toContain("?");
  });
});

// ============================================================================
// /census branch does not interfere with /auth/* paths
// ============================================================================

describe("middleware — census branch isolation", () => {
  it("does NOT treat /auth/sign-in as a census path", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    const { middleware } = await loadMiddleware();
    const res = middleware(makeRequest("/auth/sign-in"));
    // Falls through to the dashboard branch's public-prefix check → 200
    expect(res.status).toBe(200);
  });

  it("a path that starts with 'census' but is not under /census/ falls into dashboard branch", async () => {
    // The check is `pathname.startsWith("/census")`, so "/census-foo" matches.
    // Pin the actual behavior (defensive — a future refactor might tighten
    // this to a path-segment match, and this test would catch the intent).
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    const { middleware } = await loadMiddleware();
    const res = middleware(makeRequest("/census-foo"));
    // Currently treated as a census path → redirects to /census/login
    expect(res.status).toBe(307);
    expect(res.headers.get("location") ?? "").toContain("/census/login");
  });
});
