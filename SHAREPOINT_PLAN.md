# HHA Dashboard — SharePoint Companion Site Plan

> ⚠️ **STATUS: DEFERRED (2026-04-23).** The active direction for data ingestion is
> **[UPLOAD_PIPELINE_PLAN.md](UPLOAD_PIPELINE_PLAN.md)** — upload UI inside the dashboard →
> Azure Blob Storage → 15-min cron job. SharePoint still has value for the read-only
> artifacts (contracts library, historical Excel archive, vendor BAAs) in a future phase,
> but the PDF-drop-for-ingestion part of this plan is replaced by Blob + cron.
>
> Keep this doc for reference when we add the contracts / BAA repository later.

---

> Execute as **areddy@hhamedicine.com** (M365 Global Admin or SharePoint Admin). Most steps are 5 min in the M365 admin portal. Advanced automation is optional.

---

## 1. Purpose

A **single private SharePoint site** that serves the HHA Dashboard project as:

- **Document repository** — planning docs (DASHBOARD_PLAN, Architecture, ADR-001, UI mockups), hospital contracts, vendor BAAs, historical Excel backfills
- **PDF drop zone** (Session 4+) — Crystal drops daily census PDFs into a dedicated folder; our Azure Function picks them up via Graph API, runs extraction, writes aggregates to Postgres
- **Team collaboration** — links to Teams channel, meeting notes, vendor correspondence (Ventra, Paycom)

**What it is NOT:**

- Not a replacement for the dashboard database (Postgres stays the system of record for operational data)
- Not a general-purpose HHA intranet (tight scope: project-only)
- Not a PHI data store (files with PHI get sensitivity labels; census PDFs get auto-deleted after our app ingests them — see §5)

---

## 2. Site identity

