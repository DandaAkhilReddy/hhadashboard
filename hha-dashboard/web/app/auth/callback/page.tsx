"use client";

/**
 * Callback page — receives the Entra redirect after sign-in.
 *
 * Flow:
 *   1. handleRedirectPromise resolves once MSAL has parsed the URL hash
 *   2. acquireTokenSilent for the API scope
 *   3. POST {access_token, expires_at} to /api/auth/session → cookie set
 *   4. router.replace(returnTo) → user lands on the page they wanted
 */

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMsal } from "@azure/msal-react";
import { apiScope, isMsalConfigured } from "@/lib/auth/msal-config";

async function postSession(accessToken: string, expiresAt: number): Promise<void> {
  const res = await fetch("/api/auth/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ access_token: accessToken, expires_at: expiresAt }),
  });
  if (!res.ok) {
    throw new Error(`session POST failed: ${res.status}`);
  }
}

export default function AuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const msal = useMsal();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isMsalConfigured()) {
      router.replace("/");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const result = await msal.instance.handleRedirectPromise();
        const account = result?.account ?? msal.instance.getAllAccounts()[0];
        if (!account) {
          throw new Error("no account after redirect");
        }
        msal.instance.setActiveAccount(account);
        const tokenResult = await msal.instance.acquireTokenSilent({
          account,
          scopes: [apiScope()],
        });
        const expSec =
          tokenResult.expiresOn instanceof Date
            ? Math.floor(tokenResult.expiresOn.getTime() / 1000)
            : Math.floor(Date.now() / 1000) + 3600;
        await postSession(tokenResult.accessToken, expSec);
        if (!cancelled) {
          const returnTo = searchParams.get("return") ?? "/";
          router.replace(returnTo);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "callback failed");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [msal.instance, router, searchParams]);

  return (
    <div className="mx-auto mt-32 max-w-md text-center text-sm">
      {error ? (
        <span className="text-red-600">Sign-in error: {error}</span>
      ) : (
        <span className="text-slate-500">Completing sign-in…</span>
      )}
    </div>
  );
}
