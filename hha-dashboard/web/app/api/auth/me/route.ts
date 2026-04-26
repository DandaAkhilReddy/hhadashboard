/**
 * Current-user info for the UI.
 *
 * GET /api/auth/me
 *   Reads the hha_session cookie, decodes the JWT (without verification —
 *   display only; the backend verifies on every API call), maps the
 *   `groups` claim to role names via the same env-var convention as the
 *   API, and returns { upn, name, roles, comp_viewer }.
 *
 * Returns 401 with `{authenticated: false}` when no valid session — the
 * client falls back to a "Dev admin" placeholder in dev mode.
 *
 * HIPAA note: never log the UPN or claims body. Errors are logged with
 * just the failure category, never user-identifying content.
 */

import { SESSION_COOKIE_NAME, decryptSession, isSessionExpired } from "@/lib/auth/session-crypto";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export const runtime = "nodejs";

type MeResponse =
  | { authenticated: false; mode: "dev" | "prod" }
  | {
      authenticated: true;
      upn: string;
      name: string;
      roles: string[];
      comp_viewer: boolean;
    };

const AUTH_MODE: "dev" | "prod" =
  (process.env.NEXT_PUBLIC_AUTH_MODE ?? "dev") === "dev" ? "dev" : "prod";

function decodeClaims(jwt: string): Record<string, unknown> | null {
  const parts = jwt.split(".");
  if (parts.length !== 3) return null;
  try {
    const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = payload + "=".repeat((4 - (payload.length % 4)) % 4);
    const json = atob(padded);
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function buildGroupRoleMap(): Record<string, string> {
  // Mirrors the backend's settings.entra_group_to_role_map() but reads the
  // same env vars (with NEXT_PUBLIC_ prefix on the frontend).
  const entries: Array<[string | undefined, string]> = [
    [process.env.NEXT_PUBLIC_ENTRA_GROUP_ADMIN, "admin"],
    [process.env.NEXT_PUBLIC_ENTRA_GROUP_EXEC, "exec"],
    [process.env.NEXT_PUBLIC_ENTRA_GROUP_COMP_VIEWER, "comp_viewer"],
    [process.env.NEXT_PUBLIC_ENTRA_GROUP_OWNER_OPS, "owner_ops"],
    [process.env.NEXT_PUBLIC_ENTRA_GROUP_OWNER_FINANCE, "owner_finance"],
    [process.env.NEXT_PUBLIC_ENTRA_GROUP_OWNER_CLINICAL, "owner_clinical"],
    [process.env.NEXT_PUBLIC_ENTRA_GROUP_OWNER_HR, "owner_hr"],
  ];
  const map: Record<string, string> = {};
  for (const [gid, role] of entries) {
    if (gid) map[gid] = role;
  }
  return map;
}

function extractUpn(claims: Record<string, unknown>): string {
  for (const k of ["preferred_username", "upn", "email", "oid"]) {
    const v = claims[k];
    if (typeof v === "string" && v) return v;
  }
  return "";
}

function extractName(claims: Record<string, unknown>): string {
  const name = claims.name;
  if (typeof name === "string" && name) return name;
  return extractUpn(claims);
}

function extractRoles(claims: Record<string, unknown>): string[] {
  const groups = claims.groups;
  if (!Array.isArray(groups)) return [];
  const map = buildGroupRoleMap();
  const roles = new Set<string>();
  for (const g of groups) {
    if (typeof g === "string" && map[g]) roles.add(map[g]);
  }
  return Array.from(roles);
}

export async function GET(): Promise<NextResponse<MeResponse>> {
  const store = await cookies();
  const raw = store.get(SESSION_COOKIE_NAME)?.value;

  if (!raw) {
    return NextResponse.json<MeResponse>(
      { authenticated: false, mode: AUTH_MODE },
      { status: AUTH_MODE === "dev" ? 200 : 401 },
    );
  }

  const session = await decryptSession(raw);
  if (!session || isSessionExpired(session)) {
    return NextResponse.json<MeResponse>(
      { authenticated: false, mode: AUTH_MODE },
      { status: 401 },
    );
  }

  const claims = decodeClaims(session.access_token);
  if (!claims) {
    return NextResponse.json<MeResponse>(
      { authenticated: false, mode: AUTH_MODE },
      { status: 401 },
    );
  }

  const upn = extractUpn(claims);
  const roles = extractRoles(claims);

  return NextResponse.json<MeResponse>({
    authenticated: true,
    upn,
    name: extractName(claims),
    roles,
    comp_viewer: roles.includes("comp_viewer"),
  });
}
