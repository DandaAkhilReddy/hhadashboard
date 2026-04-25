/**
 * MSAL configuration for the SPA.
 *
 * Reads NEXT_PUBLIC_* env vars (must be inlined at build time). When
 * AUTH_MODE=dev or any required var is missing, returns null — the
 * AuthProvider then skips MsalProvider and the dev-stub takes over.
 */

import { type Configuration, PublicClientApplication } from "@azure/msal-browser";

export const AUTH_MODE = process.env.NEXT_PUBLIC_AUTH_MODE ?? "dev";

const TENANT_ID = process.env.NEXT_PUBLIC_AZURE_TENANT_ID ?? "";
const WEB_CLIENT_ID = process.env.NEXT_PUBLIC_AZURE_WEB_CLIENT_ID ?? "";
const API_CLIENT_ID = process.env.NEXT_PUBLIC_AZURE_API_CLIENT_ID ?? "";

export const apiScope = (): string =>
  API_CLIENT_ID ? `api://${API_CLIENT_ID}/access_as_user` : "";

export const loginScopes = ["openid", "profile", "email"] as const;

export function isMsalConfigured(): boolean {
  return Boolean(TENANT_ID && WEB_CLIENT_ID && API_CLIENT_ID);
}

let _instance: PublicClientApplication | null = null;
let _initPromise: Promise<void> | null = null;

function buildConfig(): Configuration {
  const redirectUri =
    typeof window !== "undefined" ? `${window.location.origin}/auth/callback` : "/auth/callback";

  return {
    auth: {
      clientId: WEB_CLIENT_ID,
      authority: `https://login.microsoftonline.com/${TENANT_ID}`,
      redirectUri,
      postLogoutRedirectUri: "/",
    },
    cache: {
      cacheLocation: "sessionStorage",
    },
  };
}

/**
 * Returns the singleton MSAL instance, or null when auth is not configured.
 * Caller is responsible for awaiting `ensureMsalInitialized()` before any
 * `acquireToken*` call (msal-browser v4+ requires explicit init).
 */
export function getMsalInstance(): PublicClientApplication | null {
  if (!isMsalConfigured()) return null;
  if (!_instance) {
    _instance = new PublicClientApplication(buildConfig());
  }
  return _instance;
}

export async function ensureMsalInitialized(): Promise<void> {
  const instance = getMsalInstance();
  if (!instance) return;
  if (!_initPromise) {
    _initPromise = instance.initialize();
  }
  await _initPromise;
}
