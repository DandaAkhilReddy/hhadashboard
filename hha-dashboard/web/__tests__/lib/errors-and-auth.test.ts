// Node-environment tests for the typed Error classes + with-auth helper.
//
// Errors are pure; with-auth needs next/navigation.redirect mocked
// (which calls throw in real Next.js to bail the render — we mock to
// a tagged exception we can catch and assert on).

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, ForbiddenError, UnauthenticatedError } from "@/lib/errors";

// ----- error classes -----

describe("ApiError", () => {
  it("captures status, path, body, and renders a structured message", () => {
    const err = new ApiError(500, "/api/x", "internal");
    expect(err).toBeInstanceOf(Error);
    expect(err.status).toBe(500);
    expect(err.path).toBe("/api/x");
    expect(err.bodyText).toBe("internal");
    expect(err.message).toBe("/api/x → 500: internal");
    expect(err.name).toBe("ApiError");
  });
});

describe("UnauthenticatedError", () => {
  it("locks status to 401 + carries path/body + overrides name", () => {
    const err = new UnauthenticatedError("/api/x", "expired");
    expect(err.status).toBe(401);
    expect(err.path).toBe("/api/x");
    expect(err.bodyText).toBe("expired");
    expect(err.name).toBe("UnauthenticatedError");
  });

  it("is a subclass of ApiError for the catch chain in with-auth", () => {
    expect(new UnauthenticatedError("/", "")).toBeInstanceOf(ApiError);
    expect(new UnauthenticatedError("/", "")).toBeInstanceOf(Error);
  });
});

describe("ForbiddenError", () => {
  it("locks status to 403 + carries path/body + overrides name", () => {
    const err = new ForbiddenError("/api/admin", "no role");
    expect(err.status).toBe(403);
    expect(err.path).toBe("/api/admin");
    expect(err.bodyText).toBe("no role");
    expect(err.name).toBe("ForbiddenError");
  });

  it("is a subclass of ApiError", () => {
    expect(new ForbiddenError("/", "")).toBeInstanceOf(ApiError);
  });

  it("is NOT a subclass of UnauthenticatedError (separate catch path)", () => {
    expect(new ForbiddenError("/", "")).not.toBeInstanceOf(UnauthenticatedError);
  });
});

// ----- fetchOrSignIn -----

// next/navigation's `redirect()` throws an internal Next.js sentinel that
// bubbles up the render tree. We mock it to throw a tagged Error so the
// test can assert on the redirect target + behavior.
class RedirectCalled extends Error {
  constructor(public to: string) {
    super(`REDIRECT ${to}`);
    this.name = "RedirectCalled";
  }
}

vi.mock("next/navigation", () => ({
  redirect: (to: string): never => {
    throw new RedirectCalled(to);
  },
}));

import { fetchOrSignIn } from "@/lib/auth/with-auth";

describe("fetchOrSignIn()", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns the wrapped fn's result on success", async () => {
    const result = await fetchOrSignIn(async () => ({ ok: true, data: [1, 2, 3] }));
    expect(result).toEqual({ ok: true, data: [1, 2, 3] });
  });

  it("redirects to /auth/sign-in (no return param) when UnauthenticatedError fires", async () => {
    const promise = fetchOrSignIn(async () => {
      throw new UnauthenticatedError("/api/x", "expired");
    });

    await expect(promise).rejects.toThrow(RedirectCalled);
    await expect(promise).rejects.toMatchObject({ to: "/auth/sign-in" });
  });

  it("appends ?return=<encoded path> when returnTo is provided", async () => {
    const promise = fetchOrSignIn(async () => {
      throw new UnauthenticatedError("/api/x", "expired");
    }, "/operations/sites/3");

    await expect(promise).rejects.toMatchObject({
      to: "/auth/sign-in?return=%2Foperations%2Fsites%2F3",
    });
  });

  it("encodes query-string-unsafe characters in returnTo", async () => {
    const promise = fetchOrSignIn(async () => {
      throw new UnauthenticatedError("/api/x", "expired");
    }, "/path?with=query&more=stuff");

    await expect(promise).rejects.toMatchObject({
      to: "/auth/sign-in?return=%2Fpath%3Fwith%3Dquery%26more%3Dstuff",
    });
  });

  it("bubbles ForbiddenError unchanged (does NOT redirect — the page shows 403)", async () => {
    const promise = fetchOrSignIn(async () => {
      throw new ForbiddenError("/api/admin", "no role");
    });

    await expect(promise).rejects.toBeInstanceOf(ForbiddenError);
    await expect(promise).rejects.not.toBeInstanceOf(RedirectCalled);
  });

  it("bubbles generic ApiError unchanged", async () => {
    const promise = fetchOrSignIn(async () => {
      throw new ApiError(500, "/api/x", "boom");
    });

    await expect(promise).rejects.toBeInstanceOf(ApiError);
    await expect(promise).rejects.not.toBeInstanceOf(UnauthenticatedError);
  });

  it("bubbles non-API errors (TypeError, etc.) unchanged", async () => {
    const promise = fetchOrSignIn(async () => {
      throw new TypeError("network is down");
    });

    await expect(promise).rejects.toBeInstanceOf(TypeError);
  });
});
