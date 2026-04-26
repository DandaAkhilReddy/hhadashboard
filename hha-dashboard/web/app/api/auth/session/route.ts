/**
 * Session cookie route.
 *
 * POST /api/auth/session
 *   Body: { access_token: string, expires_at: number }
 *   Sets the encrypted hha_session cookie. Same-origin only — Origin header
 *   must match the request URL's origin (defense-in-depth; SameSite=Lax
 *   already gates cross-site).
 *
 * DELETE /api/auth/session
 *   Clears the cookie. Used on sign-out.
 *
 * No JWT verification here — the backend verifies on every request. This
 * endpoint just stores what the browser-side MSAL flow handed us.
 */

import { NextResponse } from "next/server";
import {
  encryptSession,
  isSessionExpired,
  SESSION_COOKIE_NAME,
  type Session,
} from "@/lib/auth/session-crypto";

export const runtime = "nodejs";

function isSameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return false;
  try {
    return new URL(origin).origin === new URL(request.url).origin;
  } catch {
    return false;
  }
}

function isSession(value: unknown): value is Session {
  return (
    typeof value === "object" &&
    value !== null &&
    "access_token" in value &&
    "expires_at" in value &&
    typeof (value as Session).access_token === "string" &&
    typeof (value as Session).expires_at === "number"
  );
}

export async function POST(request: Request): Promise<NextResponse> {
  if (!isSameOrigin(request)) {
    return NextResponse.json({ error: "cross-origin not allowed" }, { status: 403 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  if (!isSession(body)) {
    return NextResponse.json(
      { error: "expected { access_token: string, expires_at: number }" },
      { status: 400 },
    );
  }

  if (isSessionExpired(body)) {
    return NextResponse.json({ error: "expires_at is in the past" }, { status: 400 });
  }

  const blob = await encryptSession(body);
  const maxAgeSec = Math.max(0, body.expires_at - Math.floor(Date.now() / 1000));

  const res = NextResponse.json({ ok: true });
  res.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: blob,
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: maxAgeSec,
  });
  return res;
}

export async function DELETE(request: Request): Promise<NextResponse> {
  if (!isSameOrigin(request)) {
    return NextResponse.json({ error: "cross-origin not allowed" }, { status: 403 });
  }
  const res = NextResponse.json({ ok: true });
  res.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: "",
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  return res;
}
