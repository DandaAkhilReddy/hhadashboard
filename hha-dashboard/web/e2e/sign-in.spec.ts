import { expect, test } from "@playwright/test";

/**
 * Sign-in smoke (T9).
 *
 * In dev mode (NEXT_PUBLIC_AUTH_MODE=dev), `/auth/sign-in` should
 * auto-redirect to the requested return URL (default `/`). The Overview
 * page then renders with the page title "Overview".
 *
 * Locks two regressions:
 *   - dev-mode redirect breaking (e.g. an MSAL guard added that no longer
 *     short-circuits when MSAL isn't configured)
 *   - Overview page server-side fetches throwing on first paint
 */

test("dev-mode sign-in redirects to overview", async ({ page }) => {
  await page.goto("/auth/sign-in");

  // We don't assert the URL pattern (URL-glob matching is finicky with
  // trailing slashes); we assert the *destination state* directly. If the
  // client-side redirect from /auth/sign-in to / fired, the Overview
  // heading + a recognizable metric tile will be in the DOM. If the
  // redirect didn't fire, the page would still show "Dev mode — no
  // sign-in required." and these locators would time out, surfacing the
  // regression unambiguously.
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByText("Total FL Census Today")).toBeVisible();
});
