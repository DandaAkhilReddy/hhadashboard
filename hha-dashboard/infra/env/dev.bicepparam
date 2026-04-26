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
