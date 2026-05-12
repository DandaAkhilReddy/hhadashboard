// Dev environment parameters.
//
// SKUs sized for a single-developer workstation + 5–10 occasional users.
// Cheap, no HA, no geo-redundant backups.
//
// At deploy time, supply the secure parameters via:
//   az deployment group create -g rg-hha-dashboard-dev -f infra/main.bicep \
//     -p infra/env/dev.bicepparam \
//     -p postgres_admin_password=$(openssl rand -base64 24) \
//     -p deployer_workstation_ip=$(curl -s ifconfig.me)

using '../main.bicep'

// MUST be overridden at deploy time. Bicep requires every non-defaulted
// parameter to have an assignment here, even @secure() ones. The placeholders
// will fail validation downstream (Postgres rejects empty admin password)
// before any resource is actually created — but always pass real values via
// the -p flag on `az deployment group create`.
param postgres_admin_password = '__OVERRIDE_AT_DEPLOY_TIME__'
param deployer_workstation_ip = '0.0.0.0'

param env_name = 'dev'
param location = 'eastus2'

// Postgres — Burstable B2ms is the cheapest Flex Server tier
param postgres_sku_name = 'Standard_B2ms'
param postgres_sku_tier = 'Burstable'
param postgres_backup_retention_days = 7
param postgres_geo_redundant_backup = 'Disabled'
param postgres_ha_mode = 'Disabled'

// App Service — Basic B2 (1 instance) is fine for dev
param plan_sku_name = 'B2'
param plan_sku_tier = 'Basic'
param worker_count = 1

// VNet + Key Vault — off in dev. Public Postgres + literal app_settings is
// fine here; the auditor flag and KV cost overhead are prod-only concerns.
// Override to true at deploy time if you want to test the private posture
// against the dev RG before flipping prod.
param enable_vnet = false
param enable_keyvault = false
param azure_tenant_id_for_kv = ''

// Storage — off in dev. Local Azurite covers uploads at compose-up time;
// real Storage Account is prod-only for now. Override to true if you want
// to test the upload pipeline against real Azure Blob from dev.
param enable_storage = false
param storage_sku = 'Standard_LRS'
param storage_soft_delete_retention_days = 7

// Vendor-inbound Storage — Ventra ingest pipeline per ADR-006. Off in dev
// until Ventra confirms the delivery shape (SFTP vs Snowflake-direct).
// Once they confirm + we have their SSH public key (SFTP path) or their
// Snowflake account ID (direct path), flip enable_vendor_storage to true
// here and seed ventra_sftp_public_key at deploy time via the -p flag.
param enable_vendor_storage = false
param vendor_storage_sku = 'Standard_LRS'
param vendor_storage_lifecycle_delete_days = 90
param enable_sftp = false
param ventra_sftp_public_key = ''
// Event Grid: System Topic on vendor-storage + manifest-filtered
// subscription → q-ventra-manifests queue. Stays off until
// enable_vendor_storage is flipped on (the topic source is the vendor
// account). Two-stage rollout = land storage first, validate manually,
// then wire the EG path.
param enable_vendor_eventgrid = false
// ventra_ingest event-driven Container Apps Job. Default off; flip to true
// when (a) the placeholder image is replaced by a real ACR-pushed
// ventra-ingest:{sha} (C20 CI workflow + C9-C16 Python code), and (b) the
// dependencies (enable_container_jobs + enable_vendor_storage +
// enable_vendor_eventgrid) are all on.
param enable_ventra_ingest_job = false
param ventra_ingest_image = 'mcr.microsoft.com/k8se/quickstart-jobs:latest'
param ventra_ops_email_recipients = 'areddy@hhamedicine.com'

// Monitor — off in dev to save Log Analytics ingestion costs (~$2.30/GB).
param enable_monitor = false
param monitor_retention_days = 30

// Email — off in dev. Mailpit catches outbound email at compose-up time.
param enable_email = false

// Container Apps Jobs — off in dev. Cron jobs run locally via
// `python -m jobs.upload_ingest.main` etc.
param enable_container_jobs = false

// ACR — off in dev. Cron images aren't deployed in dev (jobs run from
// the laptop). Flip to true if you want to test image-push end-to-end.
param enable_acr = false
param acr_sku = 'Basic'

// RBAC — off in dev. Nothing in dev needs MI auth (dev uses connection
// strings + dev fallback header). Skipping role propagation makes redeploys
// faster.
param enable_rbac = false

// Entra IDs — empty in dev so the API falls back to the Authorization: Dev <role>
// stub flow. When the Entra app registrations land per docs/ENTRA_SETUP.md,
// fill these in or override at deploy time.
param azure_tenant_id = ''
param azure_api_client_id = ''
param entra_groups = {
  admin: ''
  exec: ''
  comp_viewer: ''
  owner_ops: ''
  owner_finance: ''
  owner_clinical: ''
  owner_hr: ''
}

param tags = {
  project: 'hha-dashboard'
  environment: 'dev'
  managed_by: 'bicep'
  classification: 'phi-tier-b'
  cost_center: 'engineering'
}
