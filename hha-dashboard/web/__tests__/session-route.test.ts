import { afterEach, beforeAll, describe, expect, it } from "vitest";

import { DELETE, POST } from "@/app/api/auth/session/route";
import { SESSION_COOKIE_NAME, decryptSession } from "@/lib/auth/session-crypto";

beforeAll(() => {
  process.env.SESSION_SECRET = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=";
});

function makeRequest(
  method: "POST" | "DELETE",
  body: unknown,
  origin = "http://localhost:3000",
  url = "http://localhost:3000/api/auth/session",
): Request {
  return new Request(url, {
    method,
    headers: {
      "Content-Type": "application/json",
      Origin: origin,
    },
    body: body === undefined ? null : JSON.stringify(body),
  });
}

afterEach(() => {
  // No-op; handlers are pure per-request.
});

describe("POST /api/auth/session", () => {
  it("sets an httpOnly cookie that round-trips through decrypt", async () => {
    const expSec = Math.floor(Date.now() / 1000) + 600;
    const res = await POST(
      makeRequest("POST", { access_token: "tok.abc.123", expires_at: expSec }),
    );
    expect(res.status).toBe(200);

    const setCookie = res.headers.get("set-cookie") ?? "";
    expect(setCookie).toMatch(new RegExp(`^${SESSION_COOKIE_NAME}=`));
    expect(setCookie).toContain("HttpOnly");
    expect(setCookie).toContain("SameSite=lax");
    expect(setCookie).toContain("Path=/");

    const cookieValue = setCookie.split(";")[0].split("=").slice(1).join("=");
    const session = await decryptSession(cookieValue);
    expect(session).toEqual({ access_token: "tok.abc.123", expires_at: expSec });
  });

  it("rejects cross-origin POSTs with 403", async () => {
    const expSec = Math.floor(Date.now() / 1000) + 600;
    const res = await POST(
      makeRequest(
        "POST",
        { access_token: "tok.abc.123", expires_at: expSec },
        "https://attacker.example.com",
      ),
    );
    expect(res.status).toBe(403);
  });

  it("rejects malformed bodies with 400", async () => {
    const res = await POST(makeRequest("POST", { access_token: 1 }));
    expect(res.status).toBe(400);
  });

  it("rejects past expires_at with 400", async () => {
    const res = await POST(makeRequest("POST", { access_token: "x", expires_at: 1 }));
    expect(res.status).toBe(400);
  });
});

describe("DELETE /api/auth/session", () => {
  it("clears the cookie via Max-Age=0", async () => {
    const res = await DELETE(makeRequest("DELETE", undefined));
    expect(res.status).toBe(200);
    const setCookie = res.headers.get("set-cookie") ?? "";
    expect(setCookie).toMatch(new RegExp(`^${SESSION_COOKIE_NAME}=`));
    expect(setCookie).toContain("Max-Age=0");
  });

  it("rejects cross-origin DELETE with 403", async () => {
    const res = await DELETE(makeRequest("DELETE", undefined, "https://attacker.example.com"));
    expect(res.status).toBe(403);
  });
});
