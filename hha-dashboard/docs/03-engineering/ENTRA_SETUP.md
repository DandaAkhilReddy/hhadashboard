# Entra ID setup — production auth wiring

The dashboard's API verifies access tokens issued by Microsoft Entra ID
(formerly Azure AD). The verification code path is in
[`api/app/services/entra_jwt.py`](../../api/app/services/entra_jwt.py); it is
exercised by [`api/tests/test_entra_jwt.py`](../../api/tests/test_entra_jwt.py)
with synthetic RSA keys.

This document is the **Azure-side checklist** to make real auth work end-to-end.
Until both apps below are registered and the env vars in step 3 are set, the
API falls back to the dev stub (`Authorization: Dev <role>`).

## 1 · Register two Entra apps

Both registrations live in HHA's Entra tenant. Reddy or any tenant admin can
create them. Naming convention: `hha-dashboard-{api|web}-{env}`.

### a. API app (the one this codebase verifies tokens for)

- **Name**: `hha-dashboard-api-prod` (and `-dev` for the dev tenant)
- **Supported account types**: Single tenant (HHA only)
- **Redirect URIs**: none — the API does not initiate sign-in
- **Expose an API**:
  - Application ID URI: `api://<api-client-id>`
  - Add scope `access_as_user` (admin + user consent, "Sign in and read user profile")
- **App roles** (optional, can use groups instead): leave empty for now — we
  use group-claim mapping
- **Token configuration → Add groups claim**:
  - Group types: **Security groups**
  - Customize token properties: emit `Group ID` (not `sAMAccountName`) for both
    Access tokens and ID tokens
- Capture the **Application (client) ID** → this is `AZURE_API_CLIENT_ID`

### b. Web app (the SPA that signs users in)

- **Name**: `hha-dashboard-web-prod`
- **Supported account types**: Single tenant
- **Redirect URIs (SPA)**:
  - `https://app-hha-web-prod.azurewebsites.net/auth/callback`
  - `http://localhost:3000/auth/callback` (for dev)
- **API permissions**:
  - Add a permission → `hha-dashboard-api-prod` → `access_as_user` → grant admin consent
- Capture the **Application (client) ID** → frontend MSAL config

## 2 · Create role groups

Create one Entra security group per role. Group object IDs go into the API's
config so the JWT verifier maps `groups` claim → role name.

| Group name | Role | Setting field |
|---|---|---|
| `HHA-Dashboard-Admin` | `admin` | `ENTRA_GROUP_ADMIN` |
| `HHA-Dashboard-Exec` | `exec` | `ENTRA_GROUP_EXEC` |
| `HHA-Dashboard-CompViewer` | `comp_viewer` | `ENTRA_GROUP_COMP_VIEWER` |
| `HHA-Dashboard-Owner-Ops` | `owner_ops` | `ENTRA_GROUP_OWNER_OPS` |
| `HHA-Dashboard-Owner-Finance` | `owner_finance` | `ENTRA_GROUP_OWNER_FINANCE` |
| `HHA-Dashboard-Owner-Clinical` | `owner_clinical` | `ENTRA_GROUP_OWNER_CLINICAL` |
| `HHA-Dashboard-Owner-HR` | `owner_hr` | `ENTRA_GROUP_OWNER_HR` |

For each group, copy the **Object ID** (the GUID, not the name) — that's what
Entra puts in the `groups` claim and what we configure on the API side.

A user can belong to multiple groups. `comp_viewer` is **additive** — a CFO
typically gets both `Exec` and `CompViewer`, which gives them all dashboards
plus comp-sensitive endpoints (Doctor Scorecards comp detail, below-FMV
reasons).

## 3 · Configure the API

Set these in the API's environment (Key Vault → App Service config in prod,
`.env` in dev):

```bash
# Tenant + audience
AZURE_TENANT_ID=<your-tenant-uuid>
AZURE_API_CLIENT_ID=<api-app-client-id-from-1a>

# Group → role map (paste the Object IDs from step 2)
ENTRA_GROUP_ADMIN=<guid>
ENTRA_GROUP_EXEC=<guid>
ENTRA_GROUP_COMP_VIEWER=<guid>
ENTRA_GROUP_OWNER_OPS=<guid>
ENTRA_GROUP_OWNER_FINANCE=<guid>
ENTRA_GROUP_OWNER_CLINICAL=<guid>
ENTRA_GROUP_OWNER_HR=<guid>
```

