# API endpoint catalog

> **For engineers.** Every FastAPI route, grouped by domain. Auth required, request shape, response shape. Auto-generatable from `/openapi.json` long-term; hand-curated for now. Cross-reference to source files.
>
> Last updated 2026-05-11. Source of truth: `/openapi.json` on the running API.

## Conventions

- **Auth:** every endpoint requires a valid Entra token unless explicitly marked `(public)` or `(portal_kiosk)`.
- **Role gating:** uses `Depends(require_role([...]))` from `app/auth/rbac.py`.
- **Response codes:** standard FastAPI — 200 OK on success, 401 unauthenticated, 403 forbidden, 404 not found, 422 validation error, 500 server error.
- **Pagination:** cursor-based for list endpoints; `limit` defaults to 50, max 200.
- **Audit:** every mutating endpoint sets `audit.upn` GUC before the transaction so the audit trigger captures who.

## Base URLs

| Environment | API base |
|---|---|
| Production | `https://app-hha-api-prod.azurewebsites.net` |
| Local dev | `http://localhost:8000` |

OpenAPI spec: `<base>/openapi.json`. Swagger UI: `<base>/docs`. ReDoc: `<base>/redoc`.

---

## System endpoints

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/health` | Liveness check — is the process alive | (public) |
| GET | `/ready` | Readiness check — can it serve traffic (DB connectivity, schema present, audit triggers present, sites seeded) | (public) |
| GET | `/version` | Returns deploy SHA + build timestamp | (public) |

### `GET /health`

```json
200 OK
{"status": "ok"}
```

### `GET /ready`

```json
200 OK
{
  "status": "ready",
  "checks": {
    "db": "ok",
    "schema": "ok",
    "audit_trigger": "ok",
    "sites": "ok"
  }
}
```

Returns 503 if any sub-check fails.

---

## Auth endpoints

Source: `api/app/routers/auth.py`

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/api/v1/auth/callback` | OAuth callback from Entra (called by web after sign-in) | (public) |
| POST | `/api/v1/auth/logout` | Invalidate session token | required |
| GET | `/api/v1/auth/me` | Current user info (upn, groups, role) | required |

### `GET /api/v1/auth/me`

```json
200 OK
{
  "upn": "areddy@hhamedicine.com",
  "display_name": "Akhil Reddy",
  "roles": ["admin", "exec"],
  "comp_viewer": true,
  "session_expires_at": "2026-05-11T22:14:00Z"
}
```

---

## Census portal endpoints

Source: `api/app/routers/census_portal.py`. See [PHASE_1_CENSUS_PORTAL.md](../05-product/PHASE_1_CENSUS_PORTAL.md).

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/api/v1/census-portal/login` | Authenticate kiosk credential | (public) |
| GET | `/api/v1/census-portal/sites` | List FL+TX sites for the dropdown | (portal_kiosk) |
| POST | `/api/v1/census-portal/entry` | Submit daily census count | (portal_kiosk) |
| GET | `/api/v1/census-portal/today` | Read today's census for confirmation | (portal_kiosk) |

### `POST /api/v1/census-portal/login`

```json
Request:
{
  "email": "portal@hhamedicine.com",
  "password": "..."
}

Response 200:
{
  "session_token": "...",
  "expires_at": "2026-05-11T14:00:00Z"
}

Response 401: invalid credentials
Response 429: rate-limited (5 attempts/min/IP)
```

### `POST /api/v1/census-portal/entry`

```json
Request (with session_token cookie):
{
  "site_id": 3,
  "entry_date": "2026-05-11",
  "census_count": 18,
  "notes": null
}

