"use client";

/**
 * Current-user hook for client components.
 *
 * Fetches /api/auth/me via TanStack Query. In dev mode the route returns
 * { authenticated: false, mode: "dev" } and the UI renders a placeholder.
 */

import { useQuery } from "@tanstack/react-query";

export type UnauthenticatedUser = { authenticated: false; mode: "dev" | "prod" };
export type AuthenticatedUser = {
  authenticated: true;
  upn: string;
  name: string;
  roles: string[];
  comp_viewer: boolean;
};
export type CurrentUser = UnauthenticatedUser | AuthenticatedUser;

async function fetchMe(): Promise<CurrentUser> {
  const res = await fetch("/api/auth/me", { cache: "no-store" });
  // Treat 401 as a clean "not signed in" signal; throw on other errors so
  // they surface in DevTools and don't silently mask a misconfigured route.
  if (res.status === 401) {
    return (await res.json()) as UnauthenticatedUser;
  }
  if (!res.ok) {
    throw new Error(`/api/auth/me → ${res.status}`);
  }
  return (await res.json()) as CurrentUser;
}

export function useUser(): {
  user: CurrentUser | undefined;
  isLoading: boolean;
} {
  const { data, isLoading } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: fetchMe,
    staleTime: 60 * 1000,
  });
  return { user: data, isLoading };
}
