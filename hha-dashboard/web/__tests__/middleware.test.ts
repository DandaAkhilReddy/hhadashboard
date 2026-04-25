import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const ORIGINAL_AUTH_MODE = process.env.NEXT_PUBLIC_AUTH_MODE;

function makeRequest(pathname: string, withCookie: boolean): NextRequest {
  const url = `http://localhost:3000${pathname}`;
  const headers: HeadersInit = withCookie ? { cookie: "hha_session=blob123" } : {};
  return new NextRequest(url, { headers });
}

async function loadMiddleware() {
  vi.resetModules();
  // The middleware reads NEXT_PUBLIC_AUTH_MODE at module-load time.
  return (await import("@/middleware")) as typeof import("@/middleware");
}

beforeEach(() => {
  vi.resetModules();
});

afterEach(() => {
  if (ORIGINAL_AUTH_MODE === undefined) {
    delete process.env.NEXT_PUBLIC_AUTH_MODE;
  } else {
    process.env.NEXT_PUBLIC_AUTH_MODE = ORIGINAL_AUTH_MODE;
  }
});

describe("middleware (dev mode)", () => {
  it("passes through every request when AUTH_MODE=dev", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "dev";
    const { middleware } = await loadMiddleware();
    const res = middleware(makeRequest("/operations", false));
    expect(res.status).toBe(200);
    expect(res.headers.get("location")).toBeNull();
  });
});

describe("middleware (prod mode)", () => {
  it("redirects to /auth/sign-in when no cookie present", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    const { middleware } = await loadMiddleware();
    const res = middleware(makeRequest("/operations", false));
    expect(res.status).toBe(307);
    const loc = res.headers.get("location") ?? "";
    expect(loc).toContain("/auth/sign-in");
    expect(loc).toContain("return=%2Foperations");
  });

  it("passes through when cookie present", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    const { middleware } = await loadMiddleware();
    const res = middleware(makeRequest("/operations", true));
    expect(res.status).toBe(200);
  });

  it("does not redirect on /auth/* paths even with no cookie", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    const { middleware } = await loadMiddleware();
    const res = middleware(makeRequest("/auth/sign-in", false));
    expect(res.status).toBe(200);
  });

  it("does not redirect on /api/auth/* even with no cookie", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    const { middleware } = await loadMiddleware();
    const res = middleware(makeRequest("/api/auth/me", false));
    expect(res.status).toBe(200);
  });
});
