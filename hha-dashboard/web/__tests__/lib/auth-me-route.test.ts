// @vitest-environment node
//
// GET /api/auth/me — the route the TopNav uses to surface the current
// user's display name + role chips without a round-trip to FastAPI.
// Covers:
//  - no-cookie path (dev mode → 200, prod mode → 401)
//  - decryptSession returning null → 401
//  - expired session → 401
//  - malformed JWT (not 3 dot-separated parts) → 401
//  - base64url JSON decode failure → 401
//  - happy path: claims → UPN + name + roles + comp_viewer flag
//  - group → role mapping from env vars
//  - UPN fallback chain (preferred_username → upn → email → oid)

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const cookieStoreGet = vi.fn();
const decryptSessionMock = vi.fn();
const isSessionExpiredMock = vi.fn();

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: cookieStoreGet }),
}));

vi.mock("@/lib/auth/session-crypto", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth/session-crypto")>(
    "@/lib/auth/session-crypto",
  );
  return {
    ...actual,
    decryptSession: (raw: string) => decryptSessionMock(raw),
    isSessionExpired: (s: unknown) => isSessionExpiredMock(s),
  };
});

import { GET } from "@/app/api/auth/me/route";

function makeJwt(claims: Record<string, unknown>): string {
  // Build a JWT-like string (header.payload.signature). The route reads
  // only the middle segment; header + signature are arbitrary.
  const header = btoa(JSON.stringify({ alg: "RS256", typ: "JWT" }))
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  const payload = btoa(JSON.stringify(claims))
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  return `${header}.${payload}.signature`;
}

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  cookieStoreGet.mockReset();
  decryptSessionMock.mockReset();
  isSessionExpiredMock.mockReset();
  // Default: not expired (the happy-path branch). Individual tests can
  // override to force the expiry branch.
  isSessionExpiredMock.mockReturnValue(false);
});

afterEach(() => {
  // Restore env so role-map tests don't bleed.
  process.env = { ...ORIGINAL_ENV };
});

// ----------------------------- No-cookie branch -----------------------------

describe("GET /api/auth/me — no cookie", () => {
  it("dev mode returns 200 + authenticated:false", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "dev";
    cookieStoreGet.mockReturnValue(undefined);

    // Re-import to pick up the env change in the AUTH_MODE constant.
    vi.resetModules();
    const { GET: GetFresh } = await import("@/app/api/auth/me/route");
    const res = await GetFresh();

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({ authenticated: false, mode: "dev" });
  });

  it("prod mode returns 401", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    cookieStoreGet.mockReturnValue(undefined);

    vi.resetModules();
    const { GET: GetFresh } = await import("@/app/api/auth/me/route");
    const res = await GetFresh();

    expect(res.status).toBe(401);
    const body = await res.json();
    expect(body).toEqual({ authenticated: false, mode: "prod" });
  });
});

// ----------------------------- Session-decrypt failure ----------------------

describe("GET /api/auth/me — bad session", () => {
  it("decryptSession returns null → 401", async () => {
    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue(null);

    const res = await GET();

    expect(res.status).toBe(401);
    const body = await res.json();
    expect(body.authenticated).toBe(false);
  });

  it("isSessionExpired(true) → 401", async () => {
    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue({ access_token: makeJwt({ upn: "x@y.com" }) });
    isSessionExpiredMock.mockReturnValue(true);

    const res = await GET();

    expect(res.status).toBe(401);
  });
});

// ----------------------------- JWT decode failures --------------------------

describe("GET /api/auth/me — JWT decoding", () => {
  it("returns 401 when access_token has fewer than 3 dot-separated parts", async () => {
    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue({ access_token: "header.payload" });

    const res = await GET();

    expect(res.status).toBe(401);
  });

  it("returns 401 when middle segment is not valid base64url JSON", async () => {
    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue({
      access_token: "header.@@@not-base64@@@.signature",
    });

    const res = await GET();

    expect(res.status).toBe(401);
  });
});

// ----------------------------- UPN fallback chain ---------------------------

describe("GET /api/auth/me — UPN fallback chain", () => {
  it.each([
    [{ preferred_username: "p@hha.com" }, "p@hha.com"],
    [{ upn: "u@hha.com" }, "u@hha.com"],
    [{ email: "e@hha.com" }, "e@hha.com"],
    [{ oid: "00000000-0000-0000-0000-000000000001" }, "00000000-0000-0000-0000-000000000001"],
  ])("picks %j -> %s", async (claims, expected) => {
    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue({ access_token: makeJwt(claims) });

    const res = await GET();
    const body = await res.json();
    expect(body.upn).toBe(expected);
  });

  it("prefers preferred_username over upn when both present", async () => {
    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue({
      access_token: makeJwt({ preferred_username: "first@hha.com", upn: "second@hha.com" }),
    });

    const body = await (await GET()).json();
    expect(body.upn).toBe("first@hha.com");
  });

  it("returns empty UPN when no candidate claim present", async () => {
    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue({
      access_token: makeJwt({ name: "Just a Name" }),
    });

    const body = await (await GET()).json();
    expect(body.upn).toBe("");
  });
});

// ----------------------------- Name extraction ------------------------------

describe("GET /api/auth/me — name extraction", () => {
  it("uses claims.name when present", async () => {
    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue({
      access_token: makeJwt({ name: "Crystal Robinson", upn: "crystal@hha.com" }),
    });

    const body = await (await GET()).json();
    expect(body.name).toBe("Crystal Robinson");
  });

  it("falls back to UPN when name is absent", async () => {
    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue({
      access_token: makeJwt({ upn: "u@hha.com" }),
    });

    const body = await (await GET()).json();
    expect(body.name).toBe("u@hha.com");
  });
});