When `AZURE_TENANT_ID` AND `AZURE_API_CLIENT_ID` are both set, the API
**prefers** real JWT verification on any `Authorization: Bearer <jwt>` header.
The dev stub still works for unauthenticated dev flows where it would
otherwise be 401.

## 4 · Test it

### From the API side (curl + a token)

1. Sign in via the SPA, grab the `Authorization: Bearer ...` header from a
   network request in DevTools.
2. Replay it against the API:
   ```bash
   curl -H "Authorization: Bearer <jwt>" https://app-hha-api-prod.azurewebsites.net/api/v1/operations/sites-today
   ```
3. If the token is valid, the response is 200. If anything's wrong (expired,
   wrong audience, missing kid, signature bad) the API returns 401 with a
   specific reason in the body — surface in App Insights for ops.

### What to watch in App Insights

- `entra.jwks.refreshed` — fires on cold start and every 24h. Frequent
  refreshes suggest a kid rotation or a config drift.
- `Token expired` 401s — normal at session boundaries.
- `Invalid token claims` 401s with `aud` or `iss` mismatch — config error
  (wrong client_id or tenant_id), audit immediately.
- `No matching signing key for token` after a force-refresh — Entra rotated
  keys faster than 24h cache TTL; not concerning if rare, dig in if frequent.

## 5 · Frontend wiring (MSAL.js) — done in Session 6

The SPA was wired in `feat/session-6-msal`. Architecture:

- `@azure/msal-browser` + `@azure/msal-react` (browser-only)
- Server components (dashboards) fetch via a Node-only api-client that reads
  an encrypted httpOnly `hha_session` cookie and forwards the token as
  `Authorization: Bearer <jwt>`
- Client components (entry forms) use a `useApiBrowser()` hook that calls
  MSAL's `acquireTokenSilent` directly — they never touch the cookie
- Sign-in (`/auth/sign-in`) → MSAL redirect → callback (`/auth/callback`)
  acquires the API token and POSTs to `/api/auth/session` to set the
  cookie → user lands on the page they wanted
- Middleware in `web/middleware.ts` redirects unauthenticated requests to
  `/auth/sign-in` outside dev mode. Doesn't decrypt — presence-only check
- Sign-out (`/auth/sign-out`) clears the cookie AND calls
  MSAL's `logoutRedirect` (both required, otherwise half-signed-out)

### Switching from dev mode to real auth

The dev fallback is gated on `NEXT_PUBLIC_AUTH_MODE`. To go live:

1. Complete steps 1–3 above (Entra app registrations, security groups,
   API env vars).
2. Set frontend env vars in `web/.env.local` or hosting config:

   ```bash
   NEXT_PUBLIC_AUTH_MODE=prod
   NEXT_PUBLIC_AZURE_TENANT_ID=<tenant-uuid>
   NEXT_PUBLIC_AZURE_WEB_CLIENT_ID=<from-1b>
   NEXT_PUBLIC_AZURE_API_CLIENT_ID=<from-1a>
   NEXT_PUBLIC_ENTRA_GROUP_ADMIN=<guid>
   # … one for each role group …
   SESSION_SECRET=<openssl rand -base64 32>
   ```

3. Restart the Next dev server. Hitting `/` redirects to `/auth/sign-in`,
   which MSAL handles via redirect to login.microsoftonline.com.

In dev (`NEXT_PUBLIC_AUTH_MODE=dev`), MSAL is bypassed entirely — the
api-client sends `Authorization: Dev admin` and the dashboard works
without any Azure setup.

### What's still deferred

- Silent background token refresh (1h tokens; user re-logs in for now)
- Conditional Access step-up flows
- Role-based tab filtering in TopNav (backend already enforces; UI shows
  static badges)
- Playwright E2E for the sign-in flow (needs a real Azure tenant)

## 6 · Edge cases / gotchas

- **Group claim overflow**: Entra omits the `groups` claim and sends a
  `_claim_names` indirection if a user is in >150 groups. We don't handle
  the indirection yet — keep HHA Dashboard groups under 150 (we have 7).
- **Service principals**: the cron jobs (e.g. ventra_ingest) don't go
  through Entra — they're authenticated by managed identity at the Azure
  level and bypass JWT verification entirely. Audit attribution still works
  via the contextvar set at job startup.
- **Token revocation**: Entra access tokens are valid until expiry (~1h);
  we don't check a revocation list. If a user is removed from a group,
  effects propagate after their next token refresh.
