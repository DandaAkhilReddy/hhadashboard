// Prod environment parameters.
//
// SKUs sized for the live HHA dashboard: 5–10 exec users, audit retention,
// HA across availability zones, geo-redundant backups.
//
// Approximate monthly cost (eastus2):
//   Postgres D2ds_v5 ZoneRedundant + 35d retention   ~$310
//   App Service P1v3 (2 instances, shared by web+api) ~$155
//   Total before storage / observability             ~$465
//
// At deploy time, supply secure params from Key Vault:
//   az deployment group create -g rg-hha-dashboard-prod -f infra/main.bicep \
//     -p infra/env/prod.bicepparam \
//     -p postgres_admin_password=$(az keyvault secret show --vault-name kv-hha-prod -n postgres-admin --query value -o tsv) \
//     -p deployer_workstation_ip=$(curl -s ifconfig.me)

using '../main.bicep'

// MUST be overridden at deploy time. In prod, postgres_admin_password should
// come from Key Vault via:
//   -p postgres_admin_password=$(az keyvault secret show --vault-name kv-hha-prod -n postgres-admin --query value -o tsv)
// Empty placeholder here so the bicepparam compiles; deploy will fail safely
// without an override.
param postgres_admin_password = '__OVERRIDE_AT_DEPLOY_TIME__'
param deployer_workstation_ip = '162.227.196.122'

param env_name = 'prod'
param location = 'eastus2'

// Postgres — General Purpose D2ds_v5 with HA + geo-redundant backups
param postgres_sku_name = 'Standard_D2ds_v5'
param postgres_sku_tier = 'GeneralPurpose'
param postgres_backup_retention_days = 35
param postgres_geo_redundant_backup = 'Enabled'
param postgres_ha_mode = 'ZoneRedundant'

// App Service — Premium V3 P1v3 with 2 instances (shared by web + api)
// Known limitation per the plan: noisy-neighbor risk on scale events.
// Splitting into two plans is a follow-up.
param plan_sku_name = 'P1v3'
param plan_sku_tier = 'PremiumV3'
param worker_count = 2

// VNet + Key Vault — both ON in prod.
//   - VNet: 10.20.0.0/16 with 3 subnets, 2 private DNS zones
//   - Postgres injected into the postgres subnet (no public address)
//   - Key Vault reachable via private endpoint in the PE subnet
// Adds ~$30/mo in eastus2 for the VNet + 2 PEs + 2 DNS zones.
//
// azure_tenant_id_for_kv must be a real value at deploy time — KV requires
// the tenant ID even with RBAC. Override via -p at deploy if not set here.
param enable_vnet = true
param enable_keyvault = true
param azure_tenant_id_for_kv = '76596b76-3c41-40ee-a8a3-bf6930301838'

// Storage — ON in prod. Standard_RAGRS for cross-region read-access on
// backups (the LRS variant works but loses the regional-failover read
// path). Soft-delete 90 days for HIPAA-friendlier retention. Adds about
// $10/mo for the account (much less if backups < 100 GB).
param enable_storage = true
param storage_sku = 'Standard_RAGRS'
param storage_soft_delete_retention_days = 90

// Monitor — ON in prod. Required for HIPAA audit chain.
param enable_monitor = true
param monitor_retention_days = 90

// Email — ON in prod. ACS + Email Communications Service with an Azure
// Managed Domain. Custom domain attachment is a follow-up.
param enable_email = true

// Container Apps Jobs — ON in prod. Cron infrastructure for pg_backup
// (nightly @ 03:00 UTC), with the rest joining as the corresponding job
// images land. Consumption plan billing scales with execution time only.
param enable_container_jobs = true

// ACR — ON in prod. Standard SKU gives 100GB storage + replication option
// at $20/mo. Premium ($100+/mo) only needed for content trust signing or
// VNet-private ACR. Image cleanup task scheduled post-deploy.
param enable_acr = true
param acr_sku = 'Standard'

// RBAC — ON in prod. Wires AcrPull (cron jobs → ACR), Storage Blob Data
// Contributor (pg_backup → backups/), and ACS Contributor (alert_digest +
// cred_scan + api → ACS Email). All use system-assigned MIs — no static
// credentials anywhere in the runtime.
param enable_rbac = true

// Entra IDs — populated from `scripts/azure_create_missing.sh` discovery
// run on 2026-04-28. The 7 groups + 2 app registrations live in the
// HHA Medicine M365 tenant (76596b76-...).
param azure_tenant_id = '76596b76-3c41-40ee-a8a3-bf6930301838'
param azure_api_client_id = 'cabdd848-2221-4b21-9d2d-86572d791ee0'
param entra_groups = {
  admin: '12251714-b09d-4947-a82c-16057a36ef04'
  exec: 'a8d33d7f-a734-41a0-9d5b-3c450346a749'
  comp_viewer: '8198f75c-fc30-4b29-a309-957677906627'
  owner_ops: '752e1ab9-e361-4bdf-ba6c-d66f09094f84'
  owner_finance: '840d3f12-9ce8-4450-845e-294049073ccd'
  owner_clinical: '64fad693-3087-4532-9a2d-850f06bd1599'
  owner_hr: '13a06f26-6d65-4466-9c5a-f39a5698e33e'
}

param tags = {
  project: 'hha-dashboard'
  environment: 'prod'
  managed_by: 'bicep'
  classification: 'phi-tier-b'
  cost_center: 'operations'
}
