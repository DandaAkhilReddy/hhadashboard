// @vitest-environment node
//
// Extra coverage for the input-guard branches in
// `web/app/api/auth/session/route.ts` that the existing
// `session-route.test.ts` skips:
//
//   - non-JSON body in POST -> 400 "invalid json"
//   - body shape failures in isSession() (missing keys, wrong types)
//   - missing Origin header -> 403
//   - malformed Origin URL -> 403 (try/catch in isSameOrigin)
//   - maxAge math (cookie's Max-Age = expires_at - now, clamped >= 0)

import { beforeAll, describe, expect, it } from "vitest";

import { DELETE, POST } from "@/app/api/auth/session/route";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session-crypto";

beforeAll(() => {
  process.env.SESSION_SECRET = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=";
});

function makeRawRequest(
  method: "POST" | "DELETE",
  body: BodyInit | null,
  options: { origin?: string | null; url?: string } = {},
): Request {
  const { origin = "http://localhost:3000", url = "http://localhost:3000/api/auth/session" } =
    options;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (origin !== null) {
    headers.Origin = origin;
  }
  return new Request(url, { method, headers, body });
}

// ============================================================================
// POST — body parsing failures
// ============================================================================

describe("POST /api/auth/session — body parsing", () => {
  it("rejects a non-JSON body with 400 'invalid json'", async () => {
    const res = await POST(makeRawRequest("POST", "not-{json"));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toMatch(/invalid json/);
  });

  it("rejects an empty body with 400", async () => {
    const res = await POST(makeRawRequest("POST", null));
    expect(res.status).toBe(400);
  });

  it("rejects an array body (isSession requires object) with 400", async () => {
    const res = await POST(makeRawRequest("POST", JSON.stringify(["a", "b"])));
    expect(res.status).toBe(400);
  });

  it("rejects a top-level string body with 400", async () => {
    const res = await POST(makeRawRequest("POST", JSON.stringify("hello")));
    expect(res.status).toBe(400);
  });

  it("rejects a top-level number body with 400", async () => {
    const res = await POST(makeRawRequest("POST", JSON.stringify(42)));
    expect(res.status).toBe(400);
  });

  it("rejects a body missing access_token with 400", async () => {
    const res = await POST(
      makeRawRequest("POST", JSON.stringify({ expires_at: Date.now() / 1000 + 60 })),
    );
    expect(res.status).toBe(400);
  });

  it("rejects a body missing expires_at with 400", async () => {
    const res = await POST(makeRawRequest("POST", JSON.stringify({ access_token: "x" })));
    expect(res.status).toBe(400);
  });

  it("rejects a body where access_token is not a string", async () => {
    const res = await POST(
      makeRawRequest(
        "POST",
        JSON.stringify({ access_token: 123, expires_at: Date.now() / 1000 + 60 }),
      ),
    );
    expect(res.status).toBe(400);
  });

  it("rejects a body where expires_at is not a number", async () => {
    const res = await POST(
      makeRawRequest("POST", JSON.stringify({ access_token: "x", expires_at: "soon" })),
    );
    expect(res.status).toBe(400);
  });
});

// ============================================================================
// Origin header — same-origin enforcement edges
// ============================================================================

