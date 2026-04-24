# HHA Dashboard — Upload → Blob → Cron Pipeline (Plan)

> **Supersedes the Session 3 "in-memory only" approach and the SharePoint-first approach.**
> This is the active direction as of 2026-04-23. SHAREPOINT_PLAN.md + SHAREPOINT_DEEP_DIVE.md
> are kept as deferred alternatives (future phase, if/when the team wants a SharePoint file
> repository for contracts + historical Excel files).

---

## One-liner

**Owners sign in to the dashboard, drop files into a single "Drop Zone" page. Files go to Azure Blob Storage with metadata tags. A cron job (Azure Container Apps Job) runs every 15 minutes, picks up unprocessed files, routes each to the right extractor (Document Intelligence for PDFs, pandas for Excel), writes the aggregates to Postgres. The dashboard refreshes on every page load, so new numbers appear within 15 minutes of upload. Raw files auto-delete from Blob 7 days after processing.**

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        THE PIPELINE (end to end)                          │
└──────────────────────────────────────────────────────────────────────────┘

  STEP 1 — User uploads
  ┌─────────────────────────────┐
  │ Crystal / Sandy / Aneja /   │
  │ Andrea signs in,            │
  │ visits /uploads             │
  │                             │
  │ Drops a file:               │
  │  • census-2026-04-23.pdf    │
  │  • collections-2026-04.xlsx │
  │  • clinical-audit-W17.xlsx  │
  │                             │
  │ UI auto-classifies by       │
  │ filename; user can          │
  │ override via dropdown       │
  └────────────┬────────────────┘
               │ POST /api/v1/uploads (multipart)
               ▼
  STEP 2 — FastAPI accepts + stores to Blob
  ┌────────────────────────────────────────┐
  │ FastAPI                                │
  │                                        │
  │ 1. Verify user (Entra JWT or dev stub) │
  │ 2. Validate MIME + size limit (25 MB)  │
  │ 3. Compute SHA-256 of content          │
  │ 4. Generate blob path:                 │
  │    uploads/{type}/{date}/              │
  │      {upn}_{uuid}_{sha256}.{ext}       │
  │ 5. Upload to Blob with metadata:       │
  │    - type = census_pdf | finance_xlsx  │
  │           | clinical_xlsx | hr_xlsx    │
  │    - uploaded_by_upn                   │
  │    - original_filename                 │
  │    - status = uploaded                 │
  │    - sha256                            │
  │ 6. Insert row into uploads.upload_log  │
  │ 7. Return 201 { upload_id, blob_url }  │
  └──────────────┬─────────────────────────┘
                 │ Managed Identity (prod)
                 │ / connection string (dev)
                 ▼
  STEP 3 — Azure Blob Storage
  ┌────────────────────────────────────────┐
  │ Container: `uploads`                   │
  │                                        │
  │ Folder structure:                      │
  │  uploads/                              │
  │  ├── census_pdf/                       │
  │  │   └── 2026-04-23/                   │
  │  │       └── crystal_abc123_..pdf      │
  │  ├── finance_xlsx/                     │
  │  ├── clinical_xlsx/                    │
  │  └── hr_xlsx/                          │
  │                                        │
  │ Lifecycle policy: delete 7 days after  │
  │ blob-tag `status=processed` is set.    │
  │                                        │
  │ Access: Managed Identity only (prod).  │
  │ Private endpoint, no public traffic.   │
  └──────────────▲─────────────────────────┘
                 │
                 │ Every 15 min via cron
                 │
  STEP 4 — Cron job picks up unprocessed files
  ┌────────────────────────────────────────┐
  │ Azure Container Apps Job               │
  │ Name: `upload-ingest`                  │
  │ Schedule: */15 * * * *                 │
  │                                        │
  │ For each blob with tag                 │
  │   status=uploaded:                     │
  │                                        │
  │   type = blob.metadata['type']         │
  │   pdf  = blob.download()  (bytes)      │
  │                                        │
  │   ROUTE BY TYPE:                       │
  │   ├── census_pdf   → extract_census()  │
  │   ├── finance_xlsx → extract_finance() │
  │   ├── clinical_xlsx→ extract_clinical()│
  │   └── hr_xlsx      → extract_hr()      │
  │                                        │
  │   Each extractor returns structured    │
  │   aggregates (site → count, state →    │
  │   collections, etc.)                   │
  │                                        │
  │   Save to entries.* / facts.* tables   │
  │   with the audit_log event listener    │
  │   firing automatically.                │
  │                                        │
  │   Update blob tags:                    │
  │     status = processed                 │
  │     processed_at = <ts>                │
  │     rows_written = N                   │
  │   (lifecycle policy deletes 7d later)  │
  │                                        │
  │   On extraction error:                 │
  │     status = error                     │
  │     error = <message>                  │
  │     retry_count += 1                   │
  │   (after 3 failures, alert + manual    │
  │   review; stops retrying)              │
  └──────────────┬─────────────────────────┘
                 │
                 ▼
  STEP 5 — Postgres updated
  ┌────────────────────────────────────────┐
  │ entries.daily_entries                  │
  │  · census rows upserted (unique by     │
  │    site_id, entry_date)                │
  │                                        │
  │ entries.monthly_finance_manual         │
  │  · collections / AR rows upserted      │
  │                                        │
  │ entries.weekly_clinical                │
  │  · H&P/DC/LOS rows                     │
  │                                        │
  │ audit.audit_log                        │
  │  · one row per mutation, upn included  │
  └──────────────┬─────────────────────────┘
                 │
                 ▼
  STEP 6 — Dashboard reflects new numbers on next page load
  ┌────────────────────────────────────────┐
  │ Next.js pages use cache:"no-store"     │
  │ (already set in api-client.ts)         │
  │                                        │
  │ Overview / Operations / Finance /      │
  │ Clinical / People / Scorecards all     │
  │ re-fetch their endpoints on every      │
  │ render. Max staleness = 15 min from    │
  │ upload → dashboard appearance.         │
  └────────────────────────────────────────┘
