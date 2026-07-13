// MSW request handlers for unit-test fetch interception.
//
// Each handler returns a typed response derived from `lib/api-types.ts`
// (the openapi-typescript output). Adding a new endpoint means:
//   1. Regenerate api-types (`npm run gen-types`)
//   2. Add a handler here keyed off the path
//   3. Use `paths["/your/path"]["get"]["responses"]["200"]["content"]["application/json"]`
//      as the response type — that locks the mock to the server contract.
//
// For Playwright E2E this file is NOT used — `e2e/mock-api.mjs` continues
// to serve the standalone HTTP mock. The two surfaces are kept in sync by
// the same `paths` interface, so type drift surfaces at compile time.

import type { paths } from "@/lib/api-types";
import { http, HttpResponse } from "msw";

type SitesTodayResponse =
  paths["/api/v1/operations/sites-today"]["get"]["responses"]["200"]["content"]["application/json"];

type HealthResponse = paths["/health"]["get"]["responses"]["200"]["content"]["application/json"];

// Base URL is read from process.env at handler-build time so tests can
// override per environment (vitest.setup.ts sets a deterministic value).
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * Default handlers — happy-path 200 responses with empty/minimal payloads.
 * Per-test overrides via `server.use(...)` for error paths or specific data.
 */
export const handlers = [
  http.get(`${API_BASE}/health`, () => HttpResponse.json({ status: "ok" } as HealthResponse)),

  http.get(`${API_BASE}/api/v1/operations/sites-today`, () =>
    HttpResponse.json([] as SitesTodayResponse),
  ),
];
