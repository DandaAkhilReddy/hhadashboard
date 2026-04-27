import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config — HHA dashboard E2E.
 *
 * Audit ticket T9. Browser-driven smoke tests that complement the unit
 * tests by exercising real Next.js rendering through a real browser.
 *
 * Two webServers are spun up:
 *   1. mock-api on MOCK_API_PORT (default 8123) — tiny Node HTTP server
 *      that returns canned responses for every API endpoint /sign-in and
 *      /operations actually call. Keeps E2E hermetic and CI-friendly
 *      (no Postgres, no Python, no FastAPI in the picture).
 *   2. next dev on 3000 — but with NEXT_PUBLIC_API_BASE_URL pointed at
 *      the mock so server components fetch against the mock.
 *
 * Chromium-only by design: cross-browser E2E was scoped out for v0.1
 * per audit ticket T9 (focus is sign-in flow + one role-gated route).
 */

const MOCK_API_PORT = Number(process.env.MOCK_API_PORT ?? 8123);
// Intentionally NOT 3000 — keeps the user's dev server (if running) untouched
// and forces Playwright to spin up its own Next dev with the mock-API base
// URL injected at process start (NEXT_PUBLIC_* vars are baked at boot).
const APP_PORT = Number(process.env.PLAYWRIGHT_APP_PORT ?? 3101);

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.ts$/,
  // 30s default — pages should always be quicker, but Next dev HMR can
  // occasionally stall the first render. Don't set this lower in CI.
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false, // serial — single Next dev shared across specs
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",

  use: {
    baseURL: `http://localhost:${APP_PORT}`,
    trace: "on-first-retry",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: [
    {
      command: "node e2e/mock-api.mjs",
      port: MOCK_API_PORT,
      reuseExistingServer: !process.env.CI,
      env: { MOCK_API_PORT: String(MOCK_API_PORT) },
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: `npx next dev -p ${APP_PORT}`,
      port: APP_PORT,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000, // first Next dev compile on cold cache is slow
      env: {
        NEXT_PUBLIC_API_BASE_URL: `http://localhost:${MOCK_API_PORT}`,
        // Ensure dev mode is active so /auth/sign-in redirects.
        NEXT_PUBLIC_AUTH_MODE: "dev",
      },
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