```

---

## HIPAA posture (still ADR-001 compliant)

1. **All services are BAA-covered**: Azure Blob, Container Apps Jobs, Document Intelligence, Postgres — all default-covered by Microsoft's BAA via HHA's M365 tenant.
2. **Managed Identity** auth for Blob from both FastAPI (upload) and the cron job (download). No shared access keys in prod.
3. **Private endpoints**: Blob storage has no public network access; VNet-integrated from the app + job.
4. **Retention**: blob lifecycle deletes files 7 days after `status=processed` tag is set. Policy-enforced, not app-enforced — even a buggy app can't prevent deletion.
5. **Aggregate-only in Postgres**: the extractor reads patient-level fields (names, MRNs in census PDFs) **only in-memory during extraction** and discards them. Only Tier A / Tier B aggregates ever land in our DB. ADR-001's forbidden column list is enforced by the CI schema test.
6. **Audit trail**: every blob upload gets an `uploads.upload_log` row; every DB mutation by the cron gets an `audit.audit_log` row. Both include UPN + SHA-256 of the source file.
7. **Sensitivity label** (Purview, later): when admin provisions prod, apply `HHA-PHI-Restricted` label to the `uploads` container → auto-encrypts at rest with tenant-managed keys, blocks download-to-personal-OneDrive.

---

## Data model additions

Extends the entries / audit / (new) uploads schemas introduced in Session 3.

### New schema: `uploads`

Purpose: the log of what was uploaded, by whom, when, and whether the cron processed it successfully. Separate from `audit.audit_log` because it tracks file-upload events (which aren't DB mutations) and because it's the cron job's work queue.

```sql
CREATE SCHEMA IF NOT EXISTS uploads;

uploads.upload_log (
    id                     bigserial PRIMARY KEY,
    uploaded_by_upn        text NOT NULL,       -- B
    uploaded_at            timestamptz NOT NULL DEFAULT now(),
    file_type              text NOT NULL,       -- A   (census_pdf|finance_xlsx|clinical_xlsx|hr_xlsx)
    original_filename      text NOT NULL,       -- A   (never contains PHI)
    blob_name              text NOT NULL,       -- A   (e.g. census_pdf/2026-04-23/crystal_abc123_xyz.pdf)
    size_bytes             bigint NOT NULL,     -- A
    sha256                 text NOT NULL,       -- A
    status                 text NOT NULL        -- A   (uploaded | processed | error | expired)
                           DEFAULT 'uploaded',
    processing_started_at  timestamptz,         -- A
    processing_finished_at timestamptz,         -- A
    rows_written           integer,             -- A   (per-extractor: how many rows it wrote to entries/facts)
    error_message          text,                -- A
    retry_count            integer DEFAULT 0,   -- A
    -- No PHI, no patient identifiers, no file bytes
    CONSTRAINT ck_status CHECK (status IN ('uploaded', 'processing', 'processed', 'error', 'expired'))
);

