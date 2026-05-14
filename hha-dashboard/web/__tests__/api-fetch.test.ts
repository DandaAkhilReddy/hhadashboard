import { afterEach, describe, expect, it, vi } from "vitest";

import { apiGet, apiPostFormData, apiPostJson } from "@/lib/api-fetch";
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

  it("uses GET method when calling apiGet (no body)", async () => {
    const fetchSpy = mockFetch({ status: 200, json: async () => ({}) });
    await apiGet("/x", async () => "Bearer ok");
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("GET");
    expect(init.body).toBeUndefined();
  });

  it("attaches cache:'no-store' so server components don't reuse a stale fetch cache", async () => {
    const fetchSpy = mockFetch({ status: 200, json: async () => ({}) });
    await apiGet("/x", async () => "Bearer ok");
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(init.cache).toBe("no-store");
  });
});

describe("apiPostJson", () => {
  it("posts a JSON body with Content-Type and resolves the JSON response", async () => {
    const fetchSpy = mockFetch({
      status: 200,
      json: async () => ({ id: 42 }),
    });

    const out = await apiPostJson<{ id: number }>(
      "/api/v1/entries",
      { site_id: 1, census: 100 },
      async () => "Bearer x",
    );

    expect(out).toEqual({ id: 42 });
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ site_id: 1, census: 100 }));
    const headers = init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers.Authorization).toBe("Bearer x");
  });

  it("propagates ApiError on non-OK status (caller decides what to do)", async () => {
    mockFetch({ status: 422, text: async () => "bad body" });
    await expect(
      apiPostJson("/api/v1/entries", { x: 1 }, async () => "Bearer y"),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

describe("apiPostFormData", () => {
  it("posts a FormData body WITHOUT a Content-Type header so the browser sets the boundary", async () => {
    const fetchSpy = mockFetch({ status: 200, json: async () => ({ uploaded: true }) });

    const fd = new FormData();
    fd.append("file", new Blob(["x"]), "x.pdf");

    await apiPostFormData<{ uploaded: boolean }>("/api/v1/uploads", fd, async () => "Bearer x");

    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.body).toBe(fd);
    const headers = init.headers as Record<string, string>;
    // No Content-Type — the browser's multipart/form-data; boundary=...
    // header would otherwise get overwritten and the upload would fail.
    expect(headers["Content-Type"]).toBeUndefined();
    expect(headers.Authorization).toBe("Bearer x");
  });
});