// ----------------------------- Role mapping ---------------------------------

describe("GET /api/auth/me — role mapping from group IDs", () => {
  it("maps the admin group to the admin role", async () => {
    process.env.NEXT_PUBLIC_ENTRA_GROUP_ADMIN = "00000000-admin";
    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue({
      access_token: makeJwt({
        upn: "akhil@hha.com",
        groups: ["00000000-admin"],
      }),
    });

    vi.resetModules();
    const { GET: GetFresh } = await import("@/app/api/auth/me/route");
    const body = await (await GetFresh()).json();
    expect(body.roles).toEqual(["admin"]);
  });

  it("maps multiple groups and dedupes via Set semantics", async () => {
    process.env.NEXT_PUBLIC_ENTRA_GROUP_ADMIN = "g-admin";
    process.env.NEXT_PUBLIC_ENTRA_GROUP_EXEC = "g-exec";
    process.env.NEXT_PUBLIC_ENTRA_GROUP_OWNER_OPS = "g-ops";

    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue({
      access_token: makeJwt({
        upn: "akhil@hha.com",
        groups: ["g-admin", "g-exec", "g-ops", "g-admin"], // duplicate g-admin
      }),
    });

    vi.resetModules();
    const { GET: GetFresh } = await import("@/app/api/auth/me/route");
    const body = await (await GetFresh()).json();
    expect(new Set(body.roles)).toEqual(new Set(["admin", "exec", "owner_ops"]));
  });

  it("ignores groups not in the env-var map", async () => {
    process.env.NEXT_PUBLIC_ENTRA_GROUP_ADMIN = "g-admin";
    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue({
      access_token: makeJwt({
        upn: "akhil@hha.com",
        groups: ["g-admin", "g-unknown-group", "another-unknown"],
      }),
    });

    vi.resetModules();
    const { GET: GetFresh } = await import("@/app/api/auth/me/route");
    const body = await (await GetFresh()).json();
    expect(body.roles).toEqual(["admin"]);
  });

  it("empty role list when groups claim is missing", async () => {
    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue({
      access_token: makeJwt({ upn: "akhil@hha.com" }),
    });

    const body = await (await GET()).json();
    expect(body.roles).toEqual([]);
  });

  it("empty role list when groups claim is not an array (defensive)", async () => {
    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue({
      access_token: makeJwt({ upn: "x@y.com", groups: "not-an-array" }),
    });

    const body = await (await GET()).json();
    expect(body.roles).toEqual([]);
  });

  it("ignores non-string entries inside the groups array", async () => {
    process.env.NEXT_PUBLIC_ENTRA_GROUP_ADMIN = "g-admin";
    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue({
      access_token: makeJwt({
        upn: "x@y.com",
        groups: ["g-admin", 42, null, { id: "bad" }],
      }),
    });

    vi.resetModules();
    const { GET: GetFresh } = await import("@/app/api/auth/me/route");
    const body = await (await GetFresh()).json();
    expect(body.roles).toEqual(["admin"]);
  });
});

// ----------------------------- comp_viewer flag -----------------------------

describe("GET /api/auth/me — comp_viewer flag", () => {
  it("is true when the user has the comp_viewer role", async () => {
    process.env.NEXT_PUBLIC_ENTRA_GROUP_COMP_VIEWER = "g-comp";
    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue({
      access_token: makeJwt({ upn: "x@y.com", groups: ["g-comp"] }),
    });

    vi.resetModules();
    const { GET: GetFresh } = await import("@/app/api/auth/me/route");
    const body = await (await GetFresh()).json();
    expect(body.comp_viewer).toBe(true);
  });

  it("is false when the user has roles but none of them is comp_viewer", async () => {
    process.env.NEXT_PUBLIC_ENTRA_GROUP_ADMIN = "g-admin";
    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue({
      access_token: makeJwt({ upn: "x@y.com", groups: ["g-admin"] }),
    });

    vi.resetModules();
    const { GET: GetFresh } = await import("@/app/api/auth/me/route");
    const body = await (await GetFresh()).json();
    expect(body.comp_viewer).toBe(false);
  });
});

// ----------------------------- Happy path -----------------------------------

describe("GET /api/auth/me — happy path", () => {
  it("returns 200 + the full authenticated payload", async () => {
    process.env.NEXT_PUBLIC_ENTRA_GROUP_ADMIN = "g-admin";
    process.env.NEXT_PUBLIC_ENTRA_GROUP_COMP_VIEWER = "g-comp";

    cookieStoreGet.mockReturnValue({ value: "ciphertext" });
    decryptSessionMock.mockResolvedValue({
      access_token: makeJwt({
        preferred_username: "akhil@hha.com",
        name: "Akhil Reddy",
        groups: ["g-admin", "g-comp"],
      }),
    });

    vi.resetModules();
    const { GET: GetFresh } = await import("@/app/api/auth/me/route");
    const res = await GetFresh();

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.authenticated).toBe(true);
    expect(body.upn).toBe("akhil@hha.com");
    expect(body.name).toBe("Akhil Reddy");
    expect(new Set(body.roles)).toEqual(new Set(["admin", "comp_viewer"]));
    expect(body.comp_viewer).toBe(true);
  });
});