CREATE INDEX ix_upload_log_status_uploaded_at ON uploads.upload_log (status, uploaded_at);
CREATE INDEX ix_upload_log_upn ON uploads.upload_log (uploaded_by_upn);
```

`upload_log` is the job's queue. It queries `WHERE status = 'uploaded' AND retry_count < 3` to find work.

Every column is Tier A (aggregate/metadata) or Tier B (UPN). No PHI. CI guard passes.

---

## Upload UI (`/uploads` page)

Role: any authenticated role that's an owner_* or admin.

### Layout

```
┌───────────────────────────────────────────────────────────────┐
│  Upload Files                                                  │
│  Drop anything. Census PDFs, monthly finance Excel, clinical  │
│  audit spreadsheets, HR exports. We route by filename.        │
├───────────────────────────────────────────────────────────────┤
│                                                                │
│     ┌─────────────────────────────────────────────────┐       │
│     │                                                 │       │
│     │    📄  Drop files here or click to browse       │       │
│     │                                                 │       │
│     │    PDFs, Excel (.xlsx), CSV                     │       │
│     │    Max 25 MB per file · up to 10 at once        │       │
│     │                                                 │       │
│     └─────────────────────────────────────────────────┘       │
│                                                                │
│  Staged files (not yet uploaded):                              │
│  ┌──────────────────────────────────────────────────────┐     │
│  │ census-2026-04-23.pdf    [census_pdf ▼]  1.2 MB   ✕ │     │
│  │ collections-march.xlsx   [finance_xlsx ▼] 420 KB  ✕ │     │
│  └──────────────────────────────────────────────────────┘     │
│                                  [ Upload 2 files ]            │
│                                                                │
├───────────────────────────────────────────────────────────────┤
│  Recent uploads (last 24h)                                     │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ File                   Type        Status      When     │  │
│  │ census-2026-04-23.pdf  census_pdf  ✓ processed  2 min   │  │
│  │                                    7 rows written       │  │
│  │ collections-mar.xlsx   finance_xlsx ⏳ uploaded  5 min   │  │
│  │                                    queued for cron      │  │
│  │ clinical-W17.xlsx      clinical_xlsx ✗ error    1 hr    │  │
│  │                                    retry 2/3            │  │
│  └─────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

### Filename → type heuristic (runs client-side on drop)

```ts
function inferType(filename: string): FileType | null {
  const name = filename.toLowerCase();
  if (/\bcensus\b.*\.pdf$/.test(name)) return "census_pdf";
  if (/\b(collection|finance|revenue|ar[-_])/i.test(name) && /\.xlsx$/.test(name)) return "finance_xlsx";
  if (/\b(clinical|audit|chart[-_])/i.test(name) && /\.(xlsx|csv)$/.test(name)) return "clinical_xlsx";
  if (/\b(hr|headcount|turnover|roster)/i.test(name) && /\.(xlsx|csv)$/.test(name)) return "hr_xlsx";
  return null; // user must pick from dropdown
}
```

If inference returns `null`, the UI shows the dropdown as "— Pick type —" and disables the Upload button for that row until the user selects.

### Poll for status

Client polls `GET /api/v1/uploads?since=<last-seen-id>` every 30s while on the page, updating the "Recent uploads" table. No WebSocket needed for this cadence.

---

## Cron job: `upload-ingest`

### Runtime

- **Azure Container Apps Job** (cron type), schedule `*/15 * * * *`
- Docker image: `jobs/upload-ingest` (same monorepo)
- Managed Identity has `Storage Blob Data Contributor` on the `uploads` container and DB connect permission
- Exits with code 0 (success) or non-zero (Azure Monitor alert fires)

### Pseudocode

