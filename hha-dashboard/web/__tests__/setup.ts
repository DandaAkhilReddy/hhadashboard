// Vitest setup file — runs once per worker before any test.
//
// MSW + jest-dom only activate in DOM-environment tests. Tests declare DOM
// with `// @vitest-environment happy-dom` at the top of the file (vitest
// 4.x — no environmentMatchGlobs). Existing Node-only tests in this dir
// (auth/middleware/crypto/session/instrumentation) run unaffected.

import { afterAll, afterEach, beforeAll } from "vitest";

const isDom = typeof document !== "undefined";

if (isDom) {
  // jest-dom matchers (toBeInTheDocument, etc.) — async import keeps the
  // Node-environment tests from pulling DOM-only globals.
  await import("@testing-library/jest-dom/vitest");

  const { cleanup } = await import("@testing-library/react");
  const { server } = await import("./msw/server");

  beforeAll(() => {
    server.listen({ onUnhandledRequest: "error" });
  });

  afterEach(() => {
    // RTL's cleanup() unmounts every component rendered in the previous
    // test. Without this, getByText / getByRole find leftover nodes from
    // prior renders ("Found multiple elements" errors).
    cleanup();
    server.resetHandlers();
  });

  afterAll(() => {
    server.close();
  });
}
