"use client";

/**
 * Client-side providers: MSAL + TanStack Query.
 *
 * Mounted once at the root layout. In dev mode (or when MSAL env vars are
 * missing), MsalProvider is skipped — the dev-stub Authorization header is
 * used directly by api-client.ts. Entry forms that import `useApiBrowser`
 * will then return a "Dev admin" header function instead of an MSAL one.
 */

import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { MsalProvider } from "@azure/msal-react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ensureMsalInitialized, getMsalInstance } from "@/lib/auth/msal-config";

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30 * 1000,
        refetchOnWindowFocus: false,
        retry: 1,
      },
    },
  });
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [queryClient] = useState(makeQueryClient);
  const instance = useMemo(() => getMsalInstance(), []);
  const [initialized, setInitialized] = useState(instance === null);

  useEffect(() => {
    if (instance === null) return;
    let cancelled = false;
    ensureMsalInitialized().then(() => {
      if (!cancelled) setInitialized(true);
    });
    return () => {
      cancelled = true;
    };
  }, [instance]);

  // While MSAL is initializing, render nothing rather than letting the app
  // try to acquire tokens against an uninitialized instance.
  if (!initialized) return null;

  if (instance === null) {
    // Dev mode: skip MsalProvider entirely.
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }

  return (
    <MsalProvider instance={instance}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </MsalProvider>
  );
}
