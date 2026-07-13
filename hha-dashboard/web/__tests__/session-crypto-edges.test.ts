// @vitest-environment node
//
// Extra coverage for lib/auth/session-crypto.ts that the original
// session-crypto.test.ts skips:
//
//   - SESSION_SECRET env validation (missing -> throws)
//   - SESSION_SECRET wrong length (< 32 bytes -> throws)
//   - base64 padding + URL-safe variant decode
//   - _keyPromise singleton caching (second call doesn't re-importKey)
//   - decryptSession bytes.length < 13 short-circuit (no IV/ct split possible)
//   - decryptSession JSON-but-wrong-shape rejection variants
//     (missing keys / wrong field types)
//   - SESSION_COOKIE_NAME constant pin
//
// These branches are unreachable from the round-trip happy path the
// existing test exercises.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SESSION_COOKIE_NAME } from "@/lib/auth/session-crypto";

const VALID_SECRET = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=";

beforeEach(() => {
  // Each test gets a clean module cache so the _keyPromise singleton +
  // env-var read both happen fresh.
  vi.resetModules();
});

afterEach(() => {
  // biome-ignore lint/performance/noDelete: must actually unset, not coerce to "undefined"
  delete process.env.SESSION_SECRET;
});

// ============================================================================
// SESSION_COOKIE_NAME — constant pin
// ============================================================================

describe("SESSION_COOKIE_NAME", () => {
  it("is the documented 'hha_session' string", () => {
    // Middleware, /api/auth/session route handler, and the lib all
    // reference this name — pin it so a sneaky rename doesn't slip in.
    expect(SESSION_COOKIE_NAME).toBe("hha_session");
  });
});

// ============================================================================
// SESSION_SECRET env validation
// ============================================================================

describe("SESSION_SECRET validation", () => {
  it("throws when SESSION_SECRET is unset", async () => {
    // biome-ignore lint/performance/noDelete: must actually unset, not coerce to "undefined"
    delete process.env.SESSION_SECRET;
    const { encryptSession } = await import("@/lib/auth/session-crypto");
    await expect(encryptSession({ access_token: "x", expires_at: 1 })).rejects.toThrow(
      /SESSION_SECRET env var is required/,
    );
  });

  it("throws when SESSION_SECRET is empty string (falsy)", async () => {
    process.env.SESSION_SECRET = "";
    const { encryptSession } = await import("@/lib/auth/session-crypto");
    await expect(encryptSession({ access_token: "x", expires_at: 1 })).rejects.toThrow(
      /SESSION_SECRET env var is required/,
    );
  });

  it("throws when SESSION_SECRET decodes to fewer than 32 bytes", async () => {
    // "AAEC" base64-decodes to 3 bytes — not the 32 the AES-256 key needs.
    process.env.SESSION_SECRET = "AAEC";
    const { encryptSession } = await import("@/lib/auth/session-crypto");
    await expect(encryptSession({ access_token: "x", expires_at: 1 })).rejects.toThrow(
      /SESSION_SECRET must decode to 32 bytes/,
    );
  });

  it("throws when SESSION_SECRET decodes to more than 32 bytes", async () => {
    // 48 zero bytes base64.
    process.env.SESSION_SECRET = Buffer.alloc(48, 0).toString("base64");
    const { encryptSession } = await import("@/lib/auth/session-crypto");
    await expect(encryptSession({ access_token: "x", expires_at: 1 })).rejects.toThrow(
      /SESSION_SECRET must decode to 32 bytes \(got 48\)/,
    );
  });
});

// ============================================================================
// base64 URL-safe variant decode
// ============================================================================