```python
async def main():
    engine = create_async_engine(settings.database_url)
    blob_client = BlobServiceClient(account_url=SA_URL, credential=DefaultAzureCredential())
    uploads = blob_client.get_container_client("uploads")

    async with AsyncSession(engine) as db:
        # Claim work: SELECT ... FOR UPDATE SKIP LOCKED
        stmt = (
            select(UploadLog)
            .where(UploadLog.status == "uploaded", UploadLog.retry_count < 3)
            .order_by(UploadLog.uploaded_at)
            .limit(50)
            .with_for_update(skip_locked=True)
        )
        work = (await db.execute(stmt)).scalars().all()
        if not work:
            log.info("upload-ingest.no-work")
            return

        for row in work:
            row.status = "processing"
            row.processing_started_at = datetime.now(timezone.utc)
        await db.commit()

        for row in work:
            try:
                blob = uploads.get_blob_client(row.blob_name)
                data = blob.download_blob().readall()
                # verify sha256 matches
                assert hashlib.sha256(data).hexdigest() == row.sha256

                # ROUTE
                extractor = ROUTES[row.file_type]
                aggregates = await extractor(data, row, db)

                # MARK processed
                await blob.set_blob_tags({"status": "processed",
                                          "processed_at": now_iso(),
                                          "rows_written": str(aggregates.rows_written)})
                row.status = "processed"
                row.processing_finished_at = datetime.now(timezone.utc)
                row.rows_written = aggregates.rows_written
                await db.commit()
                log.info("upload-ingest.ok", blob=row.blob_name, rows=aggregates.rows_written)

            except Exception as e:
                log.exception("upload-ingest.fail", blob=row.blob_name)
                row.retry_count += 1
                row.error_message = str(e)[:500]
                row.status = "error" if row.retry_count >= 3 else "uploaded"  # requeue
                await db.commit()


ROUTES = {
    "census_pdf":    extract_census_pdf,
    "finance_xlsx":  extract_finance_xlsx,   # stub in Session 3
    "clinical_xlsx": extract_clinical_xlsx,  # stub
    "hr_xlsx":       extract_hr_xlsx,        # stub
}
```

### Extractor contract

Each extractor is `async def extract_*(data: bytes, upload_row, db) -> ExtractionResult`. It:

1. Parses the bytes (Document Intelligence for PDFs, pandas for Excel, stdlib csv for CSV)
2. Produces structured aggregates (no patient identifiers)
3. Upserts into the appropriate `entries.*` / `facts.*` tables
4. Returns `ExtractionResult(rows_written: int, warnings: list[str])`
5. Never logs the raw data; any row-level context that needs logging is sanitized first

### Session 3 scope: only `extract_census_pdf` is real

Other extractors are stubs that log "not yet implemented" and mark status=`error` with an instructional message. Session 4+ implements finance, clinical, HR extractors one at a time. Users can still upload those file types now; they just queue until the extractor is ready.

---

## Local dev changes

### docker-compose.yml — add Azurite (Azure Blob emulator)

```yaml
azurite:
  image: mcr.microsoft.com/azure-storage/azurite:latest
  container_name: hha-azurite
  restart: unless-stopped
  command: "azurite-blob --blobHost 0.0.0.0 --blobPort 10000 --skipApiVersionCheck --loose"
  ports:
    - "10000:10000"  # Blob
  volumes:
    - azurite_data:/data
```

One container. Emulates Blob locally so no Azure account needed for dev.

### `.env.example` additions

```
# Local dev via Azurite (override in prod via Managed Identity)
AZURE_STORAGE_ACCOUNT_URL=http://localhost:10000/devstoreaccount1
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://localhost:10000/devstoreaccount1;
AZURE_STORAGE_UPLOADS_CONTAINER=uploads

# Azure Document Intelligence (unchanged from Session 3 plan)
AZURE_DOC_INTELLIGENCE_ENDPOINT=https://<your-di-resource>.cognitiveservices.azure.com/
AZURE_DOC_INTELLIGENCE_API_KEY=
```

### Run the cron job locally

```bash
# One-off invocation (dev)
cd api && uv run python -m jobs.upload_ingest.main

# Simulate cron every 15 min (dev)
watch -n 900 "cd api && uv run python -m jobs.upload_ingest.main"
```

---

