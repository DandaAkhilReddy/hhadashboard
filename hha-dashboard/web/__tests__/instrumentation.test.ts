/**
 * instrumentation.ts boot-time SESSION_SECRET validation.
 *
 * Audit ticket T4 lock-in: ensures a non-dev deploy without
 * SESSION_SECRET (or with a malformed one) refuses to boot.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const ENV_KEYS = ["NEXT_RUNTIME", "NEXT_PUBLIC_AUTH_MODE", "SESSION_SECRET"] as const;

function snapshotEnv(): Record<string, string | undefined> {
  return Object.fromEntries(ENV_KEYS.map((k) => [k, process.env[k]]));
}

function restoreEnv(saved: Record<string, string | undefined>): void {
  for (const k of ENV_KEYS) {
    if (saved[k] === undefined) Reflect.deleteProperty(process.env, k);
    else process.env[k] = saved[k];
  }
}

async function loadRegister(): Promise<() => Promise<void>> {
  vi.resetModules();
  const mod = await import("../instrumentation");
  return mod.register;
}

describe("instrumentation.register", () => {
  let saved: Record<string, string | undefined>;

  beforeEach(() => {
    saved = snapshotEnv();
  });

  afterEach(() => {
    restoreEnv(saved);
  });

  it("is a no-op when not running in the nodejs runtime", async () => {
    process.env.NEXT_RUNTIME = "edge";
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    Reflect.deleteProperty(process.env, "SESSION_SECRET");
    const register = await loadRegister();
    await expect(register()).resolves.toBeUndefined();
  });

  it("is a no-op in dev mode even with no SESSION_SECRET", async () => {
    process.env.NEXT_RUNTIME = "nodejs";
    process.env.NEXT_PUBLIC_AUTH_MODE = "dev";
    Reflect.deleteProperty(process.env, "SESSION_SECRET");
    const register = await loadRegister();
    await expect(register()).resolves.toBeUndefined();
  });

  it("throws in prod mode with no SESSION_SECRET", async () => {
    process.env.NEXT_RUNTIME = "nodejs";
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    Reflect.deleteProperty(process.env, "SESSION_SECRET");
    const register = await loadRegister();
    await expect(register()).rejects.toThrow(/SESSION_SECRET env var is required/);
  });

  it("throws when SESSION_SECRET decodes to wrong byte length", async () => {
    process.env.NEXT_RUNTIME = "nodejs";
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    process.env.SESSION_SECRET = "dGhpcy1pcy10b28tc2hvcnQ=";
    const register = await loadRegister();
    await expect(register()).rejects.toThrow(/must decode to 32 bytes/);
  });

  it("succeeds with a valid 32-byte base64 SESSION_SECRET", async () => {
    process.env.NEXT_RUNTIME = "nodejs";
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    process.env.SESSION_SECRET = Buffer.from(new Uint8Array(32)).toString("base64");
    const register = await loadRegister();
    await expect(register()).resolves.toBeUndefined();
  });
});
