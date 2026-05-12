# ADR-002: Role-Based Access Control Model

- **Status:** Accepted
- **Date:** 2026-04-26
- **Deciders:** Akhil Reddy (technical lead); CEO + CFO co-sponsors
- **Supersedes:** None

## Context

The dashboard has three distinct populations of users, and they need three different authorization profiles:

1. **Exec leadership** (CEO, CFO, COO, CMO) — read every board, no entry forms, no admin. CEO and CFO additionally see comp detail (Doctor Scorecards) and below-FMV breakdowns.
2. **Department owners** (Crystal/Sandy/Maribel/Aneja/Reddy/Andrea) — read all boards, write entry forms scoped to their domain (ops/finance/clinical/HR), no admin.
3. **Census operator** (whoever is at the desk that day) — types daily census numbers for 11 sites, sees nothing else. **Different threat model entirely** — a single shared credential rotated by ops, treated as a "kiosk," no PII access.

A sloppier system would put all three in one Entra group hierarchy. We don't, for two reasons:

- **The census operator is a kiosk role**, not a "user." Whoever sits at the desk types numbers; the surface they see is intentionally minimal. Entra is overkill (and the user often won't have an Entra account at all — could be a clinical scribe, intern, or temp).
- **`comp_viewer` is orthogonal to seniority**, not a level above `exec`. Some execs need it, some don't. Group-membership encodes it as an additive flag, not a stacked role.

This ADR documents the model, locks the names, and explains why each piece can't be simplified.

## Decision

### Part 1 — Two auth surfaces

| Surface | Path | Auth | Cookie | Used by |
|---|---|---|---|---|
| **Dashboard** | `/`, `/operations`, `/finance`, `/clinical`, `/people`, `/scorecards`, `/daily-census`, … | Entra ID via MSAL (browser) → encrypted httpOnly session cookie → forwarded as `Authorization: Bearer` from server components | `hha_session` | Execs + department owners |
| **Census portal** | `/census/login`, `/census/entry` | Single shared email + password (argon2id) → opaque session token → httpOnly cookie. **Single-session lock**: each login overwrites the active token, so the second tab boots the first. | `census_session` | Daily census operator |

The two cookies have different names so there is no scenario in which authority on one surface implicitly grants authority on the other. Middleware (`web/middleware.ts`) gates each path prefix on the corresponding cookie alone.

### Part 2 — Roles + Entra groups

Seven Entra security groups in the HHA tenant. Each group's `objectId` is read by `api/app/settings.py` from environment, and `services/entra_jwt.py` maps `groups` claim → role set.

| Role | Group name | Members | Grants |
|---|---|---|---|
| `admin` | `HHA-Dashboard-Admin` | Akhil + 1 backup | Full read/write across every board, entry form, and admin page. **Acts as the operator of last resort.** |
| `exec` | `HHA-Dashboard-Exec` | CEO, CFO, COO, CMO | Read every dashboard. No entry forms. No admin. |
| `comp_viewer` | `HHA-Dashboard-CompViewer` | CEO, CFO | **Additive flag.** Unlocks Doctor Scorecards comp detail + below-FMV breakdowns. CMO and COO are deliberately excluded. |
| `owner_ops` | `HHA-Dashboard-Owner-Ops` | Crystal | Read all boards + write `/daily-census` |
| `owner_finance` | `HHA-Dashboard-Owner-Finance` | Sandy, Maribel | Read all boards + write `/monthly-finance` |
| `owner_clinical` | `HHA-Dashboard-Owner-Clinical` | Dr. Aneja, Dr. Reddy | Read all boards + write `/weekly-clinical` |
| `owner_hr` | `HHA-Dashboard-Owner-HR` | Andrea | Read all boards + write `/weekly-hr` |

A user can belong to multiple groups. Roles are the union of the matched groups. `admin` is a superset; assigning admin to anyone besides Akhil + 1 emergency backup is policy-blocked.

### Part 3 — Enforcement points

There are **three** enforcement layers. All three must agree before a request succeeds.

1. **Next.js middleware** (`web/middleware.ts`) — presence check on the cookie. No decryption. Wrong cookie → redirect to sign-in. Cheapest gate, runs on every request.

2. **FastAPI dependency** (`api/app/deps.py::get_current_user` + `require_role`) — verifies the Entra JWT, extracts the groups claim, maps to roles, fails 401/403 if the role set doesn't include any of the required ones. Per-route.

3. **Postgres** (no DB-level RBAC today; reserved for future) — currently the API holds the database password and runs every query as the same DB role. We've left the schema separation in place (`masters` / `entries` / `facts` / `audit` / `alerts` / `auth`) so a future ADR can layer Postgres `GRANT USAGE ON SCHEMA` per-role if compliance demands it.

### Part 4 — `comp_viewer` is additive, not a level

This is the part most likely to be misunderstood and "simplified" later. **Don't.**

- Without `comp_viewer`, an exec sees Doctor Scorecards but with comp columns redacted ("Salary: ●●●", "FMV delta: ●●●").
- With `comp_viewer`, the same exec sees actual dollar values, below-FMV reasons, RVU rates.
- Implementation: `CurrentUser.comp_viewer: bool` is a separate field from `roles: set[str]`. Routes that expose comp call `Depends(require_comp_viewer)` after `Depends(get_current_user)`.

**Why additive, not stacked:**

- `exec` is about which dashboards you can see. `comp_viewer` is about which **columns** you can see within those dashboards.
- A future "exec without comp" group (e.g., a head of clinical operations who doesn't need salary detail) is one Entra membership change away.
- A stacked role would force every "show comp" check to enumerate the right roles and miss new ones.

### Part 5 — Census portal is NOT in the role hierarchy

The census portal user has no role in the dashboard sense. The portal:
- Has its own credential table (`auth.census_credentials`, single-row enforced by `CHECK (id=1)`).
- Has its own router (`api/app/routers/census_portal.py`) with no `Depends(require_role)` calls.
- Audit log records mutations as `entered_by_upn = 'census-portal@hhamedicine.com'` and `source = 'manual_portal'` — distinguishable from in-dashboard owner-form entries.

The threat model: a misuse of the dashboard UPN gives someone access to **every board**. A misuse of the portal credential gives someone access to **typing numbers, nothing else.** Different blast radius justifies different identity.

## Consequences

- **Adding a new role** = new Entra group + new entry in `entra_group_to_role_map()` + new `require_role(...)` decorator on routes + ADR addendum.
- **Removing a user** = remove from Entra group. JWTs cached for ≤1h; revocation takes effect on next token refresh. For immediate revocation, also restart the App Service (forces re-fetch of JWKS).
- **Promoting a user to comp_viewer** = add to `HHA-Dashboard-CompViewer` group. Effective on next sign-in.
- **Rotating the census portal credential** = `bash infra/census_seed.sh --email <email> --rotate-random` and hand the new password to ops.
- **Auditing who has what access** = check Entra group memberships, not the codebase. The codebase reflects the contract; the directory is the source of truth.
- **Compliance evidence** = (a) this ADR, (b) Entra group membership snapshot, (c) audit_log queries showing `changed_by_upn` for any sensitive table mutation.

## Out of scope (for now)

- **Per-site authorization** — every owner sees every site. If HHA later wants regional managers (e.g., one ops owner per state), that's `site_id` in the user profile + a `WHERE site_id IN (...)` filter on every read. ~1 day of work but a schema change. Defer until requested.
- **Database-level RBAC** — schema separation is in place but no `GRANT USAGE` is exercised. Lay this in if a HIPAA auditor asks.
- **MFA enforcement** — relies on Entra's Conditional Access policies set at the tenant level. Not encoded in this codebase.
- **B2B guest users** — not supported. Single tenant.
- **Group-claim overage** (when a user belongs to >150 groups, Entra returns `_claim_names` indirection instead of `groups`). Not handled today; HHA's tenant has 7 dashboard groups, so this won't bite at our scale. Document and revisit if the tenant grows past ~100 groups.

## Verification

- `tests/test_entra_jwt.py` — group claim → role mapping unit tests.
- `tests/test_deps_auth_fallthrough.py` — Path 3 dev fallthrough only fires when both `ENV=dev` and Entra unconfigured; non-dev environments 401 without a token regardless.
- `tests/test_census_portal.py` — separate auth surface; single-session lock; lockout after 10 failed attempts.
- `tests/test_scorecards_router.py` — `comp_viewer` gate redacts comp columns when missing.
- Manual: sign in as a non-comp-viewer exec → Doctor Scorecards loads, comp cells show "—".

## References

- [api/app/services/entra_jwt.py](../../../api/app/services/entra_jwt.py)
- [api/app/deps.py](../../../api/app/deps.py)
- [api/app/routers/census_portal.py](../../../api/app/routers/census_portal.py)
- [docs/ENTRA_SETUP.md](../../03-engineering/ENTRA_SETUP.md) — one-time tenant-admin steps to provision the groups