## What gets built (file-by-file)

### Backend (api/)

- **`app/models/entries.py`** — already has `DailyEntry` from Session 3 start. Keep.
- **`app/models/audit.py`** — already has `AuditLog`. Keep.
- **`app/models/uploads.py`** — new: `UploadLog` model (see schema above)
- **`app/services/audit.py`** — SQLAlchemy `after_flush` event listener (carried from Session 3)
- **`app/services/blob.py`** — Azure Blob client factory + upload + tag + download helpers
- **`app/services/pdf_extract.py`** — census PDF extractor (Document Intelligence)
- **`app/schemas/uploads.py`** — `UploadOut`, `UploadStageIn`, `FileType` enum
- **`app/routers/uploads.py`** — `POST /api/v1/uploads` (multipart), `GET /api/v1/uploads` (list recent, `?since=<id>`)
- **`app/routers/entries.py`** — (unchanged from Session 3 scope — still exists for manual-type fallback)
- **`alembic/versions/0002_entries_audit_uploads.py`** — combined migration creating entries.daily_entries, audit.audit_log, uploads.upload_log
- **Tests**:
  - `tests/test_audit.py` — event listener writes expected rows
  - `tests/test_uploads_router.py` — POST accepts file, stores to (mocked) Blob, writes upload_log row; role gating works
  - `tests/test_job_upload_ingest.py` — mock Blob + DI; given a seeded upload_log row + fixture blob, job runs extract_census, writes daily_entries, flips status to processed
  - `tests/test_schema_classification.py` — extended to cover new columns

### Cron job (jobs/)

- **`jobs/upload_ingest/Dockerfile`** — Python 3.12 slim + uv install + entrypoint
- **`jobs/upload_ingest/main.py`** — the main() function above
- **`jobs/upload_ingest/extractors/__init__.py`** — ROUTES dict
- **`jobs/upload_ingest/extractors/census_pdf.py`** — real implementation (Session 3)
- **`jobs/upload_ingest/extractors/finance_xlsx.py`** — stub returning `NotImplementedError` (Session 4+)
- **`jobs/upload_ingest/extractors/clinical_xlsx.py`** — stub
- **`jobs/upload_ingest/extractors/hr_xlsx.py`** — stub
- **`jobs/upload_ingest/tests/`** — unit tests for each extractor

### Frontend (web/)

- **`app/(entry)/uploads/page.tsx`** — server component, role-gated, fetches recent uploads
- **`app/(entry)/uploads/UploadDropZone.tsx`** — client: drag-drop, filename-infer, staging, bulk upload, progress, polling
- **`components/FileDrop.tsx`** — already planned in Session 3; keep
- **`components/Toast.tsx`** — already planned; keep
- **`lib/api-client.ts`** — add `api.stageUpload(file, type)`, `api.listUploads(sinceId?)`
- **`components/TopNav.tsx`** — add "Upload Files" link (visible to any owner_* or admin)

### Infra (infra/)

- Bicep module additions (Session 7, not this session):
  - Storage account + `uploads` container with lifecycle policy (delete 7d after tag `status=processed`)
  - Container Apps Job `upload-ingest` with cron schedule `*/15 * * * *`
  - Managed Identity role assignments

For Session 3 we do **local-only** via Azurite + run-the-job-manually. Bicep provisioning lands in Session 7.

### Config

- **docker-compose.yml** — add Azurite service
- **`.env.example`** — add Blob + container config
- **`api/pyproject.toml`** — add `azure-storage-blob`, `python-multipart`, `pandas`, `openpyxl` (for Excel stubs), `azure-ai-documentintelligence`

---

## Defer list (explicit — not in this session)

- Finance / clinical / HR extractors (Session 4+; stubs only)
- Real Entra auth (Session 6; dev-stub `Authorization: Dev owner_ops` continues)
- Bicep infra for the job + Storage account + lifecycle policy (Session 7)
- Production Managed Identity wiring (Session 7)
- Upload resume / chunked upload (files <25 MB always fit in one POST)
- Malware scan on uploaded files (add later: Microsoft Defender for Storage scans Blob automatically when enabled at the storage-account level — $0.30/GB)
- Retention enforcement via Purview label (Session 8 polish)

---

## Verification (end-of-session gate)

