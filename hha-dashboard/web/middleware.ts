import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Auth gate (presence check only).
 *
 * Runs on every request. In dev mode (NEXT_PUBLIC_AUTH_MODE=dev) we let
 * everything through — local dev doesn't need a sign-in. In prod, we look
 * for the hha_session cookie. If absent and the path isn't an /auth/* page
 * or the /api/auth/* route handlers, redirect to /auth/sign-in with the
 * original path captured in `?return=`.
 *
 * We deliberately don't decrypt the cookie here — that adds a Web Crypto
 * call to every request. Token-expiry redirects are handled later, when
 * the server-component fetcher tries to use the stale token and the
 * fetchOrSignIn helper bounces to /auth/sign-in.
 */

const SESSION_COOKIE = "hha_session";
const AUTH_MODE = process.env.NEXT_PUBLIC_AUTH_MODE ?? "dev";

const PUBLIC_PREFIXES = ["/auth/", "/api/auth/"];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PREFIXES.some((p) => pathname.startsWith(p));
}

export function middleware(request: NextRequest): NextResponse {
  if (AUTH_MODE === "dev") {
    return NextResponse.next();
  }

  const { pathname } = request.nextUrl;
  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  const hasCookie = request.cookies.has(SESSION_COOKIE);
  if (hasCookie) {
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
