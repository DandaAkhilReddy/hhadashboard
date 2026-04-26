import { beforeAll, describe, expect, it } from "vitest";

import {
  type Session,
  decryptSession,
  encryptSession,
  isSessionExpired,
} from "@/lib/auth/session-crypto";

beforeAll(() => {
  // Stable 32-byte test key (NEVER use in real env — this is in source).
  process.env.SESSION_SECRET = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=";
});

describe("session-crypto", () => {
  it("encrypts then decrypts a session round-trip", async () => {
    const session: Session = {
      access_token: "eyJhbGciOiJSUzI1NiJ9.body.sig",
      expires_at: Math.floor(Date.now() / 1000) + 3600,
    };

    const blob = await encryptSession(session);
    expect(blob.length).toBeGreaterThan(0);
    expect(blob).not.toContain(session.access_token);

    const decrypted = await decryptSession(blob);
    expect(decrypted).toEqual(session);
  });

  it("returns null for tampered ciphertext", async () => {
    const session: Session = {
      access_token: "abc.def.ghi",
      expires_at: Math.floor(Date.now() / 1000) + 3600,
    };
    const blob = await encryptSession(session);
    const tampered = `${blob.slice(0, -2)}aa`;
    expect(await decryptSession(tampered)).toBeNull();
  });

  it("returns null for total garbage", async () => {
    expect(await decryptSession("not-a-real-blob")).toBeNull();
  });

  it("isSessionExpired flips at the boundary", () => {
    const now = 1_000_000;
    expect(isSessionExpired({ access_token: "x", expires_at: now - 1 }, now)).toBe(true);
    expect(isSessionExpired({ access_token: "x", expires_at: now }, now)).toBe(true);
    expect(isSessionExpired({ access_token: "x", expires_at: now + 1 }, now)).toBe(false);
  });
});