| | |
|---|---|
| **Site type** | Team site (Microsoft 365 Group-backed — gets a Teams channel + Planner + mailbox for free) |
| **Site name** | `HHA Dashboard` |
| **URL** | `https://hhamedicine.sharepoint.com/sites/hha-dashboard` |
| **Privacy** | **Private** — only invited members see it |
| **Language** | English (US) |
| **Time zone** | (UTC-05:00) Eastern Time |
| **M365 Group alias** | `hha-dashboard@hhamedicine.com` (auto-created, distribution list for announcements) |
| **Storage quota** | Default 25 TB (we'll use ~1 GB — no worries) |
| **External sharing** | **Disabled** at the site level (tenant default should already be restrictive; double-check) |

---

## 3. Document libraries (the folder structure)

Create these libraries inside the site. Each has different permissions (§4).

```
HHA Dashboard (site root)
│
├── 📘 Planning                          [read: Members; write: Owners]
│   ├── DASHBOARD_PLAN.md
│   ├── Architecture.md
│   ├── SHAREPOINT_PLAN.md               (this file)
│   ├── UI_MOCKUP_v5.html
│   ├── VENTRA_REPLY_DRAFT.md
│   └── adr/
│       └── 001-hipaa-data-classification.md
│
├── 📑 Contracts                         [read: Owners + owner_finance; write: Owners]
│   ├── Florida/
│   │   ├── Westside-Regional-2024-2027.pdf
│   │   ├── Woodmont-Hospital-2024-2027.pdf
│   │   └── ...
│   ├── Texas/
│   └── Vendor/
│       ├── Ventra-MSA.pdf
│       ├── Ventra-BAA.pdf
│       ├── Paycom-agreement.pdf
│       └── Microsoft-BAA-HHA-2026.pdf
│
├── 📊 Historical Data                   [read: Members; write: owner_finance + owner_hr]
│   ├── Finance/
│   │   ├── Collections-2024.xlsx
│   │   ├── AR-Aging-monthly-2024.xlsx
│   │   └── ...
│   ├── Census/
│   │   └── Daily-census-history-2025.xlsx
│   └── HR/
│       ├── Turnover-2024.xlsx
│       └── OpenPositions-2024.xlsx
│
├── 📥 Daily Uploads                     [upload-only: owner_ops; read: Owners]
│   └── Census/                          ← Crystal drops PDFs here (Session 4+ integration)
│       └── <YYYY-MM-DD>/
│           └── <site-name>.pdf
│       (auto-deleted by retention policy after 7 days — see §5)
│
├── 📩 Vendor Communications             [read: Owners; write: Owners]
│   ├── Ventra/
│   ├── Paycom/
│   └── Hospitals/
│       ├── HCA-Florida/
│       └── Jackson-Health/
│
└── 🎯 Decisions + Meeting Notes         [read: Members; write: Members]
    ├── Weekly-standup/
    ├── CEO-CFO-sponsor-reviews/
    └── Decisions-log.xlsx
```

---

## 4. Access model (3 Microsoft 365 groups)

Create these three Microsoft 365 groups (not Entra security groups — M365 groups for SharePoint/Teams). Or reuse the Entra security groups from the v5 plan.

| Group | Members | SharePoint role |
|---|---|---|
| **HHA-Dashboard-Owners** | areddy@ + CEO + CFO + COO + CMO | Owner — full control, can add members, change settings |
| **HHA-Dashboard-Members** | Crystal, Sandy, Maribel, Andrea, Dr. Aneja, Dr. Reddy + Owners | Member — read everything they have access to; write to their authorized libraries |
| **HHA-Dashboard-Visitors** | *(empty for now — tight control)* | Visitor — read-only everywhere |

**Library-level permissions** break inheritance from the site root for:

- `Contracts` — only Owners + `owner_finance`-group members (Sandy, Maribel) can read; only Owners can write
- `Historical Data` — Members read, but only `owner_finance` + `owner_hr` + Owners can write
- `Daily Uploads / Census` — `owner_ops` (Crystal) + Owners can upload; read restricted to Owners (the app reads via app-only credential)

**External sharing:** disabled. No "Share with link" for anyone outside the tenant.

---

## 5. HIPAA + security

### Sensitivity labels (M365 E3/E5 feature — Purview)

Apply these to the sensitive libraries:

- `HHA-Internal-Confidential` — on `Contracts`, `Vendor Communications`, `Historical Data/HR`
  - Encrypts files at rest with HHA-managed keys
  - Blocks "Share externally" and "Copy to personal OneDrive"
  - Requires "Work or school account" to open
- `HHA-PHI-Restricted` — on `Daily Uploads/Census`
  - Highest restriction. Files auto-deleted after 7 days (retention policy below)
  - Only service accounts + Crystal can access
  - Audit log on every read

### Retention policy (Purview Retention → add a policy)

- **Daily Uploads/Census**: retain 7 days, then permanent delete (the app ingests within hours; no reason to keep raw PDFs)
- **Planning, Contracts, Vendor Communications**: retain 7 years (healthcare standard)
- **Historical Data**: retain 7 years
- **Decisions + Meeting Notes**: retain 3 years

### DLP (Data Loss Prevention) policy

Create a DLP policy scoped to this site that detects and blocks:

- US SSN patterns
- Medical Record Number patterns
- Credit card numbers

Action: block upload + notify areddy@ on match.

### Audit

- Turn on **unified audit log** for the site (Purview → Audit). Keeps 90 days by default on E3, 1 year on E5.
- Export quarterly to the dashboard's `audit.audit_log`-adjacent storage if we want joined audit trail. Not critical for MVP.

---

## 6. Integration with the dashboard app (Session 4+)

Once the dashboard app needs to read from SharePoint:

### Read-only flow — app pulls from SharePoint

1. Register an **Entra app registration** `hha-dashboard-sharepoint-reader` (separate from the web/api apps)
2. Grant it **application permission** `Sites.Selected` (least privilege — needs admin consent)
3. Grant this app **Read** access to ONLY this site via Graph API:

   ```powershell
   # Run as SharePoint admin
   Grant-PnPAzureADAppSitePermission `
       -AppId <sharepoint-reader-app-id> `
       -DisplayName "HHA Dashboard API" `
       -Site "https://hhamedicine.sharepoint.com/sites/hha-dashboard" `
       -Permissions Read
   ```

4. In FastAPI or the Azure Function, use `azure-identity` + Microsoft Graph SDK:

   ```python
   from azure.identity import DefaultAzureCredential
   from msgraph import GraphServiceClient

   credential = DefaultAzureCredential()
   graph = GraphServiceClient(credential, ["https://graph.microsoft.com/.default"])

   # List new PDFs in Daily Uploads/Census folder
   items = await graph.sites.by_site_id(SITE_ID).drives.by_drive_id(DRIVE_ID)
       .items.by_item_id(FOLDER_ID).children.get()
   ```

5. Cron job (Container Apps Job) runs every 30 min, checks for new PDFs, downloads + extracts + saves aggregates, then marks the PDF as processed (custom metadata column)

### Upload flow — Crystal drops a PDF

- **Path A (simpler, Session 3):** Crystal uploads directly to the dashboard app (`/entry/daily-census` page, PDF tab). App extracts in memory, discards. SharePoint NOT used for census.
- **Path B (Session 4+):** Crystal also has the option to drop the PDF into `HHA Dashboard / Daily Uploads / Census / <YYYY-MM-DD>/` folder from Windows Explorer (synced via OneDrive) or Teams. Our job picks it up within 30 min. Nice for days when she doesn't want to sign in to the dashboard.

Both paths end with the same aggregate in Postgres.

---

## 7. Setup checklist (for areddy@ to execute)

Estimated time: **30 minutes** from start to fully provisioned.

### Step 1 — Create the site (5 min)

1. Go to <https://hhamedicine.sharepoint.com/_layouts/15/sharepoint.aspx>
2. Click **+ Create site** → **Team site**
3. Fill:
   - Name: `HHA Dashboard`
   - Group email: `hha-dashboard@hhamedicine.com`
   - Privacy: **Private**
   - Language: English (US)
4. Add initial owners: yourself (areddy@) + CEO + CFO
5. Click **Finish**

### Step 2 — Configure site settings (5 min)

1. On the new site → ⚙ **Site information** → **View all site settings**
2. **Site permissions** → **Advanced permissions settings**:
   - Confirm 3 default SharePoint groups exist: Owners, Members, Visitors
   - Map them to the Entra security groups from the v5 plan (or keep as standalone)
3. **Regional settings** → Eastern Time
4. **Site features** → ensure **Document Sets** is enabled (we'll use for per-day census folders)

### Step 3 — Create document libraries (10 min)

For each of the 6 libraries in §3:

1. Site home → **+ New** → **Document library**
2. Name it (e.g. `Contracts`)
3. Go into the library → ⚙ → **Library settings** → **Permissions for this library**
4. **Stop inheriting permissions** → customize per §4
5. Add folders/subfolders per §3 structure

### Step 4 — Apply sensitivity labels (5 min, if you have E5 / Purview licensed)

1. Go to <https://compliance.microsoft.com> → **Information protection** → **Labels**
2. Create `HHA-Internal-Confidential` and `HHA-PHI-Restricted` if they don't exist
3. Apply via **Policies** → scope to this SharePoint site
4. On each library in the site: ⚙ → **Library settings** → **Default label** → pick

### Step 5 — Retention policy (5 min)

1. <https://compliance.microsoft.com> → **Data lifecycle management** → **Retention policies**
2. New policy → scope to the HHA Dashboard site
3. Add rule: `Daily Uploads/Census` folder → retain 7 days then delete
4. Add rule: rest of site → retain 7 years

### Step 6 — Seed initial content (5 min)

1. Upload from OneDrive → SharePoint:
   - `DASHBOARD_PLAN.md` → Planning
   - `Architecture.md` → Planning
   - `UI_MOCKUP_v5.html` → Planning
   - `VENTRA_REPLY_DRAFT.md` → Planning
   - `SHAREPOINT_PLAN.md` → Planning (this file)
2. Drop the `hha-dashboard/docs/adr/001-hipaa-data-classification.md` into `Planning/adr/`
3. Hospital contracts → `Contracts/Florida/` (as you gather them)
4. Microsoft BAA export from Service Trust portal → `Contracts/Vendor/`

### Step 7 — Add members (5 min)

Site → **Settings** ⚙ → **Site permissions** → **Invite people** → **Add members to group**:

- Crystal Anderson
- Sandy Collins
- Maribel Reyes
- Andrea Simon
- Dr. Pallavi Aneja
- Dr. Veena Reddy

### Step 8 — Post welcome message in the Teams channel

The M365 Group auto-creates a Teams channel. Post:

> 👋 Welcome to the HHA Dashboard project workspace. Planning docs are in **Planning**, contracts in **Contracts**, historical data in **Historical Data**. Drop census PDFs in **Daily Uploads / Census** (Crystal). Questions → me.
> — Akhil

---

## 8. Optional: automate provisioning via PowerShell

If you want to recreate the site in another environment (staging, test) or script the setup:

```powershell
# Install PnP.PowerShell once
Install-Module -Name PnP.PowerShell -Scope CurrentUser

# Authenticate as tenant admin
Connect-PnPOnline -Url "https://hhamedicine-admin.sharepoint.com" -Interactive

# Create the site
New-PnPSite -Type TeamSite `
    -Title "HHA Dashboard" `
    -Alias "hha-dashboard" `
    -Description "Operations Dashboard project workspace" `
    -IsPublic:$false

# Connect to the new site
Connect-PnPOnline -Url "https://hhamedicine.sharepoint.com/sites/hha-dashboard" -Interactive

# Create libraries
$libraries = @("Planning", "Contracts", "Historical Data", "Daily Uploads", "Vendor Communications", "Decisions")
foreach ($lib in $libraries) {
    New-PnPList -Title $lib -Template DocumentLibrary
}

# Create folders inside Contracts
Add-PnPFolder -Name "Florida" -Folder "Contracts"
Add-PnPFolder -Name "Texas" -Folder "Contracts"
Add-PnPFolder -Name "Vendor" -Folder "Contracts"

# Grant the dashboard app read-only (after app registration exists)
Grant-PnPAzureADAppSitePermission `
    -AppId "<dashboard-api-app-id>" `
    -DisplayName "HHA Dashboard API" `
    -Site "https://hhamedicine.sharepoint.com/sites/hha-dashboard" `
    -Permissions Read
```

Save this as `scripts/provision-sharepoint.ps1` in the repo for repeatability.

---

## 9. What's NOT in scope here (scope guards)

- **No public-facing SharePoint pages.** The dashboard app is the only public UI.
- **No wiki / intranet expansion.** Keep it focused on this project.
- **No PHI beyond the 7-day census drop zone.** Raw claim data from Ventra stays in Azure Blob with auto-shred — NOT SharePoint.
- **No SharePoint forms** for data entry (we have the dashboard app). SharePoint is files-only.
- **No external sharing.** Anyone outside hhamedicine.com shouldn't see any of this.

If SharePoint scope grows later (e.g., company-wide wiki), create a *separate* site. Keep this one narrow.

---

## 10. Cost

- **$0 incremental.** Included in your existing M365 licensing. No new subscription.
- Storage well under 1 GB — far below the 25 TB default quota.

---

## 11. Verification (after setup)

1. Sign in as a test member (not admin) — e.g., temporarily add Crystal's account
2. Try to navigate to `Contracts` → should get 403 (permission inheritance broken correctly)
3. Upload a file to `Daily Uploads/Census/2026-04-23/` → success
4. Wait 7 days, check that the retention policy deleted the file
5. As an external user (your personal Gmail) — try to open any file link → should get "Access Denied" (external sharing off)

---

## 12. Open items for Akhil

- [ ] Decide whether `owner_finance` (Sandy, Maribel) gets write access to `Contracts` or read-only
- [ ] Confirm E5/Purview licensing is active (for sensitivity labels)
- [ ] Decide who gets added to Owners group beyond CEO + CFO + Reddy (COO? CMO?)
- [ ] Scheduled date for the welcome-Teams-message + member onboarding

---

_Draft 2026-04-23. Action window: 30 min with admin access._
