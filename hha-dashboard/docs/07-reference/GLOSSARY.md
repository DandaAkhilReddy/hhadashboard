# Glossary

> **Plain-English definitions** for every term used across HHA Dashboard docs. Domain-specific (healthcare RCM, Azure, HIPAA, HHA-internal) terms first, then technical (engineering).
>
> If you encounter a term not here, file an issue (or just add it — every PR can update this file).
>
> Last updated 2026-05-11.

## Healthcare / RCM terms

| Term | Plain-English meaning |
|---|---|
| **Adjustment, contractual** | Money written off a charge because of a contract with the payer (e.g., insurance only pays 70% of the billed rate — the other 30% is a contractual adjustment) |
| **A/R** (Accounts Receivable) | Money owed to HHA that hasn't been collected yet |
| **A/R aging bucket** | How long money has been owed — 0-30 days, 31-60, 61-90, 91-120, 120+ days. Older buckets are riskier to collect |
| **Athena, Athenahealth** | The practice management system (PM) underlying Ventra's billing service. We don't talk to Athena directly; we go through Ventra |
| **Attribution rule** | Which physician gets credit for an encounter when multiple physicians touched the patient. Common options: rendering provider, supervising provider, attending physician |
| **BAA** (Business Associate Agreement) | Legal contract under HIPAA that lets a vendor handle PHI on HHA's behalf |
| **Bad-debt write-off** | Money written off because the patient never paid and we've given up collecting |
| **Census** | Number of patients currently admitted to a hospital site |
| **Charge** | A billable item — e.g., "30 minutes of hospitalist time = $200 billed" |
| **Claim** | A bill sent to a payer (insurance company) for a service rendered |
| **CMS** (Centers for Medicare & Medicaid Services) | US federal agency. Sets rules for Medicare/Medicaid billing |
| **Collection rate** | Cash collected divided by net revenue. > 95% is healthy |
| **CPT code** | Procedure code used in billing (e.g., 99221 = "initial hospital care"). HHA explicitly does NOT persist per-line CPT codes (LDS-tier data) |
| **Days in A/R** | How long, on average, money sits in A/R before being collected. < 50 days is healthy |
| **DC** (Discharge) | When a patient leaves the hospital |
| **Encounter** | A specific interaction between a physician and a patient (a visit, a consultation) |
| **FMV** (Fair Market Value) | The "going rate" for a physician's compensation. Below-FMV comp can violate Stark/AKS laws |
| **FTE** (Full-Time Equivalent) | Workforce measure — 1.0 = full-time, 0.5 = half-time |
| **Gross charges** | Total dollar amount billed, before any adjustments |
| **Guarantor** | The person legally responsible for paying a patient's bill (usually the patient themselves; sometimes a parent or spouse) |
| **H&P** (History & Physical) | A clinical note documenting the patient's medical history and exam. HHA tracks "H&P within 24h of admission" as a quality metric |
| **HCAHPS** | Patient satisfaction survey (out of scope for HHA Dashboard) |
| **HIPAA** | The 1996 US federal health-privacy law. Defines PHI and what vendors must do to protect it |
| **HL7 / FHIR** | Healthcare data interchange standards. Out of scope for HHA Dashboard (Phase 4+) |
| **Hospitalist** | A physician specialized in caring for hospital inpatients |
| **ICD-10** | Diagnosis code (e.g., I10 = essential hypertension). HHA explicitly does NOT persist per-line ICD codes (LDS-tier data) |
| **LDS** (Limited Data Set) | A category of patient data with most identifiers stripped but with some dates and ZIP-code data remaining. Still HIPAA-restricted; requires a Data Use Agreement. HHA never persists LDS data |
| **LOS** (Length of Stay) | How many days a patient was in the hospital |
| **MGMA** | Medical Group Management Association. Publishes benchmark data on physician productivity (used for FMV bands) |
| **Modifier** | Two-character suffix on a CPT code that qualifies it. Per-line modifiers are LDS-tier; HHA doesn't persist |
| **MRN** (Medical Record Number) | Hospital's internal patient identifier. PHI; HHA never persists |
| **Net collection rate** (NCR) | Payments / net revenue. > 95% is healthy |
| **Net revenue** | Charges minus all adjustments and write-offs. The "real" revenue number |
| **NPI** (National Provider Identifier) | A 10-digit number identifying a US healthcare provider (physician or facility). Public information, NOT PHI |
| **Payer** | The entity paying the bill — usually an insurance company, sometimes Medicare/Medicaid, sometimes the patient |
| **Payer class** | Category of payer — `commercial`, `medicare`, `medicaid`, `selfpay`, `other`. HHA uses this 5-bucket taxonomy |
| **PHI** (Protected Health Information) | Patient data identifiable to a specific person + linked to a health condition. HIPAA's most-protected category. HHA never persists PHI |
| **PII** (Personally Identifiable Information) | Broader term than PHI; any data identifying a person. PHI is a subset |
| **PM** (Practice Management) | Software that handles billing, scheduling, and operational workflow for a healthcare practice (Athena is HHA's PM via Ventra) |
| **Posting date** | The date a payment or adjustment is recorded in the billing system (different from the date of service) |
| **Provider** | Physician or midlevel (NP/PA) — anyone who can bill for clinical services |
| **Rank** (Doctor Scorecards) | Composite quartile score for a physician's productivity + quality vs peer band. HHA uses quartiles, not absolute ranks, to avoid politics |
| **RCM** (Revenue Cycle Management) | The end-to-end billing workflow — charge entry, claim submission, payment posting, denials. Ventra owns this for HHA's Florida book |
| **Rendering provider** | The physician who actually performed the service |
| **Revenue per FTE** | Net revenue attributed to a physician divided by their FTE |
| **RVU** (Relative Value Unit) | Standardized productivity measure. 1 RVU = a standardized unit of physician work |
| **Self-pay** | A patient paying out-of-pocket (no insurance) |
| **Stark / AKS** | US federal laws restricting physician self-referrals and kickbacks. Compensation arrangements with physicians must be at FMV |
| **Subscriber** | The person whose name is on an insurance policy (sometimes the patient, sometimes a spouse/parent). Identifiers are PHI; HHA never persists |
| **Supervising provider** | Senior physician who oversees a midlevel's work. Sometimes used for attribution instead of the rendering provider |
| **Takeback** (or recoupment) | When a payer demands HHA return money paid for a claim (e.g., they decide the service wasn't covered after all) |
| **Ventra** | HHA's RCM partner. Handles billing for HHA's Florida hospitals only |
| **WORM** (Write-Once-Read-Many) | Storage mode where data, once written, cannot be modified or deleted for a fixed retention period. Used for HIPAA-compliant backups |
| **Work RVU** | Subset of RVU representing the physician's work effort (excludes practice expense and malpractice) |
| **Write-off** | Money formally removed from A/R as uncollectable |
| **835** | EDI file format payers send to providers with payment + adjustment detail (per claim) |
| **837** | EDI file format providers send to payers (the actual claim). Not used in our data flow |

## Azure / cloud terms

| Term | Plain-English meaning |
|---|---|
| **App Service** | Azure's platform for hosting web applications (we use it for both `app-hha-web-prod` and `app-hha-api-prod`) |
| **App Service Plan** | The underlying compute tier that an App Service runs on. We use B1 (Basic) |
| **Application Insights** | Azure's APM (application performance monitoring) tool. Captures traces, metrics, exceptions |
| **Bicep** | Microsoft's domain-specific language for declaring Azure infrastructure (alternative to Terraform). HHA's infra is all Bicep |
| **Blob Storage** | Azure's object storage (like AWS S3). Used for backups and (Phase 2) Ventra raw drops |
| **Container Apps** | Azure's managed container platform (cheaper than AKS, friendlier than Functions for stateful jobs) |
| **Container Apps Job** | A scheduled or event-driven container that runs to completion (vs Container Apps Service which runs continuously) |
| **Container Registry** (ACR) | Azure's hosted Docker registry. Stores container images we deploy |
| **Entra ID** | Microsoft's identity service (formerly Azure AD). Source of truth for all HHA Dashboard user identity |
| **Event Grid** | Azure's event routing service. Used to trigger our ingestion job when a manifest file lands |
| **GP / General Purpose tier** | Higher-tier Postgres pricing — supports zone redundancy, more compute. Currently NOT used (we're on Burstable B1ms to save money) |
| **Key Vault** | Azure's secret management service. Stores connection strings, API keys |
| **Log Analytics** | Azure's log aggregation backend. Application Insights writes to a Log Analytics workspace |
| **Managed Identity** | An automatically-managed Azure AD identity assigned to a resource. Lets the resource authenticate to other Azure resources without static credentials |
| **OIDC** (OpenID Connect federated identity) | A way GitHub Actions can authenticate to Azure without storing a secret — Azure trusts GitHub's token issuer |
| **PaaS** (Platform-as-a-Service) | Managed-cloud model where Azure handles the OS, patches, scaling. App Service and Postgres Flex are PaaS |
| **PITR** (Point-in-time Restore) | Restoring a database to a specific timestamp. Postgres Flex supports this natively |
| **Postgres Flexible Server** | Azure's managed Postgres offering. We use the Burstable B1ms tier |
| **Private Endpoint** | A network construct that gives an Azure service a private IP inside your VNet. Currently not used (cost-tuned) |
| **Resource Group** | A logical container for related Azure resources. HHA's prod resources are in `rg-hha-dashboard-prod` |
| **SCM** (deployment-side container) | The "Kudu" container that handles deployment, environment vars, log streaming for App Services |
| **SFTP** | Secure File Transfer Protocol. Azure Blob can be SFTP-enabled for partner data delivery (Ventra) |
| **VNet** (Virtual Network) | Azure's network construct for isolating resources. Currently disabled in HHA's deploy to save cost |
| **WORM** (Write-Once-Read-Many) | Storage immutability policy. Once set, blobs can't be modified or deleted for the retention period |
| **Zone redundancy** | Azure feature where a resource is replicated across multiple availability zones in a region. Currently disabled (cost-tuned) |

## Project-specific terms

| Term | Plain-English meaning |
|---|---|
| **Akhil** | Akhil Reddy, IT Director, sole engineer on HHA Dashboard |
| **`audit.upn` GUC** | Postgres session variable holding the user's email. Set per-request by the API; read by the audit trigger to attribute the change |
| **comp_viewer** | Entra security group that grants ADDITIONAL visibility to `masters.comp_agreements` and the Below-FMV tile on People board. Orthogonal to `exec` role |
| **data_class** | Column-level HIPAA classification tag (A/B/C/D). Stored in SQLAlchemy `info={}` dict. CI test enforces |
| **Decision tracker** | Section at the top of [VENTRA_QUESTIONS.md](VENTRA_QUESTIONS.md) where action items get checked off during the vendor meeting |
| **Exec gate** | Per ADR-005, a phase-boundary review that requires both co-sponsors (CEO + CFO) to sign off |
| **HIPAA firewall** | The strip + aggregate pattern in `jobs/ventra_ingest/parse/option_b.py` that prevents PHI from entering Postgres |
| **kiosk credential** | The shared portal password for census entry. One credential, all site leaders, used on shared workstations |
| **OneDrive sync** | A common Windows + JavaScript dev environment issue. Files locked while OneDrive uploads. Workaround: pause sync or move repo out of OneDrive |
| **`source_system`** | Column tag indicating where a row came from — `VENTRA_FL_ATHENA` or `HHA_TX_MANUAL` or `PAYCOM` etc. FL and TX rows never mix in the same row |
| **Tile** | A single metric display on a board (e.g., "Today's census") |

## Technical / general engineering terms

| Term | Plain-English meaning |
|---|---|
| **ADR** (Architecture Decision Record) | A short, locked, dated document capturing a single architectural decision and its rationale. HHA has 5 ADRs in `docs/adr/` |
| **Alembic** | Python migration framework for SQLAlchemy. HHA tracks Postgres schema changes here |
| **Allowlist** | A closed set of permitted values. Safer than denylist for security boundaries (because new unknown items are excluded by default) |
| **API contract** | The shape of an API endpoint (method, path, request body, response body). Documented in OpenAPI and [API_ENDPOINT_CATALOG.md](API_ENDPOINT_CATALOG.md) |
| **asyncpg** | Async Postgres driver for Python (used by SQLAlchemy async). Uses `?ssl=require` URL syntax |
| **psycopg** | Sync Postgres driver. Used by Alembic. Uses `?sslmode=require` URL syntax. **NOT interchangeable with asyncpg's URL format** |
| **C4 model** | A 4-level diagramming convention for software architecture (Context, Container, Component, Code). HHA uses levels 1 + 2 |
| **CI** (Continuous Integration) | Automated tests + builds on every PR. HHA uses GitHub Actions |
| **CRLF / LF** | Different line endings. Windows uses CRLF (`\r\n`), Linux/macOS use LF (`\n`). Mixing them causes git noise |
| **Cursor pagination** | Stable list pagination using a cursor (opaque token) instead of offset/limit. Avoids drift if rows are inserted during iteration |
| **Defense in depth** | Multiple independent layers of protection (allowlist + assert + CI test + audit log). Any single failure doesn't expose the system |
| **GUC** (Grand Unified Configuration) | Postgres's term for a session/transaction-scoped variable. Used by HHA's audit trigger to capture identity |
| **Idempotent** | An operation that can be repeated safely with the same result. HHA's ingestion job is idempotent via UPSERT on natural key |
| **Manifest pattern** | Writing a final summary file after all data files to signal "drop complete." HHA's Ventra ingest triggers on `_MANIFEST.csv` only |
| **MSAL** (Microsoft Authentication Library) | Client-side library for Entra ID sign-in. Used in HHA's Next.js web app |
| **OIDC** | See "OpenID Connect" / "OIDC federated identity" above |
| **OpenAPI** | A specification for describing REST APIs. FastAPI auto-generates one at `/openapi.json` |
| **PaaS** | See Azure section |
| **Polars** | A fast DataFrame library for Python (alternative to pandas). HHA uses it for Ventra CSV parsing |
| **Pre-commit hook** | Git hook that runs before every commit. HHA's hook blocks forbidden column names |
| **Quarantine** | A separate storage bucket where bad/unprocessable files go for manual review |
| **RBAC** (Role-Based Access Control) | Authorization model where permissions are tied to roles, not individual users |
| **Runbook** | Operational guide for known scenarios (e.g., "what to do when X happens"). HHA's is at [RUNBOOK.md](RUNBOOK.md) |
| **SAS** (Shared Access Signature) | A temporary, scoped URL granting access to Azure Storage. Not currently used by HHA (Managed Identity preferred) |
| **Session GUC** | See "GUC" above. Postgres session variable, lifetime = connection |
| **Smoke test** | A quick end-to-end test to confirm a deploy is alive (vs full integration tests). HHA's is `scripts/smoke_deploy.sh` |
| **UPSERT** | INSERT-or-UPDATE on conflict. Postgres syntax: `INSERT ... ON CONFLICT (...) DO UPDATE SET ...` |
| **`uv`** | Fast Python package manager. HHA uses it instead of pip/poetry |
| **WSL** (Windows Subsystem for Linux) | Linux env on Windows. Akhil's dev environment uses it but with quirks calling Windows `az.cmd` |

## Acronym quick reference

| Acronym | Stands for |
|---|---|
| ACS | Azure Communication Services (email) |
| ADR | Architecture Decision Record |
| API | Application Programming Interface |
| AR | Accounts Receivable |
| BAA | Business Associate Agreement |
| CI | Continuous Integration |
| CMS | Centers for Medicare & Medicaid Services |
| CPT | Current Procedural Terminology (procedure codes) |
| EDI | Electronic Data Interchange |
| FMV | Fair Market Value |
| FTE | Full-Time Equivalent |
| GUC | Grand Unified Configuration (Postgres session vars) |
| H&P | History & Physical (clinical note) |
| HHA | Hospital Hospitalists Associates (this company) |
| HIPAA | Health Insurance Portability and Accountability Act |
| HL7 | Health Level Seven (healthcare data exchange standard) |
| ICD | International Classification of Diseases (diagnosis codes) |
| KV | Key Vault |
| LDS | Limited Data Set (HIPAA category) |
| LOS | Length of Stay |
| MFA | Multi-Factor Authentication |
| MGMA | Medical Group Management Association |
| MI | Managed Identity (Azure) |
| MRN | Medical Record Number |
| MSAL | Microsoft Authentication Library |
| NCR | Net Collection Rate |
| NPI | National Provider Identifier |
| OIDC | OpenID Connect |
| ORM | Object-Relational Mapper (e.g., SQLAlchemy) |
| PAT | Personal Access Token |
| PHI | Protected Health Information |
| PII | Personally Identifiable Information |
| PITR | Point-in-Time Restore |
| PM | Practice Management (software) |
| RBAC | Role-Based Access Control |
| RCM | Revenue Cycle Management |
| RG | Resource Group (Azure) |
| RPO | Recovery Point Objective |
| RTO | Recovery Time Objective |
| RVU | Relative Value Unit |
| SFTP | Secure File Transfer Protocol |
| SOW | Statement of Work |
| TLS | Transport Layer Security |
| UPN | User Principal Name (Entra ID — typically email) |
| VNet | Virtual Network (Azure) |
| WORM | Write-Once-Read-Many |
| WSL | Windows Subsystem for Linux |

---

**Next read:** [INDEX.md](INDEX.md) for the full doc map.
