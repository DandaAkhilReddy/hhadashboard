# HHA Dashboard — SharePoint Deep Dive

> ⚠️ **STATUS: DEFERRED (2026-04-23).** The active ingestion pipeline is
> [UPLOAD_PIPELINE_PLAN.md](UPLOAD_PIPELINE_PLAN.md) — upload UI → Azure Blob → 15-min cron.
> The Graph API integration code in §1 below is no longer the primary path.
> Sections §2 (Entra app registration), §3 (Purview labels / DLP / retention), and §4
> (PowerShell provisioning) remain useful if/when the team wants a read-only SharePoint
> repository for contracts, historical Excel archives, and vendor BAAs in a later phase.

---

> Companion to [SHAREPOINT_PLAN.md](SHAREPOINT_PLAN.md). This doc goes layer-by-layer into the 4 most technical parts of the setup. Read top-to-bottom, or jump to a section via TOC.

## Table of contents

1. [§1 Graph API integration](#1-graph-api-integration) — full Python code for the dashboard reading PDFs from SharePoint
2. [§2 Entra app registration](#2-entra-app-registration-walkthrough) — every click in Azure portal
3. [§3 Purview setup](#3-purview-setup) — sensitivity labels + DLP + retention
4. [§4 PowerShell provisioning script](#4-powershell-provisioning-script) — one-shot `.ps1` that provisions the whole site

---

## §1 Graph API integration

### The flow

```
Crystal drops PDF in
┌───────────────────────────────────┐
│ SharePoint                        │
│  /sites/hha-dashboard             │
│  /Daily Uploads/Census/           │
│    /2026-04-23/                   │
│      westside-regional.pdf   ◀────┤ Crystal (via Teams app, OneDrive sync,
│      woodmont-hospital.pdf        │         or web UI)
│      jfk-main.pdf                 │
└──────────────┬────────────────────┘
               │
               │  Graph API: GET /drives/{id}/items/{folder}/children
               │  (runs every 30 min via Container App Job,
               │   OR webhook-triggered for near-real-time)
               ▼
       ┌────────────────────────────────┐
       │ Azure Container App Job        │
       │  sharepoint_ingest (Python)    │
       │                                │
       │  For each new PDF:             │
       │    1. Download bytes           │
       │    2. Extract via Doc Intel    │
       │    3. Save aggregate to DB     │
       │    4. Mark SP item "Processed" │
       │       (custom metadata column) │
       │    5. Log audit row            │
       └─────────────┬──────────────────┘
                     │
                     ▼
            ┌──────────────────┐
            │ Postgres         │
            │ entries.         │
            │ daily_entries    │
            └──────────────────┘
```

### Authentication options (pick one)

| Option | When | Pros | Cons |
|---|---|---|---|
| **Managed Identity (MI)** | Prod (Azure App Service / Container Apps) | No secrets, auto-rotated, tied to the resource | Only works inside Azure |
| **Client secret** | Dev / local testing | Works anywhere | Secret rotates; store in Key Vault |
| **Certificate** | High-security prod alternative | More robust than secret | More setup; cert renewal |

**Recommendation:** MI in prod, client secret in Key Vault for dev. Same code — `DefaultAzureCredential` picks the right one based on environment.

### Python dependencies

Add to `api/pyproject.toml`:

```toml
dependencies = [
    # ... existing ...
    "msgraph-sdk>=1.14.0",          # Microsoft Graph Python SDK
    "azure-identity>=1.19.0",       # DefaultAzureCredential (already there)
]
```

### Complete code — `jobs/sharepoint_ingest/main.py`

```python
"""SharePoint census-PDF ingestion job.

Runs every 30 min via Azure Container App Job cron.
Polls SharePoint /Daily Uploads/Census/ for unprocessed PDFs,
extracts census counts via Document Intelligence, writes
aggregates to Postgres, marks SharePoint items as processed.

Per ADR-001:
- PDF bytes live in memory only; no disk persistence in our infra
- Only Tier A aggregates land in Postgres
- Audit row written for every ingestion
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from azure.identity.aio import DefaultAzureCredential
from msgraph import GraphServiceClient
from msgraph.generated.models.field_value_set import FieldValueSet

# Our existing services
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "api"))
from app.models.entries import DailyEntry  # noqa: E402
from app.models.masters import Site  # noqa: E402
from app.services.pdf_extract import extract_census_from_pdf  # noqa: E402
from app.settings import settings  # noqa: E402

from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)

# Config (from env / Key Vault via Managed Identity)
TENANT_ID = os.environ["AZURE_TENANT_ID"]
SP_HOSTNAME = os.environ.get("SP_HOSTNAME", "hhamedicine.sharepoint.com")
SP_SITE_PATH = os.environ.get("SP_SITE_PATH", "/sites/hha-dashboard")
SP_CENSUS_FOLDER = os.environ.get("SP_CENSUS_FOLDER", "Daily Uploads/Census")
INGEST_SERVICE_UPN = "sharepoint-ingest@hhamedicine.com"  # identity logged in audit


async def resolve_site_id(graph: GraphServiceClient) -> str:
    """GET /sites/{hostname}:{site-path}  →  site.id"""
    site = await graph.sites.by_site_id(f"{SP_HOSTNAME}:{SP_SITE_PATH}").get()
    return site.id


async def resolve_drive_id(graph: GraphServiceClient, site_id: str) -> str:
    """The default document library is the 'drive' in Graph terminology."""
    drives = await graph.sites.by_site_id(site_id).drives.get()
    # Pick the 'Documents' drive (default), or iterate if multiple
    for drive in drives.value:
        if drive.name in ("Documents", "Shared Documents"):
            return drive.id
    raise RuntimeError(f"No default drive found on site {site_id}")


async def list_unprocessed_pdfs(
    graph: GraphServiceClient, site_id: str, drive_id: str, folder_path: str
):
    """List all PDFs under /Daily Uploads/Census/ where the custom 'Processed' column is not 'yes'.

    Uses Graph's $filter on driveItems with the `listItem.fields` expand.
    """
    # Get the folder item to scope the enumeration
    folder = await graph.drives.by_drive_id(drive_id).root.item_with_path(folder_path).get()
    # Children of the folder — recursive walk because we have date subfolders
    async for item in _walk(graph, drive_id, folder.id):
        if not item.file:
            continue
        if not item.name.lower().endswith(".pdf"):
            continue
        # Check the Processed column (custom) via listItem.fields
        list_item = await graph.drives.by_drive_id(drive_id).items.by_drive_item_id(item.id).list_item.get()
        fields = list_item.fields.additional_data if list_item.fields else {}
        if fields.get("Processed", "").lower() == "yes":
            continue
        yield item, list_item


async def _walk(graph, drive_id, folder_id):
    """Recursively iterate all items under a folder."""
    children = await graph.drives.by_drive_id(drive_id).items.by_drive_item_id(folder_id).children.get()
    for item in children.value:
        if item.folder:
            async for sub in _walk(graph, drive_id, item.id):
                yield sub
        else:
            yield item


async def download_pdf(graph: GraphServiceClient, drive_id: str, item_id: str) -> bytes:
    """Stream the file content into memory. NEVER writes to disk."""
    stream = await graph.drives.by_drive_id(drive_id).items.by_drive_item_id(item_id).content.get()
    return stream  # msgraph returns bytes directly for binary files


async def mark_processed(
    graph: GraphServiceClient,
    drive_id: str,
    item_id: str,
    *,
    matched_sites: int,
    sha256: str,
    notes: str = "",
) -> None:
    """Update the listItem's custom fields so we don't re-process.

    Requires a custom column `Processed` (Yes/No) on the document library.
    Add via SharePoint UI or the provisioning script (§4).
    """
    fields = FieldValueSet(
        additional_data={
            "Processed": "Yes",
            "ProcessedAt": datetime.now(timezone.utc).isoformat(),
            "ProcessedMatches": str(matched_sites),
            "ProcessedSha256": sha256,
            "ProcessedNotes": notes or "",
        }
    )
    await graph.drives.by_drive_id(drive_id).items.by_drive_item_id(item_id).list_item.fields.patch(
        fields
    )


async def save_entries(
    db: AsyncSession,
    *,
    extraction_matches: list,  # CensusExtractionResult.matches
    entry_date,
    pdf_sha256: str,
) -> int:
    """Upsert daily_entries rows for each matched site. Returns count of rows written."""
    # Fetch site_id → name map
    sites = {
        s.name: s.id for s in (await db.execute(select(Site))).scalars().all()
    }
    rows_written = 0
    for m in extraction_matches:
        site_id = sites.get(m.site_name)
        if site_id is None:
            log.warning("Skipping unknown site from extraction: %s", m.site_name)
            continue
        stmt = (
            pg_insert(DailyEntry)
            .values(
                site_id=site_id,
                entry_date=entry_date,
                census=m.census,
                open_shifts=0,  # not extracted from PDF; user can add later
                entered_by_upn=INGEST_SERVICE_UPN,
                source="pdf_extract",
                pdf_sha256=pdf_sha256,
            )
            .on_conflict_do_update(
                index_elements=["site_id", "entry_date"],
                set_=dict(
                    census=m.census,
                    source="pdf_extract",
                    pdf_sha256=pdf_sha256,
                    entered_by_upn=INGEST_SERVICE_UPN,
                    updated_at=datetime.now(timezone.utc),
                ),
            )
        )
        await db.execute(stmt)
        rows_written += 1
    await db.commit()
    return rows_written


async def process_one(
    graph: GraphServiceClient,
    db: AsyncSession,
    site_id: str,
    drive_id: str,
    item,
    list_item,
    known_site_names: list[str],
) -> None:
    """Ingest one PDF end-to-end."""
    log.info("Processing %s (id=%s)", item.name, item.id)
    try:
        pdf_bytes = await download_pdf(graph, drive_id, item.id)
        sha256 = hashlib.sha256(pdf_bytes).hexdigest()

        result = await extract_census_from_pdf(pdf_bytes, known_sites=known_site_names)
        if not result.matches:
            log.warning("No matches extracted from %s — marking processed with 0 matches", item.name)
            await mark_processed(graph, drive_id, item.id, matched_sites=0, sha256=sha256,
                                 notes="No tables matched known sites")
            return

        # Derive entry_date from folder name (YYYY-MM-DD) or fall back to item's lastModifiedDateTime
        entry_date = _derive_entry_date(item, list_item)

        rows = await save_entries(db, extraction_matches=result.matches, entry_date=entry_date,
                                   pdf_sha256=sha256)

        await mark_processed(graph, drive_id, item.id, matched_sites=rows, sha256=sha256)
        log.info("✓ %s → %d daily_entries rows", item.name, rows)

    except Exception:
        log.exception("Failed to process %s", item.name)
        # Don't mark as processed — next run will retry. After 3 failures,
        # an alert fires (Azure Monitor rule on job exit code / log events).
        raise


def _derive_entry_date(item, list_item):
    """Prefer the folder name if it's a YYYY-MM-DD date, else item's lastModifiedDateTime."""
    from datetime import date, datetime as dt
    import re
    parent_name = item.parent_reference.path.split("/")[-1] if item.parent_reference else ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", parent_name)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # Fallback
    return item.last_modified_date_time.date() if item.last_modified_date_time else dt.utcnow().date()


async def main() -> None:
    log.info("sharepoint_ingest.start")
    # Auth — DefaultAzureCredential picks MI in Azure, client secret locally
    credential = DefaultAzureCredential()
    graph = GraphServiceClient(credential, scopes=["https://graph.microsoft.com/.default"])

    site_id = await resolve_site_id(graph)
    drive_id = await resolve_drive_id(graph, site_id)
    log.info("site_id=%s drive_id=%s", site_id, drive_id)

    # Open DB session
    engine = create_async_engine(settings.database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionLocal() as db:
        known_site_names = [
            s.name for s in (await db.execute(select(Site))).scalars().all()
        ]
        processed = 0
        async for item, list_item in list_unprocessed_pdfs(
            graph, site_id, drive_id, SP_CENSUS_FOLDER
        ):
            await process_one(graph, db, site_id, drive_id, item, list_item, known_site_names)
            processed += 1

    await engine.dispose()
    await credential.close()
    log.info("sharepoint_ingest.done processed=%d", processed)


if __name__ == "__main__":
    asyncio.run(main())
```

### Real-time via webhooks (optional upgrade)

Polling every 30 min is fine for MVP. For sub-minute latency, subscribe to a Graph change notification on the Census folder:

```python
# One-time subscription creation (store the subscription id; renew before expiration)
subscription = {
    "changeType": "updated,created",
    "notificationUrl": "https://api-hha.azurewebsites.net/webhooks/sharepoint",
    "resource": f"/drives/{DRIVE_ID}/root:/{SP_CENSUS_FOLDER}",
    "expirationDateTime": "2026-05-23T00:00:00Z",  # max 43200 min = 30 days, renew
    "clientState": "<random-string-you-generated>",  # echoed back for verification
}
r = await graph.subscriptions.post(subscription)
```

Then a FastAPI webhook endpoint:

```python
@router.post("/webhooks/sharepoint")
async def sharepoint_webhook(request: Request):
    # Handshake for subscription validation
    if "validationToken" in request.query_params:
        return PlainTextResponse(request.query_params["validationToken"])
    # Real change notification — enqueue a fast path
    body = await request.json()
    for notification in body["value"]:
        # verify clientState matches our stored value
        await queue_processing.put(notification["resource"])
    return {"status": "accepted"}
```

Webhooks only arrive in "push" direction; we still pull the actual file via Graph.

### Error handling + idempotency

- **Idempotent via `ProcessedSha256`**: if we re-download the same PDF (network retry, reprocessing), `save_entries` upserts on `(site_id, entry_date)` so no duplicate rows.
- **Retry policy**: Container App Job has `retry: 3` in its spec. Exit code > 0 triggers retry.
- **Dead-letter**: after 3 failures, the SharePoint item gets `Processed: error` (not `yes`). Runbook: a human reviews `/Daily Uploads/Census/` for any `Processed: error` item weekly.
- **PHI leak prevention**: downloaded bytes are never logged. If extraction fails, the exception is logged, but the `pdf_bytes` variable is never included in log fields.

### Tests

`jobs/sharepoint_ingest/tests/test_ingest.py`:

```python
# Mock the Graph SDK + Document Intelligence SDK.
# Assert: given a fixture response with 3 matches, save_entries inserts 3 rows
# and mark_processed is called once with the correct sha256.
```

---

## §2 Entra app registration walkthrough

Goal: create an Entra app that can read/write only the **HHA Dashboard** SharePoint site, nothing else. Uses the least-privilege `Sites.Selected` pattern, not the big-hammer `Sites.Read.All`.

### Click-by-click

#### A. Create the app registration

1. Go to <https://entra.microsoft.com> → sign in as areddy@hhamedicine.com
2. Left sidebar → **Applications** → **App registrations** → **+ New registration**
3. Fill:
   - **Name**: `hha-dashboard-sharepoint`
   - **Supported account types**: "Accounts in this organizational directory only (hhamedicine only — Single tenant)"
   - **Redirect URI**: leave blank (this is a daemon app, no user login flow)
4. Click **Register**
5. On the overview page, copy and save:
   - **Application (client) ID** → `AZURE_SP_CLIENT_ID` env var
   - **Directory (tenant) ID** → `AZURE_TENANT_ID` env var (same tenant as the main app)

#### B. Configure API permissions

1. Left menu on the app page → **API permissions** → **+ Add a permission**
2. Pick **Microsoft Graph** → **Application permissions** (NOT "Delegated")
3. Search for and add these:
   - **`Sites.Selected`** — the least-privilege one. With this + step D below, the app sees ONLY the HHA Dashboard site, nothing else in SharePoint.
   - **`User.Read.All`** — OPTIONAL, only if you want the job to resolve UPN → display name for audit logs. Skip for strictest setup.
4. Click **Grant admin consent for HHA Medicine** (the big blue button at the top — you need Global Admin or Privileged Role Admin)
5. Status of each permission should now show a green check with "Granted for HHA Medicine"

> ❌ **Do not** add `Sites.Read.All` or `Sites.FullControl.All` — those grant access to every site in the tenant. Over-privileged. `Sites.Selected` + explicit site grant is correct.

#### C. Create a client secret (for local dev; prod uses Managed Identity)

1. Left menu → **Certificates & secrets** → **Client secrets** → **+ New client secret**
2. Description: `dev-2026-04-to-2026-10`
3. Expires: **6 months** (rotation discipline)
4. Click **Add**
5. **Copy the `Value`** IMMEDIATELY (you won't see it again). Store it:
   - Dev: write to Key Vault under name `sharepoint-client-secret`; your local `.env` has `AZURE_SP_CLIENT_SECRET=<value>` pulled from there
   - Prod: NEVER use this secret — Managed Identity handles auth

#### D. Grant site-specific permission

The secret lets the app authenticate. But the app has `Sites.Selected`, which means zero SharePoint access until you grant it to a specific site.

Use Microsoft Graph Explorer to grant:

1. Go to <https://developer.microsoft.com/en-us/graph/graph-explorer>
2. Sign in as areddy@ (you need SharePoint admin or global admin)
3. First, find the site ID. Run:

   ```
   GET https://graph.microsoft.com/v1.0/sites/hhamedicine.sharepoint.com:/sites/hha-dashboard
   ```

   Response includes `"id": "hhamedicine.sharepoint.com,<site-guid>,<web-guid>"`. Copy the full ID string.
4. Now grant the app:

   ```
   POST https://graph.microsoft.com/v1.0/sites/{site-id}/permissions
   Content-Type: application/json

   {
     "roles": ["write"],
     "grantedToIdentities": [{
       "application": {
         "id": "<AZURE_SP_CLIENT_ID from step A>",
         "displayName": "hha-dashboard-sharepoint"
       }
     }]
   }
   ```

   Pick `read` if the app only needs to read; `write` lets it update the `Processed` metadata column.

#### E. Test from curl

Get an access token (dev only — use the secret):

```bash
TENANT_ID=<your-tenant-id>
CLIENT_ID=<your-app-client-id>
CLIENT_SECRET=<your-secret>

TOKEN=$(curl -s -X POST \
  "https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=${CLIENT_ID}" \
  -d "client_secret=${CLIENT_SECRET}" \
  -d "scope=https://graph.microsoft.com/.default" \
  | jq -r .access_token)

# Verify: list drives in our site
curl -H "Authorization: Bearer $TOKEN" \
  "https://graph.microsoft.com/v1.0/sites/hhamedicine.sharepoint.com:/sites/hha-dashboard:/drives"

# Expect: JSON array including the "Documents" library. Any other site → 403.
```

If the final curl returns the drives list, Graph auth is working and scope is correct.

#### F. Switch to Managed Identity in prod

When the app runs on Azure App Service or Container Apps:

1. Enable **System-assigned Managed Identity** on the resource (portal → Identity → On)
2. In Graph Explorer, run the same `POST /permissions` grant as step D, but with:

   ```json
   "grantedToIdentities": [{
     "application": {
       "id": "<managed-identity-object-id>",
       "displayName": "hha-dashboard-api (MI)"
     }
   }]
   ```

   (Find MI object ID via `az ad sp list --display-name hha-dashboard-api`.)
3. Your Python code uses `DefaultAzureCredential()` — no secret needed. Managed Identity is automatically used.
4. You can now remove `AZURE_SP_CLIENT_SECRET` from App Service config. Fewer secrets = fewer leak paths.

### Secret rotation runbook

Every 6 months:

1. Create a new secret (Step C)
2. Update Key Vault's `sharepoint-client-secret`
3. Restart the App Service / Container Apps Job to pick up the new secret
4. **Delete** the old secret from the app registration

In prod with MI you don't rotate — Azure handles it.

### Why `Sites.Selected` over `Sites.Read.All`

With `Sites.Read.All`, a compromised app secret gives the attacker read access to *every* SharePoint site in the tenant — HR files, legal, board minutes, everything. With `Sites.Selected` + explicit grant, the attacker sees only the HHA Dashboard site. **Blast radius reduction is worth the 5 extra minutes of setup.**

---

## §3 Purview setup

Purview is Microsoft's compliance suite — Sensitivity Labels, DLP, Retention, Audit. Accessed at <https://compliance.microsoft.com>.

**Licensing check:** confirm HHA has one of: M365 E3 + E3 Compliance add-on, M365 E5, or M365 Business Premium. Without these, labels + DLP aren't available. Retention is included in E3 without add-on.

### A. Sensitivity labels

Labels are tags that travel with files — when a labeled file is downloaded, the label goes with it. Labels enforce encryption, block external sharing, and show a visual marker in Office apps.

#### Create `HHA-Internal-Confidential`

1. <https://compliance.microsoft.com> → **Information protection** → **Labels** tab → **+ Create a label**
2. **Name**: `HHA-Internal-Confidential`
3. **Display name**: `HHA Internal — Confidential`
4. **Description for users**: "HHA internal business information. Do not share externally."
5. **Description for admins**: "Applied to Planning, Contracts, Vendor Communications, Historical Data/HR."
6. **Scope**: check **Files & emails** and **Groups & sites** → Next
7. **Protection settings** → **Encrypt** → **Configure encryption settings**:
   - Assign permissions:
     - **Owner**: HHA-Dashboard-Owners group (full control)
     - **Co-author**: HHA-Dashboard-Members group (read, edit, copy, print, but no forward)
   - **Content expires**: Never
   - **Allow offline access**: 30 days
8. **Content marking** → on → add footer: `HHA Medicine — Confidential. Internal use only.`
9. **Auto-labeling for files** → off (we'll apply manually to libraries)
10. **Labels for Groups & sites**:
    - Privacy: Private
    - External user access: Never
    - External sharing: Disabled
    - Conditional access: Require healthy device (optional, needs Intune)
11. **Review & create** → **Create label**

#### Create `HHA-PHI-Restricted`

Repeat with tighter settings:

1. Name: `HHA-PHI-Restricted`
2. Display: `HHA PHI — Restricted`
3. Scope: **Files & emails only** (we don't use it on sites)
4. **Encrypt** with these permissions:
   - **Reviewer** (not Owner): HHA-Dashboard-Owners (read, edit, but no export)
   - **Service account**: `sharepoint-ingest-mi@hhamedicine.com` (read only — the job)
5. **Content expires**: 7 days (auto-revoke access on expiration)
6. **Offline access**: Disabled (no caching of PHI)
7. **Content marking**: footer `HHA PHI — Restricted. Do not forward, print, or export.`
8. Create

#### Publish labels

Labels exist but aren't available until published:

1. **Labels** → **Label policies** → **+ Publish labels**
2. Pick both labels
3. **Users and groups**: HHA-Dashboard-Owners + HHA-Dashboard-Members
4. **Policy settings**:
   - Default label: None (user picks)
   - Require justification for label downgrade: Yes
5. **Name**: `HHA Dashboard Labels` → Publish

Wait 30–60 min for Office apps to see the labels.

#### Apply labels to SharePoint libraries

1. Go to the site → `Contracts` library → ⚙ **Library settings** → **Apply label**
2. Pick `HHA-Internal-Confidential` → All new + existing items get labeled
3. Repeat for `Historical Data` and `Vendor Communications`
4. For `Daily Uploads/Census`: apply `HHA-PHI-Restricted`

### B. Data Loss Prevention (DLP)

DLP detects sensitive patterns (SSN, MRN, credit cards) in files and takes action.

1. <https://compliance.microsoft.com> → **Data loss prevention** → **Policies** → **+ Create policy**
2. **Category**: Custom
3. **Name**: `HHA Dashboard — Sensitive Data Detection`
4. **Locations**: pick **SharePoint sites** → **Edit** → include only the HHA Dashboard site URL
5. **Policy settings** → **Create or customize advanced DLP rules**:

   **Rule 1: Detect and block SSN**
   - Condition: content contains sensitive info type **"U.S. Social Security Number (SSN)"** with >=1 instance and confidence medium+
   - Action:
     - **Restrict access**: Block only external users (internal users can still see it)
     - **Notify**: areddy@ + user
     - **Justification**: require business justification to override
   - **Incident report**: high severity, email areddy@

   **Rule 2: Detect MRN**
   - Sensitive info type: create a custom one if not present — regex `\bMRN[:\s]*\d{6,10}\b`
   - Action: same as SSN

   **Rule 3: Detect US Bank account / Credit card**
   - Built-in info types: "U.S. Bank Account Number" + "Credit Card Number"
   - Action: same

6. **Mode**: **Turn on immediately**
7. Create

### C. Retention policies

Retention = how long files must be kept and when they auto-delete.

#### Policy 1: `Daily Uploads/Census` — 7-day delete

1. **Data lifecycle management** → **Retention policies** → **+ New retention policy**
2. Name: `HHA Census PDF Retention`
3. Locations: **SharePoint sites** → HHA Dashboard site → **Choose sites** → click into the site's Daily Uploads library
4. Retention settings:
   - **Retain items for a specific period**: 7 days
   - **After the retention period**: **Delete items automatically**
   - **Start the retention period based on**: item creation date
5. Create

#### Policy 2: Contracts / Historical Data / Vendor Communications — 7-year retain

1. New retention policy: `HHA Compliance 7-Year`
2. Locations: same site, pick those libraries
3. Retain 2555 days (7 years), then **Trigger review** (don't auto-delete contracts)
4. Create

#### Policy 3: Meeting notes — 3-year retain

1. `HHA Decisions 3-Year`
2. Library: `Decisions + Meeting Notes`
3. Retain 1095 days, then auto-delete
4. Create

### D. Unified Audit Log

1. **Audit** section of compliance portal → **Start recording user and admin activity** (one-time enable)
2. Audit is now capturing every SharePoint action (file viewed, downloaded, permission changed, etc.)
3. Retention: 90 days on E3, 1 year on E5. Export older to Azure Storage via a scheduled runbook if needed.

#### Useful audit queries

```
# Who downloaded from Contracts in the last 30 days?
Activities: FileDownloaded
File location: contains "/sites/hha-dashboard/Contracts/"
Date range: last 30 days

# External sharing attempts (should be 0 given external sharing is off)
Activities: SharingInvitationCreated
Users: any
```

---

## §4 PowerShell provisioning script

One-shot script that provisions the entire site. Run as SharePoint admin. ~3 minutes to execute.

### Prerequisites

```powershell
# Install once
Install-Module -Name PnP.PowerShell -Scope CurrentUser -Force
Install-Module -Name Microsoft.Graph -Scope CurrentUser -Force
```

### Save as `scripts/provision-sharepoint.ps1`

```powershell
<#
.SYNOPSIS
  Provisions the HHA Dashboard SharePoint site end-to-end.
.DESCRIPTION
  Creates the site, libraries, folders, permission groups, applies labels,
  grants the hha-dashboard-sharepoint Entra app read/write access.
.PARAMETER TenantDomain
  e.g., "hhamedicine" (not the full .onmicrosoft.com)
.PARAMETER SharePointAppId
  Client ID of the `hha-dashboard-sharepoint` Entra app registration (from §2).
.EXAMPLE
  .\provision-sharepoint.ps1 -TenantDomain "hhamedicine" -SharePointAppId "<client-id>"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$TenantDomain,
    [Parameter(Mandatory = $true)][string]$SharePointAppId,
    [string]$SiteAlias = "hha-dashboard",
    [string]$SiteTitle = "HHA Dashboard"
)

$ErrorActionPreference = "Stop"
$AdminUrl = "https://$TenantDomain-admin.sharepoint.com"
$SiteUrl  = "https://$TenantDomain.sharepoint.com/sites/$SiteAlias"

Write-Host "[1/8] Connect to SharePoint admin..." -ForegroundColor Cyan
Connect-PnPOnline -Url $AdminUrl -Interactive

# --- Create site ---
Write-Host "[2/8] Create Team site if not exists..." -ForegroundColor Cyan
$existing = Get-PnPTenantSite -Url $SiteUrl -ErrorAction SilentlyContinue
if (-not $existing) {
    New-PnPSite `
        -Type TeamSite `
        -Title $SiteTitle `
        -Alias $SiteAlias `
        -Description "HHA Dashboard project workspace — planning, contracts, historical data, daily PDF uploads" `
        -IsPublic:$false `
        -TimeZone UTCMinus05EasternTimeUSAndCanada | Out-Null
    Write-Host "  Created $SiteUrl" -ForegroundColor Green
} else {
    Write-Host "  Site already exists at $SiteUrl" -ForegroundColor Yellow
}

# Switch connection to the new site
Connect-PnPOnline -Url $SiteUrl -Interactive

# --- Permission groups ---
# Default Owners/Members/Visitors groups auto-created by Team site.
# Rename for clarity + add the Entra security groups as members.
Write-Host "[3/8] Permission groups..." -ForegroundColor Cyan
$owners   = Get-PnPGroup -AssociatedOwnerGroup
$members  = Get-PnPGroup -AssociatedMemberGroup
$visitors = Get-PnPGroup -AssociatedVisitorGroup
Write-Host "  Owners=$($owners.Title)  Members=$($members.Title)  Visitors=$($visitors.Title)"

# Optional: add your Entra security groups here if they exist
# Add-PnPGroupMember -Identity $owners.Title -LoginName "c:0o.c|federateddirectoryclaimprovider|<HHA-Dashboard-Owners-ObjectId>"
# Add-PnPGroupMember -Identity $members.Title -LoginName "c:0o.c|federateddirectoryclaimprovider|<HHA-Dashboard-Members-ObjectId>"

# --- Libraries ---
$libraries = @(
    @{ Name = "Planning";              Description = "Build plan, architecture, ADRs, mockups" },
    @{ Name = "Contracts";             Description = "Hospital + vendor + BAA contracts" },
    @{ Name = "Historical Data";       Description = "12-month Excel backfills: finance, census, HR" },
    @{ Name = "Daily Uploads";         Description = "PDF drop zone (auto-delete after 7 days)" },
    @{ Name = "Vendor Communications"; Description = "Ventra, Paycom, hospital correspondence" },
    @{ Name = "Decisions";             Description = "Meeting notes + decisions log" }
)

Write-Host "[4/8] Create document libraries..." -ForegroundColor Cyan
foreach ($lib in $libraries) {
    $existing = Get-PnPList -Identity $lib.Name -ErrorAction SilentlyContinue
    if (-not $existing) {
        New-PnPList -Title $lib.Name -Template DocumentLibrary -Url $lib.Name.Replace(' ', '') | Out-Null
        Set-PnPList -Identity $lib.Name -Description $lib.Description | Out-Null
        Write-Host "  + $($lib.Name)" -ForegroundColor Green
    } else {
        Write-Host "  = $($lib.Name) (exists)" -ForegroundColor Yellow
    }
}

# --- Folder structure ---
Write-Host "[5/8] Create folders..." -ForegroundColor Cyan
$folders = @(
    "Contracts/Florida",
    "Contracts/Texas",
    "Contracts/Vendor",
    "Historical Data/Finance",
    "Historical Data/Census",
    "Historical Data/HR",
    "Daily Uploads/Census",
    "Vendor Communications/Ventra",
    "Vendor Communications/Paycom",
    "Vendor Communications/Hospitals",
    "Decisions/Weekly-standup",
    "Decisions/CEO-CFO-sponsor-reviews",
    "Planning/adr"
)
foreach ($f in $folders) {
    $parts = $f.Split('/', 2)
    $list = $parts[0]
    $path = $parts[1]
    $target = "$list/$path"
    try {
        Resolve-PnPFolder -SiteRelativePath $target | Out-Null
        Write-Host "  + $target" -ForegroundColor Green
    } catch {
        Write-Host "  ! $target failed: $_" -ForegroundColor Red
    }
}

# --- Custom "Processed" column on Daily Uploads for Graph-API ingestion ---
Write-Host "[6/8] Add Processed metadata column on Daily Uploads..." -ForegroundColor Cyan
$existing = Get-PnPField -List "Daily Uploads" -Identity "Processed" -ErrorAction SilentlyContinue
if (-not $existing) {
    Add-PnPField -List "Daily Uploads" -DisplayName "Processed" `
                 -InternalName "Processed" -Type Choice -Choices "No","Yes","error" | Out-Null
    Add-PnPField -List "Daily Uploads" -DisplayName "ProcessedAt" `
                 -InternalName "ProcessedAt" -Type DateTime | Out-Null
    Add-PnPField -List "Daily Uploads" -DisplayName "ProcessedMatches" `
                 -InternalName "ProcessedMatches" -Type Number | Out-Null
    Add-PnPField -List "Daily Uploads" -DisplayName "ProcessedSha256" `
                 -InternalName "ProcessedSha256" -Type Text | Out-Null
    Add-PnPField -List "Daily Uploads" -DisplayName "ProcessedNotes" `
                 -InternalName "ProcessedNotes" -Type Note | Out-Null
    Write-Host "  Added 5 Processed-* columns" -ForegroundColor Green
} else {
    Write-Host "  Processed column already exists" -ForegroundColor Yellow
}

# --- Break inheritance + set per-library permissions ---
Write-Host "[7/8] Break permission inheritance on sensitive libraries..." -ForegroundColor Cyan
foreach ($lib in @("Contracts", "Historical Data", "Daily Uploads", "Vendor Communications")) {
    Set-PnPList -Identity $lib -BreakRoleInheritance -CopyRoleAssignments:$false -ClearSubscopes | Out-Null
    # Grant Owners full control
    Set-PnPListPermission -Identity $lib -User $owners.Title -AddRole "Full Control" | Out-Null
    Write-Host "  Hardened: $lib" -ForegroundColor Green
}

# Members get Read on all libraries by default (inherited from site root). Customize further per §4 of main plan:
# Set-PnPListPermission -Identity "Contracts" -User $members.Title -RemoveRole "Read"  # if ultra-strict

# --- Grant the Entra app Sites.Selected access ---
Write-Host "[8/8] Grant $SharePointAppId Read+Write on this site..." -ForegroundColor Cyan
# Requires Microsoft.Graph module
Connect-MgGraph -Scopes "Sites.FullControl.All" -NoWelcome

$site = Invoke-MgGraphRequest -Method GET `
    -Uri "https://graph.microsoft.com/v1.0/sites/$TenantDomain.sharepoint.com:/sites/$SiteAlias"
$siteId = $site.id

$body = @{
    roles = @("write")
    grantedToIdentities = @(
        @{
            application = @{
                id = $SharePointAppId
                displayName = "hha-dashboard-sharepoint"
            }
        }
    )
} | ConvertTo-Json -Depth 5

Invoke-MgGraphRequest -Method POST `
    -Uri "https://graph.microsoft.com/v1.0/sites/$siteId/permissions" `
    -Body $body -ContentType "application/json" | Out-Null

Write-Host "  ✓ Graph app granted write access" -ForegroundColor Green

Write-Host ""
Write-Host "Done. Site: $SiteUrl" -ForegroundColor Green
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  - Add HHA-Dashboard-Members group members via site UI"
Write-Host "  - Apply sensitivity labels via compliance portal (§3)"
Write-Host "  - Configure retention policies via compliance portal (§3)"
Write-Host "  - Upload initial Planning docs from OneDrive"
```

### Run it

```powershell
.\scripts\provision-sharepoint.ps1 `
    -TenantDomain "hhamedicine" `
    -SharePointAppId "<YOUR-APP-CLIENT-ID-FROM-§2>"
```

Two interactive login prompts: one for SharePoint admin, one for Graph API (for the app permission grant). Each opens a browser window — sign in as areddy@, approve.

Total elapsed: ~3 minutes. Afterward, the site is fully provisioned with:

- 6 libraries, 13 folders
- Hardened permissions on sensitive libraries
- Custom `Processed*` columns on Daily Uploads for ingestion
- Entra app has write access to only this site

### Idempotency

The script is safe to re-run. Existing libraries/folders are detected and skipped (yellow `=` log line). You can use the same script in staging/test tenants by changing `-TenantDomain`.

### Teardown script (if you ever need to start over)

```powershell
# DANGEROUS — deletes the whole site and its contents
Connect-PnPOnline -Url "https://$TenantDomain-admin.sharepoint.com" -Interactive
Remove-PnPTenantSite -Url "https://$TenantDomain.sharepoint.com/sites/hha-dashboard" -Force
# Site goes to recycle bin for 93 days; truly delete via:
Remove-PnPTenantDeletedSite -Url "https://$TenantDomain.sharepoint.com/sites/hha-dashboard" -Force
```

---

## What to do after running this deep-dive

1. **Have SHAREPOINT_PLAN.md open** to understand the big picture
2. **Do §2 (Entra app registration) first** — ~10 min. You need the `SharePointAppId` before step 8 of the PowerShell script works.
3. **Run §4 (PowerShell)** — ~3 min. Site is live.
4. **Do §3 (Purview)** — ~20 min. Labels, DLP, retention.
5. **Then §1 becomes relevant** — when we're ready to build the SharePoint ingestion job in Session 4+.

Total: ~35 min of your admin time. The Session 1 SHAREPOINT_PLAN.md sections 1-9 already cover the non-deep-dive bits (site UI layout, members, initial content upload).

---

_Draft 2026-04-23. Expect ~1.5 hours to read + understand + execute end-to-end._
