// @vitest-environment happy-dom
//
// MSAL config helper tests. The module reads NEXT_PUBLIC_* env vars at
// import time and caches the PublicClientApplication singleton, so each
// test mutates `process.env` BEFORE `vi.resetModules()` + dynamic import
// to get a fresh module state.

import { beforeEach, describe, expect, it, vi } from "vitest";

// Mock @azure/msal-browser so PublicClientApplication doesn't try to
// hit the network / read window storage during import.
const initializeMock = vi.fn();
const ctorMock = vi.fn();

vi.mock("@azure/msal-browser", () => {
  class FakePublicClientApplication {
    initialize = initializeMock;
    constructor(config: unknown) {
      ctorMock(config);
    }
  }
  return { PublicClientApplication: FakePublicClientApplication };
});

const ENV_VARS = [
  "NEXT_PUBLIC_AUTH_MODE",
  "NEXT_PUBLIC_AZURE_TENANT_ID",
  "NEXT_PUBLIC_AZURE_WEB_CLIENT_ID",
  "NEXT_PUBLIC_AZURE_API_CLIENT_ID",
] as const;

function clearEnv(): void {
  for (const key of ENV_VARS) {
    delete process.env[key];
  }
}

async function freshImport() {
  vi.resetModules();
  return import("@/lib/auth/msal-config");
}

describe("isMsalConfigured()", () => {
  beforeEach(() => {
    clearEnv();
    initializeMock.mockReset().mockResolvedValue(undefined);
    ctorMock.mockReset();
  });

  it("returns false when no MSAL env vars are set", async () => {
    const { isMsalConfigured } = await freshImport();
    expect(isMsalConfigured()).toBe(false);
  });

  it("returns false when only TENANT_ID is set", async () => {
    process.env.NEXT_PUBLIC_AZURE_TENANT_ID = "tenant-uuid";
    const { isMsalConfigured } = await freshImport();
    expect(isMsalConfigured()).toBe(false);
  });

  it("returns false when WEB_CLIENT_ID is missing", async () => {
    process.env.NEXT_PUBLIC_AZURE_TENANT_ID = "t";
    process.env.NEXT_PUBLIC_AZURE_API_CLIENT_ID = "api";
    const { isMsalConfigured } = await freshImport();
    expect(isMsalConfigured()).toBe(false);
  });

  it("returns true when all three required IDs are set", async () => {
    process.env.NEXT_PUBLIC_AZURE_TENANT_ID = "t";
    process.env.NEXT_PUBLIC_AZURE_WEB_CLIENT_ID = "web";
    process.env.NEXT_PUBLIC_AZURE_API_CLIENT_ID = "api";
    const { isMsalConfigured } = await freshImport();
    expect(isMsalConfigured()).toBe(true);
  });
});

describe("apiScope()", () => {
  beforeEach(() => {
    clearEnv();
    initializeMock.mockReset().mockResolvedValue(undefined);
    ctorMock.mockReset();
  });

  it("returns empty string when API_CLIENT_ID is unset", async () => {
    const { apiScope } = await freshImport();
    expect(apiScope()).toBe("");
  });

  it("returns the documented api://<id>/access_as_user shape when set", async () => {
    process.env.NEXT_PUBLIC_AZURE_API_CLIENT_ID = "api-uuid-1234";
    const { apiScope } = await freshImport();
    expect(apiScope()).toBe("api://api-uuid-1234/access_as_user");
  });
});

describe("loginScopes", () => {
  it("exposes the documented OIDC scope set as a frozen tuple", async () => {
    const { loginScopes } = await freshImport();
    expect(loginScopes).toEqual(["openid", "profile", "email"]);
  });
});

describe("getMsalInstance()", () => {
  beforeEach(() => {
    clearEnv();
    initializeMock.mockReset().mockResolvedValue(undefined);
    ctorMock.mockReset();
  });

  it("returns null when MSAL is not configured", async () => {
    const { getMsalInstance } = await freshImport();
    expect(getMsalInstance()).toBeNull();
    expect(ctorMock).not.toHaveBeenCalled();
  });

  it("constructs PublicClientApplication exactly once (singleton)", async () => {
    process.env.NEXT_PUBLIC_AZURE_TENANT_ID = "tenant-id";
    process.env.NEXT_PUBLIC_AZURE_WEB_CLIENT_ID = "web-id";
    process.env.NEXT_PUBLIC_AZURE_API_CLIENT_ID = "api-id";

    const { getMsalInstance } = await freshImport();
    const first = getMsalInstance();
    const second = getMsalInstance();

    expect(first).not.toBeNull();
    expect(first).toBe(second);
    expect(ctorMock).toHaveBeenCalledTimes(1);
  });

  it("passes the documented config shape into PublicClientApplication", async () => {
    process.env.NEXT_PUBLIC_AZURE_TENANT_ID = "tenant-x";
    process.env.NEXT_PUBLIC_AZURE_WEB_CLIENT_ID = "web-y";
    process.env.NEXT_PUBLIC_AZURE_API_CLIENT_ID = "api-z";

    const { getMsalInstance } = await freshImport();
    getMsalInstance();

    expect(ctorMock).toHaveBeenCalledTimes(1);
    const config = ctorMock.mock.calls[0]?.[0] as {
      auth: { clientId: string; authority: string; redirectUri: string };
      cache: { cacheLocation: string };
    };
    expect(config.auth.clientId).toBe("web-y");
    expect(config.auth.authority).toBe("https://login.microsoftonline.com/tenant-x");
    expect(config.auth.redirectUri).toContain("/auth/callback");
    expect(config.cache.cacheLocation).toBe("sessionStorage");
  });
});

describe("ensureMsalInitialized()", () => {
  beforeEach(() => {
    clearEnv();
    initializeMock.mockReset().mockResolvedValue(undefined);
    ctorMock.mockReset();
  });

  it("resolves immediately without calling instance.initialize when not configured", async () => {
    const { ensureMsalInitialized } = await freshImport();
    await ensureMsalInitialized();
    expect(initializeMock).not.toHaveBeenCalled();
  });

  it("calls instance.initialize exactly once when configured (even across multiple awaits)", async () => {
    process.env.NEXT_PUBLIC_AZURE_TENANT_ID = "t";
    process.env.NEXT_PUBLIC_AZURE_WEB_CLIENT_ID = "w";
    process.env.NEXT_PUBLIC_AZURE_API_CLIENT_ID = "a";

    const { ensureMsalInitialized } = await freshImport();
    await ensureMsalInitialized();
    await ensureMsalInitialized();
    await ensureMsalInitialized();

    // Singleton init promise — only one underlying call regardless of
    // how many places await the promise.
    expect(initializeMock).toHaveBeenCalledTimes(1);
  });
});
