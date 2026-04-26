import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiGet } from "@/lib/api-fetch";
import { ApiError, ForbiddenError, UnauthenticatedError } from "@/lib/errors";

const ORIGINAL_FETCH = globalThis.fetch;

function mockFetch(response: Partial<Response>) {
  const fn = vi.fn().mockResolvedValue({
    ok: response.status ? response.status < 400 : true,
    status: response.status ?? 200,
    json: response.json ?? (async () => ({})),
    text: response.text ?? (async () => ""),
  } as Response);
  globalThis.fetch = fn as unknown as typeof globalThis.fetch;
  return fn;
}

afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
  vi.restoreAllMocks();
});

describe("apiGet", () => {
  it("attaches the resolved Bearer header", async () => {
    const fetchSpy = mockFetch({ status: 200, json: async () => ({ ok: true }) });

    await apiGet<{ ok: boolean }>("/api/v1/sites", async () => "Bearer abc");

    expect(fetchSpy).toHaveBeenCalledOnce();
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer abc");
  });

  it("attaches a sync dev-stub header", async () => {
    const fetchSpy = mockFetch({ status: 200, json: async () => ({ ok: true }) });

    await apiGet<{ ok: boolean }>("/api/v1/sites", () => "Dev admin");

    const headers = (fetchSpy.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toBe("Dev admin");
  });

  it("throws UnauthenticatedError on 401", async () => {
    mockFetch({ status: 401, text: async () => "expired" });
    await expect(apiGet("/x", async () => "Bearer stale")).rejects.toBeInstanceOf(
      UnauthenticatedError,
    );
  });

  it("throws ForbiddenError on 403", async () => {
    mockFetch({ status: 403, text: async () => "no role" });
    await expect(apiGet("/x", async () => "Bearer ok")).rejects.toBeInstanceOf(ForbiddenError);
  });

  it("throws ApiError on other 4xx/5xx", async () => {
    mockFetch({ status: 500, text: async () => "boom" });
    await expect(apiGet("/x", async () => "Bearer ok")).rejects.toBeInstanceOf(ApiError);
  });
});
