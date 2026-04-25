/**
 * Server-side session reader.
 *
 * Reads the encrypted `hha_session` cookie set by /api/auth/session, decrypts
 * it, and returns `Authorization: Bearer <jwt>` for outgoing API calls.
 *
 * Dev fallback: when NEXT_PUBLIC_AUTH_MODE=dev and no cookie is present,
 * returns `Authorization: Dev admin` so local dev keeps working without
 * Azure setup. Outside dev mode with no cookie, throws UnauthenticatedError
 * which the page catches and converts to redirect('/auth/sign-in').
 *
 * This module is Node-only — it imports `next/headers`, which is statically
 * disallowed in client bundles. Never import from this in a "use client" file.
 */

import { cookies } from "next/headers";
import { decryptSession, SESSION_COOKIE_NAME, isSessionExpired } from "./session-crypto";
import { UnauthenticatedError } from "../errors";

const AUTH_MODE = process.env.NEXT_PUBLIC_AUTH_MODE ?? "dev";

export async function getServerAuthHeader(): Promise<string> {
  const store = await cookies();
  const raw = store.get(SESSION_COOKIE_NAME)?.value;

  if (raw) {
    const session = await decryptSession(raw);
    if (session && !isSessionExpired(session)) {
      return `Bearer ${session.access_token}`;
    }
    // Expired or undecryptable → fall through to dev fallback / 401.
  }

  if (AUTH_MODE === "dev") {
    return "Dev admin";
  }

  throw new UnauthenticatedError("/api/auth/session", "no valid session cookie");
}
