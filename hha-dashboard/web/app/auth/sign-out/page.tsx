"use client";

/**
 * Sign-out page.
 *
 * Both sides matter — clear the cookie AND tell MSAL to forget the
 * account, otherwise the next sign-in flow silently re-uses the cached
 * account and we end up back-to-back signed in.
 */

import { isMsalConfigured } from "@/lib/auth/msal-config";
import { useMsal } from "@azure/msal-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

async function clearSession(): Promise<void> {
  await fetch("/api/auth/session", { method: "DELETE" });
}

export default function SignOutPage() {
  const router = useRouter();
  const msal = useMsal();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await clearSession();
      if (cancelled) return;
      if (isMsalConfigured()) {
        // logoutRedirect navigates away — no need for router.replace.
        await msal.instance.logoutRedirect({
          postLogoutRedirectUri: "/",
        });
      } else {
        router.replace("/");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [msal.instance, router]);

  return (
    <div className="mx-auto mt-32 max-w-md text-center text-sm text-slate-500">
      Signing you out…
    </div>
  );
}
