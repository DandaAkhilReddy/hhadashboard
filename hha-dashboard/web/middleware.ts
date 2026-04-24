import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Middleware stub.
 *
 * Session 1: no-op — every request passes through.
 * Session 2: real MSAL session check + Entra group → role mapping → route guards
 * per the RBAC table in CLAUDE.md.
 */
export function middleware(_request: NextRequest) {
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