describe("POST /api/auth/session — Origin header", () => {
  it("rejects a request with no Origin header with 403", async () => {
    // No Origin header at all → isSameOrigin returns false → 403.
    const body = JSON.stringify({
      access_token: "tok",
      expires_at: Math.floor(Date.now() / 1000) + 60,
    });
    const res = await POST(makeRawRequest("POST", body, { origin: null }));
    expect(res.status).toBe(403);
  });

  it("rejects a request with a malformed Origin URL with 403", async () => {
    // The isSameOrigin try/catch swallows URL constructor errors → 403.
    const body = JSON.stringify({
      access_token: "tok",
      expires_at: Math.floor(Date.now() / 1000) + 60,
    });
    const res = await POST(makeRawRequest("POST", body, { origin: "::: not a url :::" }));
    expect(res.status).toBe(403);
  });

  it("rejects a request with the same hostname but different port with 403", async () => {
    // Origin includes the port — :3001 ≠ :3000 even on the same host.
    const body = JSON.stringify({
      access_token: "tok",
      expires_at: Math.floor(Date.now() / 1000) + 60,
    });
    const res = await POST(makeRawRequest("POST", body, { origin: "http://localhost:3001" }));
    expect(res.status).toBe(403);
  });

  it("rejects a request with the same host but http vs https with 403", async () => {
    // Scheme is part of the origin tuple.
    const body = JSON.stringify({
      access_token: "tok",
      expires_at: Math.floor(Date.now() / 1000) + 60,
    });
    const res = await POST(makeRawRequest("POST", body, { origin: "https://localhost:3000" }));
    expect(res.status).toBe(403);
  });
});

// ============================================================================
// maxAge math + Path/SameSite attributes
// ============================================================================

describe("POST /api/auth/session — cookie attributes", () => {
  it("Max-Age equals expires_at - now (within 1 second of jitter)", async () => {
    const now = Math.floor(Date.now() / 1000);
    const lifetimeSeconds = 1800;
    const res = await POST(
      makeRawRequest(
        "POST",
        JSON.stringify({ access_token: "tok", expires_at: now + lifetimeSeconds }),
      ),
    );
    const setCookie = res.headers.get("set-cookie") ?? "";
    const match = setCookie.match(/Max-Age=(\d+)/);
    expect(match).not.toBeNull();
    const maxAge = Number.parseInt(match?.[1] ?? "0", 10);
    expect(maxAge).toBeGreaterThanOrEqual(lifetimeSeconds - 1);
    expect(maxAge).toBeLessThanOrEqual(lifetimeSeconds);
  });

  it("sets Path=/ on the cookie", async () => {
    const res = await POST(
      makeRawRequest(
        "POST",
        JSON.stringify({
          access_token: "tok",
          expires_at: Math.floor(Date.now() / 1000) + 60,
        }),
      ),
    );
    const setCookie = res.headers.get("set-cookie") ?? "";
    expect(setCookie).toContain("Path=/");
  });

  it("sets SameSite=lax on the cookie", async () => {
    const res = await POST(
      makeRawRequest(
        "POST",
        JSON.stringify({
          access_token: "tok",
          expires_at: Math.floor(Date.now() / 1000) + 60,
        }),
      ),
    );
    const setCookie = res.headers.get("set-cookie") ?? "";
    expect(setCookie).toContain("SameSite=lax");
  });

  it("does NOT set Secure when NODE_ENV is test (only in production)", async () => {
    // Tests run with NODE_ENV !== "production", so Secure must be absent.
    const res = await POST(
      makeRawRequest(
        "POST",
        JSON.stringify({
          access_token: "tok",
          expires_at: Math.floor(Date.now() / 1000) + 60,
        }),
      ),
    );
    const setCookie = res.headers.get("set-cookie") ?? "";
    expect(setCookie).not.toContain("Secure");
  });
});

// ============================================================================
// DELETE branch
// ============================================================================

describe("DELETE /api/auth/session — edges", () => {
  it("rejects DELETE with no Origin header", async () => {
    const res = await DELETE(makeRawRequest("DELETE", null, { origin: null }));
    expect(res.status).toBe(403);
  });

  it("DELETE returns the cookie with name=hha_session value='' and Max-Age=0", async () => {
    const res = await DELETE(makeRawRequest("DELETE", null));
    const setCookie = res.headers.get("set-cookie") ?? "";
    expect(setCookie.startsWith(`${SESSION_COOKIE_NAME}=`)).toBe(true);
    // The value-segment is empty: `hha_session=;`
    const valueSegment = setCookie.split(";")[0];
    expect(valueSegment).toBe(`${SESSION_COOKIE_NAME}=`);
    expect(setCookie).toContain("Max-Age=0");
  });
});
