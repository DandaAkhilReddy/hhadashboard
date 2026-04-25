/**
 * Environment-agnostic fetcher for the FastAPI backend.
 *
 * Same module is used by both server-side (api-client.ts) and browser-side
 * (api-browser.ts) wrappers. The auth header is injected by the caller —
 * the fetcher itself knows nothing about cookies, MSAL, or dev stubs.
 *
 * 401 → UnauthenticatedError (server pages catch this and redirect)
 * 403 → ForbiddenError
 * other 4xx/5xx → ApiError
 */

import { ApiError, ForbiddenError, UnauthenticatedError } from "./errors";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type GetAuthHeader = () => Promise<string> | string;

type FetchOptions = {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: BodyInit | null;
  headers?: Record<string, string>;
};

async function resolveAuth(getAuthHeader: GetAuthHeader): Promise<string> {
  const v = getAuthHeader();
  return v instanceof Promise ? await v : v;
}

export async function apiFetch<T>(
  path: string,
  options: FetchOptions,
  getAuthHeader: GetAuthHeader,
): Promise<T> {
  const auth = await resolveAuth(getAuthHeader);
  const res = await fetch(`${API_BASE}${path}`, {
    method: options.method ?? "GET",
    headers: {
      Authorization: auth,
      ...(options.headers ?? {}),
    },
    body: options.body,
    cache: "no-store",
  });

  if (res.ok) {
    return (await res.json()) as T;
  }

  const bodyText = await res.text();
  if (res.status === 401) throw new UnauthenticatedError(path, bodyText);
  if (res.status === 403) throw new ForbiddenError(path, bodyText);
  throw new ApiError(res.status, path, bodyText);
}

export async function apiGet<T>(path: string, getAuthHeader: GetAuthHeader): Promise<T> {
  return apiFetch<T>(path, { method: "GET" }, getAuthHeader);
}

export async function apiPostJson<T>(
  path: string,
  body: unknown,
  getAuthHeader: GetAuthHeader,
): Promise<T> {
  return apiFetch<T>(
    path,
    {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    },
    getAuthHeader,
  );
}

export async function apiPostFormData<T>(
  path: string,
  formData: FormData,
  getAuthHeader: GetAuthHeader,
): Promise<T> {
  return apiFetch<T>(path, { method: "POST", body: formData }, getAuthHeader);
}
