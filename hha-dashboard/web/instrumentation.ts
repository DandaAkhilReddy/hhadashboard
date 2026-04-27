/**
 * Next.js instrumentation hook — runs once when the server process boots,
 * before any request is served.
 *
 * https://nextjs.org/docs/app/api-reference/file-conventions/instrumentation
 *
 * Audit ticket T4: SESSION_SECRET is required in any non-dev mode for the
 * AES-GCM cookie encryption. The existing fail-fast in
 * `lib/auth/session-crypto.ts::getSecret` only fires when an auth-related
 * route is hit. That means a misconfigured prod deploy (env var unset)
 * boots cleanly, serves dashboard pages while in dev fallback, and only
 * crashes when a user attempts MSAL sign-in.
 *
 * Better: fail at process boot. Operator sees the error in App Service
 * stdout immediately and fixes config before any user is impacted.
 */

export async function register(): Promise<void> {
  // Only run in the Node.js server runtime (not edge, not client).
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  const authMode = process.env.NEXT_PUBLIC_AUTH_MODE ?? "dev";
  const secret = process.env.SESSION_SECRET;

  if (authMode !== "dev" && !secret) {
    throw new Error(
      `Refusing to start: SESSION_SECRET env var is required when NEXT_PUBLIC_AUTH_MODE=${authMode}. Generate a 32-byte base64 key (openssl rand -base64 32) and set it as an App Service config value (or KV reference). See web/.env.example for format.`,
    );
  }

  if (secret) {
    // Validate the shape early — if it's not 32 bytes after base64
    // decode, the AES-GCM importKey call will throw later, and that
    // error is harder to diagnose.
    const cleaned = secret.replace(/-/g, "+").replace(/_/g, "/");
    const padded = cleaned + "=".repeat((4 - (cleaned.length % 4)) % 4);
    let decodedLength = 0;
    try {
      decodedLength = Buffer.from(padded, "base64").length;
    } catch {
      throw new Error(
        "SESSION_SECRET could not be base64-decoded. Generate a fresh " +
          "key with: openssl rand -base64 32",
      );
    }
    if (decodedLength !== 32) {
      throw new Error(
        `SESSION_SECRET must decode to 32 bytes (got ${decodedLength}). Generate a fresh key with: openssl rand -base64 32`,
      );
    }
  }
}
