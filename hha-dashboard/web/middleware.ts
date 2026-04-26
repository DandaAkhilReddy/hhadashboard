import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Auth gate (presence check only).
 *
 * Two independent surfaces share this middleware:
 *
 * 1. **Dashboard** (Entra-gated). In dev (NEXT_PUBLIC_AUTH_MODE=dev) we let
 *    everything through. In prod we look for the `hha_session` cookie. If
 *    absent and the path isn't an /auth/* page or /api/auth/* route, we
 *    redirect to /auth/sign-in with `?return=`.
 *
 * 2. **Census portal** (separate single-credential login). Always on,
 *    regardless of AUTH_MODE — the portal is the same in dev and prod since
 *    it's not Entra-backed. We look for the `census_session` cookie. If
 *    absent and the path isn't /census/login, redirect to /census/login.
 *
 * Token-expiry / session-invalid redirects are handled by the API itself
 * (returns 401 → server pages redirect via cookies()). This middleware
 * does only presence checks.
 */

const DASHBOARD_COOKIE = "hha_session";
const CENSUS_COOKIE = "census_session";
const AUTH_MODE = process.env.NEXT_PUBLIC_AUTH_MODE ?? "dev";

const DASHBOARD_PUBLIC_PREFIXES = ["/auth/", "/api/auth/"];

function isCensusPath(pathname: string): boolean {
  return pathname.startsWith("/census");
}

function isDashboardPublicPath(pathname: string): boolean {
  return DASHBOARD_PUBLIC_PREFIXES.some((p) => pathname.startsWith(p));
}

export function middleware(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;

  // ---- Census portal branch — independent of AUTH_MODE ----
  if (isCensusPath(pathname)) {
    if (pathname === "/census/login" || pathname === "/census") {
      return NextResponse.next();
    }
    if (request.cookies.has(CENSUS_COOKIE)) {
      return NextResponse.next();
    }
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/census/login";
    loginUrl.search = "";
    return NextResponse.redirect(loginUrl);
  }

  // ---- Dashboard branch ----
  if (AUTH_MODE === "dev") {
    return NextResponse.next();
  }

  if (isDashboardPublicPath(pathname)) {
    return NextResponse.next();
  }

  if (request.cookies.has(DASHBOARD_COOKIE)) {
    return NextResponse.next();
  }

  const signInUrl = request.nextUrl.clone();
  signInUrl.pathname = "/auth/sign-in";
  signInUrl.search = `?return=${encodeURIComponent(pathname)}`;
  return NextResponse.redirect(signInUrl);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