describe("base64ToBytes — URL-safe variant", () => {
  it("accepts a URL-safe (-/_) variant of the secret", async () => {
    // 32 bytes of 0xff base64-encode to a string containing many '/'
    // characters — the URL-safe variant replaces those with '_'. The lib
    // must accept both forms (middleware tokens travel in URL-safe form).
    const allOnesStd = Buffer.alloc(32, 0xff).toString("base64");
    const allOnesUrlSafe = allOnesStd.replace(/\+/g, "-").replace(/\//g, "_");
    expect(allOnesUrlSafe).not.toBe(allOnesStd); // sanity: actually different
    expect(allOnesUrlSafe).toContain("_"); // URL-safe '/' replacement
    process.env.SESSION_SECRET = allOnesUrlSafe;

    const { encryptSession, decryptSession } = await import("@/lib/auth/session-crypto");
    const session = { access_token: "tok", expires_at: 999 };
    const blob = await encryptSession(session);
    expect(await decryptSession(blob)).toEqual(session);
  });

  it("accepts a secret without trailing padding", async () => {
    // The standard secret has '=' padding; the lib re-pads under the hood
    // to handle both forms.
    process.env.SESSION_SECRET = VALID_SECRET.replace(/=+$/, "");
    const { encryptSession, decryptSession } = await import("@/lib/auth/session-crypto");
    const session = { access_token: "tok", expires_at: 42 };
    const blob = await encryptSession(session);
    expect(await decryptSession(blob)).toEqual(session);
  });
});

// ============================================================================
// _keyPromise caching — second call must not re-importKey
// ============================================================================

describe("getKey caching (_keyPromise singleton)", () => {
  it("imports the key exactly once across multiple encryptSession calls", async () => {
    process.env.SESSION_SECRET = VALID_SECRET;

    // Spy on crypto.subtle.importKey BEFORE importing the module so the
    // first internal call hits the spy.
    const importKeySpy = vi.spyOn(crypto.subtle, "importKey");
    importKeySpy.mockClear();

    const { encryptSession } = await import("@/lib/auth/session-crypto");

    await encryptSession({ access_token: "a", expires_at: 1 });
    await encryptSession({ access_token: "b", expires_at: 2 });
    await encryptSession({ access_token: "c", expires_at: 3 });

    expect(importKeySpy).toHaveBeenCalledTimes(1);
    importKeySpy.mockRestore();
  });

  it("decryptSession reuses the same cached key as encryptSession", async () => {
    process.env.SESSION_SECRET = VALID_SECRET;
    const importKeySpy = vi.spyOn(crypto.subtle, "importKey");
    importKeySpy.mockClear();

    const { encryptSession, decryptSession } = await import("@/lib/auth/session-crypto");

    const blob = await encryptSession({ access_token: "x", expires_at: 7 });
    await decryptSession(blob);
    await decryptSession(blob);

    expect(importKeySpy).toHaveBeenCalledTimes(1);
    importKeySpy.mockRestore();
  });
});

// ============================================================================
// decryptSession — short-circuit + JSON-shape rejection
// ============================================================================

describe("decryptSession — defensive branches", () => {
  beforeEach(() => {
    process.env.SESSION_SECRET = VALID_SECRET;
  });

  it("returns null for an empty string (length < 13)", async () => {
    const { decryptSession } = await import("@/lib/auth/session-crypto");
    expect(await decryptSession("")).toBeNull();
  });

  it("returns null for a blob shorter than 13 bytes after decode", async () => {
    // 8 zero bytes base64 -> too small to contain even the 12-byte IV.
    const { decryptSession } = await import("@/lib/auth/session-crypto");
    const tooShort = Buffer.alloc(8, 0).toString("base64url");
    expect(await decryptSession(tooShort)).toBeNull();
  });

  it("returns null when ciphertext is exactly 12 bytes (no auth tag)", async () => {
    // 12 bytes = just an IV, no ciphertext + GCM tag at all.
    const { decryptSession } = await import("@/lib/auth/session-crypto");
    const ivOnly = Buffer.alloc(12, 0).toString("base64url");
    expect(await decryptSession(ivOnly)).toBeNull();
  });

  it("returns null for random gibberish that base64-decodes but fails AEAD", async () => {
    const { decryptSession } = await import("@/lib/auth/session-crypto");
    const fake = Buffer.alloc(64, 0xff).toString("base64url");
    expect(await decryptSession(fake)).toBeNull();
  });

  it("returns null when plaintext is valid JSON but not an object", async () => {
    // To exercise this branch we have to mint a real ciphertext whose
    // plaintext is the string '"hello"' (a top-level JSON string).
    const { encryptSession, decryptSession } = await import("@/lib/auth/session-crypto");

    // We can't pass a non-Session to encryptSession() (TS would refuse),
    // so reach behind the API: build it ourselves using the same Web
    // Crypto primitive. Use a private-but-stable pattern: encrypt a
    // legit session, then re-encrypt a malformed payload using the same
    // key. Easier path: monkey-patch JSON.stringify for one call.
    const real = JSON.stringify;
    let calledOnce = false;
    vi.spyOn(JSON, "stringify").mockImplementation((value: unknown) => {
      if (!calledOnce) {
        calledOnce = true;
        return real("just-a-string"); // top-level JSON string
      }
      return real(value);
    });
    const blob = await encryptSession({ access_token: "x", expires_at: 1 });
    const decrypted = await decryptSession(blob);
    vi.restoreAllMocks();
    expect(decrypted).toBeNull();
  });

  it.each([
    [{ expires_at: 1 }, "access_token missing"],
    [{ access_token: "x" }, "expires_at missing"],
    [{ access_token: 42, expires_at: 1 }, "access_token wrong type"],
    [{ access_token: "x", expires_at: "soon" }, "expires_at wrong type"],
    [{ access_token: "x", expires_at: null }, "expires_at null"],
    [{ access_token: null, expires_at: 1 }, "access_token null"],
  ])("returns null when plaintext JSON has %s", async (payload, _label) => {
    const { encryptSession, decryptSession } = await import("@/lib/auth/session-crypto");

    // Use the same monkey-patch trick to slip a non-Session payload past
    // the encryptSession() type guard.
    const real = JSON.stringify;
    let calledOnce = false;
    vi.spyOn(JSON, "stringify").mockImplementation((value: unknown) => {
      if (!calledOnce) {
        calledOnce = true;
        return real(payload);
      }
      return real(value);
    });

    const blob = await encryptSession({ access_token: "x", expires_at: 1 });
    const decrypted = await decryptSession(blob);
    vi.restoreAllMocks();
    expect(decrypted).toBeNull();
  });

  it("accepts a well-formed payload with extra keys (type-guard ignores extras)", async () => {
    // The shape guard checks the two required keys ARE present and the
    // right type — it does NOT reject extra keys. Re-confirming this lets
    // the server attach forward-compatible fields later without breaking
    // existing cookies.
    const { encryptSession, decryptSession } = await import("@/lib/auth/session-crypto");

    const real = JSON.stringify;
    let calledOnce = false;
    vi.spyOn(JSON, "stringify").mockImplementation((value: unknown) => {
      if (!calledOnce) {
        calledOnce = true;
        return real({ access_token: "x", expires_at: 100, extra: "ok" });
      }
      return real(value);
    });

    const blob = await encryptSession({ access_token: "x", expires_at: 100 });
    const decrypted = await decryptSession(blob);
    vi.restoreAllMocks();

    expect(decrypted).not.toBeNull();
    expect(decrypted?.access_token).toBe("x");
    expect(decrypted?.expires_at).toBe(100);
  });
});

// ============================================================================
// isSessionExpired — default `nowSec` branch (uses Date.now() when omitted)
// ============================================================================

describe("isSessionExpired — default now", () => {
  beforeEach(() => {
    process.env.SESSION_SECRET = VALID_SECRET;
  });

  it("uses Date.now() when nowSec is omitted", async () => {
    const { isSessionExpired } = await import("@/lib/auth/session-crypto");
    // expires_at far in the past -> expired
    expect(isSessionExpired({ access_token: "x", expires_at: 1 })).toBe(true);
    // expires_at far in the future -> not expired
    const farFuture = Math.floor(Date.now() / 1000) + 86_400;
    expect(isSessionExpired({ access_token: "x", expires_at: farFuture })).toBe(false);
  });
});

// ============================================================================
// encryptSession — every call produces a fresh IV (no nonce reuse)
// ============================================================================

describe("encryptSession — nonce uniqueness", () => {
  beforeEach(() => {
    process.env.SESSION_SECRET = VALID_SECRET;
  });

  it("produces a different ciphertext for the same plaintext on each call", async () => {
    // AES-GCM with nonce reuse is catastrophically broken — the IV MUST be
    // randomly generated per encryption. Two calls with the same session
    // must produce different blobs.
    const { encryptSession } = await import("@/lib/auth/session-crypto");
    const session = { access_token: "deterministic", expires_at: 100 };
    const a = await encryptSession(session);
    const b = await encryptSession(session);
    const c = await encryptSession(session);
    expect(a).not.toBe(b);
    expect(b).not.toBe(c);
    expect(a).not.toBe(c);
  });

  it("produces a blob with no obvious plaintext leakage", async () => {
    const { encryptSession } = await import("@/lib/auth/session-crypto");
    const session = { access_token: "SUPER_SECRET_TOKEN_12345", expires_at: 100 };
    const blob = await encryptSession(session);
    expect(blob).not.toContain("SUPER_SECRET");
    expect(blob).not.toContain("access_token");
  });
});
