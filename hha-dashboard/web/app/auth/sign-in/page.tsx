"use client";

/**
 * Sign-in page.
 *
 * Auto-fires loginRedirect on mount when MSAL is configured. In dev mode
 * (no MSAL), redirects straight to / since the dev-stub flow doesn't need
 * a sign-in step.
 */

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMsal } from "@azure/msal-react";
import { isMsalConfigured, loginScopes } from "@/lib/auth/msal-config";

export default function SignInPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const msalConfigured = isMsalConfigured();
  // useMsal is safe to call when MsalProvider is absent — returns a stub
  // that we won't touch unless msalConfigured is true.
  const msal = useMsal();
  const [error, setError] = useState<string | null>(null);
  const returnTo = searchParams.get("return") ?? "/";

  useEffect(() => {
    if (!msalConfigured) {
      router.replace(returnTo);
      return;
    }
    if (msal.accounts.length > 0) {
      router.replace(returnTo);
      return;
    }
    if (msal.inProgress !== "none") return;

    msal.instance
      .loginRedirect({
        scopes: [...loginScopes],
        redirectStartPage: returnTo,
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "sign-in failed");
      });
  }, [msalConfigured, msal.accounts, msal.inProgress, msal.instance, returnTo, router]);

  return (
    <div className="mx-auto mt-32 max-w-md text-center">
      <div className="text-sm text-slate-500">
        {error ? (
          <span className="text-red-600">Sign-in error: {error}</span>
        ) : msalConfigured ? (
          "Redirecting to Microsoft sign-in…"
        ) : (
          "Dev mode — no sign-in required."
        )}
      </div>
    </div>
  );
}
