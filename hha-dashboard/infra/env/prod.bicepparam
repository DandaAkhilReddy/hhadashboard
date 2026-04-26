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
param deployer_workstation_ip = '0.0.0.0'

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
param azure_tenant_id_for_kv = ''

// Storage — ON in prod. Standard_RAGRS for cross-region read-access on
// backups (the LRS variant works but loses the regional-failover read
// path). Soft-delete 90 days for HIPAA-friendlier retention. Adds about
// $10/mo for the account (much less if backups < 100 GB).
param enable_storage = true
param storage_sku = 'Standard_RAGRS'
param storage_soft_delete_retention_days = 90

// Monitor — ON in prod. Required for HIPAA audit chain (Diagnostic Settings
// route Postgres / App Service / Key Vault / Storage logs into the
// workspace). 90-day retention; longer-term retention runs in the
// Postgres audit_log table at the schema level. Workspace ingestion cost
// scales with traffic — budget ~$50/mo for 5–10 user dashboards.
param enable_monitor = true
param monitor_retention_days = 90

// Email — ON in prod. ACS + Email Communications Service with an Azure
// Managed Domain (sender DoNotReply@<random>.azurecomm.net). Daily 7am
// digest + credential expiry alerts route through here. Custom domain
// attachment (alerts@hhamedicine.com) is a follow-up.
param enable_email = true

// Entra IDs — populate from the prod app registrations.
// Override at deploy time if these aren't yet committed.
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
  environment: 'prod'
  managed_by: 'bicep'
  classification: 'phi-tier-b'
  cost_center: 'operations'
}
