import { expect, test } from "@playwright/test";

/**
 * Operations board smoke (T9).
 *
 * Hits `/operations` and confirms the page lays out the FL sites table
 * from real API data (mocked at the HTTP boundary by e2e/mock-api.mjs).
 *
 * Locks two regressions:
 *   - Operations server component fails to fetch on first paint
 *   - Site list rendering breaks (e.g. data shape drift between
 *     api-client types and Pydantic schemas)
 *
 * Out-of-scope for this smoke (deferred to a follow-up): clicking into
 * an individual site's SiteCensusForm and saving — that path needs a
 * write-side mock and toast assertion which is materially more setup.
 * Captured as a TODO so future Claude or contributor can extend.
 */

test("operations page renders FL sites table from API", async ({ page }) => {
  await page.goto("/operations");

  await expect(page.getByRole("heading", { name: "Operations Board" })).toBeVisible();

  // Mocked sites both appear by name.
  await expect(page.getByRole("link", { name: /Westside Regional/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /Woodmont Hospital/ })).toBeVisible();

  // The 142 census value (seeded in mock-api.mjs) renders for Westside.
  await expect(page.getByText("142", { exact: true }).first()).toBeVisible();
});

// TODO(T9-followup): click "Westside Regional", assert SiteCensusForm
// renders, save a value, assert toast. Requires extending mock-api.mjs
// with a write-side stub (PUT /api/v1/operations/sites/{id}/census or
// similar) and a toast-locator strategy.