1. `docker compose up -d` — Postgres + Mailpit + Adminer + **Azurite** running
2. `cd api && uv sync && uv run alembic upgrade head` — creates 3 new tables
3. `uv run pytest -v` — all tests pass including:
   - HIPAA schema classification (no Tier C columns)
   - Audit listener fires on mutation
   - Upload endpoint accepts PDF, stores to Azurite, writes upload_log row
   - Cron job claims work, extracts census, writes daily_entries, marks processed
4. `uv run uvicorn app.main:app --reload`
5. `cd web && npm run dev`
6. **End-to-end manual test:**
   - Open `http://localhost:3000/uploads` as owner_ops
   - Drag a sample `census-2026-04-23.pdf` → UI detects type as `census_pdf` → click Upload
   - Immediately: file appears in "Recent uploads" with status = ⏳ uploaded
   - Run cron manually: `uv run python -m jobs.upload_ingest.main`
   - Page auto-polls → status flips to ✓ processed, "7 rows written"
   - Navigate to `http://localhost:3000/operations` → today's census numbers reflect the PDF
   - In Adminer (`localhost:8080`): `SELECT * FROM audit.audit_log ORDER BY changed_at DESC` → 7 rows from the upsert
   - In Azurite (via Azure Storage Explorer or `az storage blob list --account-name devstoreaccount1`): blob has metadata `status=processed`

---

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Azurite behaves differently from real Azure Blob on tags / lifecycle | Integration test also runs against a dev Azure Storage account in CI; smoke test after Bicep provisions real resources |
| Two cron invocations race on the same file | `FOR UPDATE SKIP LOCKED` on upload_log row claim prevents double-processing |
| Malformed upload size bypasses check | FastAPI + nginx (App Service default) enforce 25 MB at two layers |
| User uploads a malicious PDF | Microsoft Defender for Storage (enable at storage-account level, $0.30/GB scanned) flags malware before job reads |
| Fuzzy site-name match misclassifies Westside → Woodmont | Extraction service returns `CensusExtractionResult` with per-row confidence; UI for manual entry is always the fallback |
| PHI accidentally logged during extraction error | `structlog` processor strips known PHI-adjacent field names; extractor `except` logs only exception class + blob SHA-256 |
| Blob lifecycle policy fails to delete | Weekly Azure Monitor query: `blob_count WHERE status=processed AND processed_at < now() - 10d` should be 0 |

---

## Why this beats SharePoint for Session 3

- **Users never leave the dashboard** — upload happens on the same site they're logged into. No context switch to SharePoint Online.
- **One auth system** — Entra ID for dashboard = Entra ID for upload. SharePoint adds another permission model (site groups, library-level ACLs) that needs separate admin effort.
- **Cleaner HIPAA story** — Blob has simpler RBAC via Managed Identity. SharePoint's `Sites.Selected` pattern works but adds 3 Graph API calls per file read.
- **Structured metadata** — Blob tags are searchable + policy-evaluable. SharePoint custom columns are possible but more limited.
- **Extraction parallelism** — Blob Events + Azure Functions or just bigger cron batches scale horizontally. SharePoint file-change webhooks are fine but rate-limited.
- **No Graph API latency** — SharePoint lookups go through Graph (~200ms p50). Blob is direct from the VNet (<20ms).

SharePoint still wins for:

- Contracts library (users browse + download)
- Historical Excel archive (read-only)
- Vendor BAA + MSA PDFs

Those stay in the (deferred) SharePoint plan for later. This session is focused on the **data ingestion pipeline**.

---

## Status of superseded docs

- `SHAREPOINT_PLAN.md` — **DEFERRED**. Marked at top of file. Still valid for the read-only artifacts (contracts, Excel archives, BAA library) in a future phase.
- `SHAREPOINT_DEEP_DIVE.md` — **DEFERRED**. Same.
- Previous approved Session 3 plan (in `.claude/plans/so-now-we-are-nested-grove.md`) — superseded by this doc. The in-memory-only approach is reverted; files now go through Blob.
- `docs.html` + `index.html` — current, index.html shows the SharePoint docs but they're labeled DEFERRED.

---

_Draft 2026-04-23. Owner: Akhil. Resume Session 3 implementation from this plan._
