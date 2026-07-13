// Server-side session reader tests. Mocks next/headers cookies + the
// session-crypto decrypt/expire helpers so each test controls the
// cookie state and the resulting auth path.

import { beforeEach, describe, expect, it, vi } from "vitest";

const getCookieMock = vi.fn();
const decryptSessionMock = vi.fn();
const isSessionExpiredMock = vi.fn();

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => getCookieMock(name),
  }),
}));

vi.mock("@/lib/auth/session-crypto", () => ({
  SESSION_COOKIE_NAME: "hha_session",
  decryptSession: (raw: string) => decryptSessionMock(raw),
  isSessionExpired: (session: unknown) => isSessionExpiredMock(session),
}));

async function freshImport() {
  vi.resetModules();
  return import("@/lib/auth/server-session");
}

describe("getServerAuthHeader", () => {
  beforeEach(() => {
    getCookieMock.mockReset();
    decryptSessionMock.mockReset();
    isSessionExpiredMock.mockReset();
    // biome-ignore lint/performance/noDelete: env-default ?? requires actual undefined, not ""
    delete process.env.NEXT_PUBLIC_AUTH_MODE;
  });

  it("returns 'Bearer <jwt>' when a valid session cookie decrypts and is not expired", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    getCookieMock.mockReturnValue({ value: "encrypted-blob" });
    decryptSessionMock.mockResolvedValue({ access_token: "jwt-xyz", expires_at: 9_999_999_999 });
    isSessionExpiredMock.mockReturnValue(false);

    const { getServerAuthHeader } = await freshImport();
    const result = await getServerAuthHeader();

    expect(result).toBe("Bearer jwt-xyz");
    expect(getCookieMock).toHaveBeenCalledWith("hha_session");
    expect(decryptSessionMock).toHaveBeenCalledWith("encrypted-blob");
  });

  it("falls through to 'Dev admin' when no cookie + dev mode", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "dev";
    getCookieMock.mockReturnValue(undefined);

    const { getServerAuthHeader } = await freshImport();
    expect(await getServerAuthHeader()).toBe("Dev admin");
    // Never touched the decrypt helpers
    expect(decryptSessionMock).not.toHaveBeenCalled();
  });

  it("defaults to dev mode when NEXT_PUBLIC_AUTH_MODE is unset", async () => {
    // Module reads `process.env.NEXT_PUBLIC_AUTH_MODE ?? "dev"` at top level.
    // biome-ignore lint/performance/noDelete: env-default ?? requires actual undefined, not ""
    delete process.env.NEXT_PUBLIC_AUTH_MODE;
    getCookieMock.mockReturnValue(undefined);

    const { getServerAuthHeader } = await freshImport();
    expect(await getServerAuthHeader()).toBe("Dev admin");
  });

  it("throws UnauthenticatedError when no cookie + non-dev mode", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    getCookieMock.mockReturnValue(undefined);

    const { getServerAuthHeader } = await freshImport();

    await expect(getServerAuthHeader()).rejects.toMatchObject({
      name: "UnauthenticatedError",
      status: 401,
      path: "/api/auth/session",
    });
  });

  it("falls through to dev fallback when decrypt returns null (corrupted cookie + dev)", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "dev";
    getCookieMock.mockReturnValue({ value: "garbage" });
    decryptSessionMock.mockResolvedValue(null);

    const { getServerAuthHeader } = await freshImport();
    expect(await getServerAuthHeader()).toBe("Dev admin");
  });

  it("throws UnauthenticatedError when decrypt returns null in non-dev mode", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    getCookieMock.mockReturnValue({ value: "garbage" });
    decryptSessionMock.mockResolvedValue(null);

    const { getServerAuthHeader } = await freshImport();
    await expect(getServerAuthHeader()).rejects.toMatchObject({
      name: "UnauthenticatedError",
      status: 401,
    });
  });

  it("falls through to dev fallback when session is expired + dev", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "dev";
    getCookieMock.mockReturnValue({ value: "blob" });
    decryptSessionMock.mockResolvedValue({
      access_token: "stale",
      expires_at: 100,
    });
    isSessionExpiredMock.mockReturnValue(true);

    const { getServerAuthHeader } = await freshImport();
    expect(await getServerAuthHeader()).toBe("Dev admin");
  });

  it("throws UnauthenticatedError when session is expired + non-dev", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    getCookieMock.mockReturnValue({ value: "blob" });
    decryptSessionMock.mockResolvedValue({
      access_token: "stale",
      expires_at: 100,
    });
    isSessionExpiredMock.mockReturnValue(true);

    const { getServerAuthHeader } = await freshImport();
    await expect(getServerAuthHeader()).rejects.toMatchObject({
      name: "UnauthenticatedError",
      status: 401,
    });
  });

  it("calls isSessionExpired with the decrypted session payload", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "prod";
    const session = { access_token: "jwt", expires_at: 9_999_999_999 };
    getCookieMock.mockReturnValue({ value: "blob" });
    decryptSessionMock.mockResolvedValue(session);
    isSessionExpiredMock.mockReturnValue(false);

    const { getServerAuthHeader } = await freshImport();
    await getServerAuthHeader();

    expect(isSessionExpiredMock).toHaveBeenCalledWith(session);
  });
});
