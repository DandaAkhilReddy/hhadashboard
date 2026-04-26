/**
 * Server-page auth helper.
 *
 * Wraps a fetch thunk so that an UnauthenticatedError (thrown by api-client
 * when the session cookie is missing/expired and we're not in dev mode)
 * triggers a redirect to /auth/sign-in. Any other error bubbles unchanged.
 *
 * Usage:
 *   const [today, aging] = await fetchOrSignIn(() =>
 *     Promise.all([api.financeToday(), api.arAging()]),
 *   );
 *
 * Pass `returnTo` if you want post-login to land on a deep page instead
 * of "/" — typically the path of the page calling this helper.
 */

import { redirect } from "next/navigation";
import { UnauthenticatedError } from "../errors";

export async function fetchOrSignIn<T>(fn: () => Promise<T>, returnTo?: string): Promise<T> {
  try {
    return await fn();
  } catch (err) {
    if (err instanceof UnauthenticatedError) {
      const qs = returnTo ? `?return=${encodeURIComponent(returnTo)}` : "";
      redirect(`/auth/sign-in${qs}`);
    }
    throw err;
  }
}