Response 201:
{
  "id": 1234,
  "site_id": 3,
  "entry_date": "2026-05-11",
  "census_count": 18,
  "source": "portal",
  "created_at": "2026-05-11T13:22:01Z"
}
```

UPSERT semantics: re-submitting for the same `(site_id, entry_date)` updates the existing row and records the change in audit log.

---

## Operations endpoints

Source: `api/app/routers/operations.py`. Drives the Operations board.

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/api/v1/operations/summary` | Top-of-board summary (today's census per site + state totals) | `exec` or `owner_ops` |
| GET | `/api/v1/operations/sites/{site_id}/census` | Per-site census trend (last 90d) | `exec` or `owner_ops` |
| GET | `/api/v1/operations/variance` | Sites with variance > 20% vs 3-mo avg | `exec` or `owner_ops` |
| POST | `/api/v1/operations/entry/manual` | Admin manual census entry (overrides portal) | `admin` |

### `GET /api/v1/operations/summary`

```json
200 OK
{
  "as_of": "2026-05-11T14:00:00Z",
  "totals": {
    "fl_total": 142,
    "tx_total": 28,
    "overall": 170
  },
  "sites": [
    {
      "site_id": 3,
      "site_code": "WESTSIDE",
      "state": "FL",
      "today_census": 18,
      "three_mo_avg": 16.4,
      "mtd_avg": 17.1,
      "variance_pct": 9.8,
      "md_status": "covered"
    },
    ...
  ]
}
```

---

## Finance endpoints

Source: `api/app/routers/finance.py`. Drives the Finance board.

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/api/v1/finance/collections/daily` | Daily collections by state | `exec` or `owner_finance` |
| GET | `/api/v1/finance/ar/aging` | AR aging buckets by state | `exec` or `owner_finance` |
| GET | `/api/v1/finance/days-in-ar` | Days in AR (rolling 90d) | `exec` or `owner_finance` |
| GET | `/api/v1/finance/net-collection-rate` | Net collection rate trend | `exec` or `owner_finance` |
| POST | `/api/v1/finance/entry/monthly` | Manual monthly entry (TX only) | `owner_finance` |

### `GET /api/v1/finance/collections/daily`

Query params: `start_date`, `end_date`, `state` (FL|TX|ALL).

```json
200 OK
{
  "rows": [
    {
      "date": "2026-05-11",
      "state": "FL",
      "payer_class": "commercial",
      "site_id": 3,
      "gross_charges": 12500.00,
      "payments_received": 8200.50,
      "net_revenue": 7800.00,
      "source_system": "VENTRA_FL_ATHENA"
    },
    ...
  ],
  "totals_by_state": {
    "FL": {"gross": 145000.00, "payments": 92000.00},
    "TX": {"gross": 35000.00, "payments": 22000.00}
  }
}
```

---

## Clinical endpoints

Source: `api/app/routers/clinical.py`. Drives the Clinical Quality board.

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/api/v1/clinical/hp-compliance` | H&P within 24h percentage | `exec` or `owner_clinical` |
| GET | `/api/v1/clinical/dc-compliance` | DC within 48h percentage | `exec` or `owner_clinical` |
| GET | `/api/v1/clinical/los` | Avg LOS by state, plus Woodmont watch | `exec` or `owner_clinical` |
| GET | `/api/v1/clinical/credentials/expiring` | Credentials expiring within 30/60/90d | `exec` or `owner_clinical` |
| POST | `/api/v1/clinical/entry/monthly` | Manual monthly clinical entry | `owner_clinical` |

---

## People endpoints

Source: `api/app/routers/people.py`. Drives the People & Pipeline board.

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/api/v1/people/headcount` | W-2 vs 1099 count, overall + per site | `exec` or `owner_hr` |
| GET | `/api/v1/people/open-positions` | Open positions, overall + per site | `exec` or `owner_hr` |
| GET | `/api/v1/people/turnover` | 90-day rolling turnover | `exec` or `owner_hr` |
| GET | `/api/v1/people/fill-rate` | Coverage fill rate | `exec` or `owner_hr` |
| POST | `/api/v1/people/positions` | Add a new open position | `owner_hr` |
| PATCH | `/api/v1/people/positions/{id}` | Update open position status | `owner_hr` |

---

## Doctor Scorecards endpoints

Source: `api/app/routers/scorecards.py`. **Exec-only.**

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/api/v1/scorecards/list` | All physicians with their scorecard tiles | `exec` (NOT `comp_viewer`) |
| GET | `/api/v1/scorecards/physician/{npi}` | Individual scorecard detail | `exec` |
| GET | `/api/v1/scorecards/rank` | Composite overall rank | `exec` |

**Sensitivity:** Per [adr/002-rbac-model.md](../02-architecture/adr/002-rbac-model.md), doctors **never** see their own rank or peers'. The endpoint requires `exec` group membership — not `comp_viewer`, not `admin`.

---

## Admin endpoints

Source: `api/app/routers/admin.py`. **Admin role only.**

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/api/v1/admin/sites` | List all sites (incl inactive) | `admin` |
| POST | `/api/v1/admin/sites` | Create new site | `admin` |
| PATCH | `/api/v1/admin/sites/{id}` | Update site | `admin` |
| GET | `/api/v1/admin/physicians` | List all physicians | `admin` |
| POST | `/api/v1/admin/physicians` | Create new physician | `admin` |
| GET | `/api/v1/admin/comp-agreements` | List comp agreements | `admin` AND `comp_viewer` |
| POST | `/api/v1/admin/comp-agreements` | Create comp agreement | `admin` AND `comp_viewer` |
| GET | `/api/v1/admin/alert-subscriptions` | Manage alert routing | `admin` |
| POST | `/api/v1/admin/alert-subscriptions` | Create/update alert sub | `admin` |
| GET | `/api/v1/admin/audit-log` | View audit log (filtered + paginated) | `admin` |

---

## Webhook endpoints (Phase 2)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/api/v1/webhooks/ventra-ingest-complete` | Container Apps Job calls this when ingest done | Managed Identity bearer token |
| POST | `/api/v1/webhooks/alert-deliver-ack` | ACS Email delivery acknowledgement | shared secret |

---

## Error response shape

Every error from a 4xx or 5xx endpoint follows this shape (per the global error rules in CLAUDE.md):

```json
{
  "error": {
    "code": "SNAKE_CASE_ERROR_CODE",
    "message": "Human-readable description, safe to show users",
    "correlation_id": "uuid"
  }
}
```

Examples:

- 401: `{"code": "UNAUTHENTICATED", "message": "Sign in to continue"}`
- 403: `{"code": "FORBIDDEN", "message": "This action requires exec role"}`
- 404: `{"code": "NOT_FOUND", "message": "Site 999 not found"}`
- 422: `{"code": "VALIDATION_ERROR", "message": "census_count must be ≥ 0"}`
- 409: `{"code": "CONFLICT", "message": "Census already entered for this site/date"}`

Internal server errors (500) never leak stack traces; they log the trace internally and return a sanitized `correlation_id` the user can quote to support.

## Rate limits

| Endpoint | Limit |
|---|---|
| `POST /api/v1/census-portal/login` | 5 per minute per IP |
| `POST /api/v1/auth/callback` | 10 per minute per IP |
| Other authenticated endpoints | 200 per minute per user |
| Webhook endpoints | 1000 per minute per source IP |

Exceeding returns 429 with `Retry-After` header.

## How to regenerate this catalog from OpenAPI

Long-term, this doc should be auto-generated.

```bash
cd hha-dashboard/api
uv run python scripts/openapi_to_md.py > ../docs/API_ENDPOINT_CATALOG.generated.md
```

(Script TBD — not yet built. Hand-curation is fine until the API surface stabilizes after Phase 2.)

---

**Next read:** [TROUBLESHOOTING.md](../04-operations/TROUBLESHOOTING.md) for what to do when one of these endpoints misbehaves.
