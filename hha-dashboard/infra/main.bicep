// HHA Dashboard — root Bicep template (RG-scoped).
//
// What this deploys:
//   - One Postgres Flexible Server v16 + database + deployer firewall rule
//   - One App Service Plan (Linux) + one Web app (Next.js) + one API app (FastAPI)
//   - Firewall rules on Postgres for each of the API app's outbound IPs
//
// What this does NOT deploy (out of scope for the v0 scaffold; see plan):
//   - VNet, private endpoints, private DNS zones
//   - Key Vault (secrets pass via app_settings; KV references replace them later)
//   - Blob Storage (uploads, backups)
//   - Container Apps Jobs (cron)
//   - Application Insights / Log Analytics (no diagnostic settings)
//   - Communication Services (Email)
//   - RBAC role assignments (none yet — no managed identities consume anything)
//   - Custom domain / managed cert
//
// Verification: `az bicep build` and `az bicep lint` only — no live deploy.

targetScope = 'resourceGroup'

// ---------------------------------------------------------------------------
// Parameters
// ---------------------------------------------------------------------------

@description('Environment short name. Becomes the suffix in all resource names.')
@allowed(['dev', 'prod'])
param env_name string

@description('Azure region. Picked for Postgres Flex SKU coverage and 3-AZ availability.')
param location string = 'eastus2'

@description('Postgres SKU name, e.g. Standard_B2ms (dev) or Standard_D2ds_v5 (prod).')
param postgres_sku_name string

@description('Postgres SKU tier. Burstable (dev) or GeneralPurpose (prod).')
@allowed(['Burstable', 'GeneralPurpose', 'MemoryOptimized'])
param postgres_sku_tier string

@description('Postgres backup retention days. 7 (dev) to 35 (prod max).')
@minValue(7)
@maxValue(35)
param postgres_backup_retention_days int

@description('Geo-redundant Postgres backup. Enabled in prod.')
@allowed(['Enabled', 'Disabled'])
param postgres_geo_redundant_backup string

@description('Postgres high-availability mode. ZoneRedundant in prod.')
@allowed(['ZoneRedundant', 'SameZone', 'Disabled'])
param postgres_ha_mode string

@description('Postgres admin login. Must not be a reserved name (admin, root, etc.).')
param postgres_admin_login string = 'hhaadmin'

@secure()
@description('Postgres admin password. Supplied at deploy time, never persisted.')
param postgres_admin_password string

@description('Deployer workstation IP. Used for the single Postgres firewall rule that lets the operator run migrations directly. No 0.0.0.0 rule is created.')
param deployer_workstation_ip string

@description('App Service Plan SKU name. B2 (dev) or P1v3 (prod).')
param plan_sku_name string

@description('App Service Plan SKU tier. Basic (dev) or PremiumV3 (prod).')
@allowed(['Basic', 'Standard', 'PremiumV2', 'PremiumV3'])
param plan_sku_tier string

@description('App Service worker count. 1 (dev), 2 (prod).')
@minValue(1)
param worker_count int

@description('Microsoft Entra tenant id. Empty allowed in dev to keep the dev-stub auth flow working.')
param azure_tenant_id string = ''

@description('Microsoft Entra API app (registration) client id.')
param azure_api_client_id string = ''

@description('Entra group object IDs that map to roles.')
param entra_groups object = {
  admin: ''
  exec: ''
  comp_viewer: ''
  owner_ops: ''
  owner_finance: ''
  owner_clinical: ''
  owner_hr: ''
}

@description('Enable VNet + private DNS zones. When true, Postgres switches to VNet injection (no public access). When false, the v0 public-with-firewall posture from Session 8 stays.')
param enable_vnet bool = false

@description('Enable Key Vault module. Creates an empty vault with private endpoint (when enable_vnet is also true) or public-with-IP-allowlist (when enable_vnet is false). Initial secrets are seeded out-of-band by bootstrap.sh in Session 10.')
param enable_keyvault bool = false

@description('Microsoft Entra tenant id for Key Vault RBAC. Required when enable_keyvault is true.')
param azure_tenant_id_for_kv string = ''

@description('Tags applied to every resource.')
param tags object = {
  project: 'hha-dashboard'
  environment: env_name
  managed_by: 'bicep'
  classification: 'phi-tier-b'
}

// ---------------------------------------------------------------------------
// Names — single source of truth for every resource in the deployment.
// ---------------------------------------------------------------------------

var postgres_name = 'psql-hha-${env_name}'
var plan_name = 'plan-hha-${env_name}'
var web_name = 'app-hha-web-${env_name}'
var api_name = 'app-hha-api-${env_name}'
var database_name = 'hha_dashboard'
var vnet_name = 'vnet-hha-${env_name}'
var kv_name = 'kv-hha-${env_name}'

// ---------------------------------------------------------------------------
// Modules
// ---------------------------------------------------------------------------

// VNet + private DNS zones — only deployed when enable_vnet is true. The
// outputs are referenced conditionally below; downstream modules consume
// the subnet/zone IDs only when vnet exists.
module vnet './modules/vnet.bicep' = if (enable_vnet) {
  name: 'vnet-deploy'
  params: {
    name: vnet_name
    location: location
    tags: tags
  }
}

module postgres './modules/postgres.bicep' = {
  name: 'postgres-deploy'
  params: {
    name: postgres_name
    location: location
    sku_name: postgres_sku_name
    sku_tier: postgres_sku_tier
    backup_retention_days: postgres_backup_retention_days
    geo_redundant_backup: postgres_geo_redundant_backup
    ha_mode: postgres_ha_mode
    admin_login: postgres_admin_login
    admin_password: postgres_admin_password
    database_name: database_name
    deployer_workstation_ip: deployer_workstation_ip
    delegated_subnet_id: enable_vnet ? vnet!.outputs.postgres_subnet_id : ''
    private_dns_zone_id: enable_vnet ? vnet!.outputs.pg_dns_zone_id : ''
    tags: tags
  }
}

// Key Vault — only deployed when enable_keyvault is true. When VNet is also
// on, the vault gets a private endpoint in the PE subnet and goes private.
// When VNet is off, the vault stays public with a network-ACL default-deny
// + the deployer workstation IP allowlist.
module keyvault './modules/keyvault.bicep' = if (enable_keyvault) {
  name: 'keyvault-deploy'
  params: {
    name: kv_name
    location: location
    tenant_id: azure_tenant_id_for_kv
    deployer_workstation_ip: deployer_workstation_ip
    pe_subnet_id: enable_vnet ? vnet!.outputs.pe_subnet_id : ''
    dns_zone_id: enable_vnet ? vnet!.outputs.kv_dns_zone_id : ''
    tags: tags
  }
}

// Compose connection strings inline so the password never lives in the
// postgres module's outputs (which are visible to RG Reader).
var pg_host = postgres.outputs.host
var database_url = 'postgresql+asyncpg://${postgres_admin_login}:${postgres_admin_password}@${pg_host}:5432/${database_name}?ssl=require'
var database_url_sync = 'postgresql+psycopg://${postgres_admin_login}:${postgres_admin_password}@${pg_host}:5432/${database_name}?sslmode=require'

var common_app_settings = {
  ENV: env_name
  LOG_LEVEL: env_name == 'prod' ? 'INFO' : 'DEBUG'
}

var api_app_settings = union(common_app_settings, {
  DATABASE_URL: database_url
  DATABASE_URL_SYNC: database_url_sync
  AZURE_TENANT_ID: azure_tenant_id
  AZURE_API_CLIENT_ID: azure_api_client_id
  ENTRA_GROUP_ADMIN: entra_groups.admin
  ENTRA_GROUP_EXEC: entra_groups.exec
  ENTRA_GROUP_COMP_VIEWER: entra_groups.comp_viewer
  ENTRA_GROUP_OWNER_OPS: entra_groups.owner_ops
  ENTRA_GROUP_OWNER_FINANCE: entra_groups.owner_finance
  ENTRA_GROUP_OWNER_CLINICAL: entra_groups.owner_clinical
  ENTRA_GROUP_OWNER_HR: entra_groups.owner_hr
  // Defer to Session 9+: ACS connection, Blob URL, Doc Intelligence endpoint
})

var web_app_settings = union(common_app_settings, {
  // The web tier reads the API base URL + Entra IDs (NEXT_PUBLIC_*).
  // Since these are inlined at build, the deploy step (Session 9+) will
  // typically run `npm run build` in CI rather than relying on runtime env.
  // We set them here so a runtime `next start` can find them too.
  NEXT_PUBLIC_API_BASE_URL: 'https://${api_name}.azurewebsites.net'
  NEXT_PUBLIC_AUTH_MODE: env_name == 'prod' ? 'prod' : 'dev'
  NEXT_PUBLIC_AZURE_TENANT_ID: azure_tenant_id
  NEXT_PUBLIC_AZURE_API_CLIENT_ID: azure_api_client_id
  // SESSION_SECRET for the encrypted hha_session cookie comes from KV in prod;
  // in dev a placeholder is set per env params (out of scope for this scaffold).
})

module appservice './modules/appservice.bicep' = {
  name: 'appservice-deploy'
  params: {
    plan_name: plan_name
    web_name: web_name
    api_name: api_name
    location: location
    plan_sku_name: plan_sku_name
    plan_sku_tier: plan_sku_tier
    worker_count: worker_count
    app_settings_web: web_app_settings
    app_settings_api: api_app_settings
    tags: tags
  }
}

// ---------------------------------------------------------------------------
// API outbound → Postgres firewall wiring (post-deploy step, not in template).
//
// Bicep can't use a deploy-time output (App Service outboundIpAddresses) as
// the count of a resource loop (BCP178). The cleanest workaround for a
// scaffold is to wire the firewall rules in a one-off shell step after the
// initial deploy. README has the snippet:
//
//   for ip in $(az webapp show -n app-hha-api-${env} -g rg-hha-dashboard-${env} \
//        --query outboundIpAddresses -o tsv | tr ',' ' '); do
//     az postgres flexible-server firewall-rule create \
//        -g rg-hha-dashboard-${env} -n psql-hha-${env} \
//        --rule-name "api-outbound-${ip//./-}" \
//        --start-ip-address "$ip" --end-ip-address "$ip"
//   done
//
// When the vnet.bicep module lands (Session 9), this whole block goes away —
// VNet integration replaces public + firewall with a private endpoint.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Outputs — public, non-secret only.
// ---------------------------------------------------------------------------

@description('Public URL of the Next.js web app.')
output web_url string = 'https://${appservice.outputs.web_hostname}'

@description('Public URL of the FastAPI api app.')
output api_url string = 'https://${appservice.outputs.api_hostname}'

@description('Postgres FQDN. Connection string is composed inline; not output here.')
output postgres_host string = postgres.outputs.host

@description('Database name on the Postgres server.')
output database_name string = postgres.outputs.database_name

@description('Web app system-assigned managed identity principal ID.')
output web_principal_id string = appservice.outputs.web_principal_id

@description('API app system-assigned managed identity principal ID.')
output api_principal_id string = appservice.outputs.api_principal_id

@description('Key Vault URI when enable_keyvault is true; empty otherwise. Use as the base URI for @Microsoft.KeyVault(...) app_settings references after bootstrap.sh seeds the secrets in Session 10.')
output vault_uri string = enable_keyvault ? keyvault!.outputs.vault_uri : ''

@description('Key Vault name when enable_keyvault is true; empty otherwise. Used by bootstrap.sh and by the App Service RBAC role assignment in Session 10.')
output vault_name string = enable_keyvault ? keyvault!.outputs.vault_name : ''

@description('VNet resource ID when enable_vnet is true; empty otherwise. Used by Session 10 to wire App Service VNet integration.')
output vnet_id string = enable_vnet ? vnet!.outputs.vnet_id : ''

@description('App subnet ID when enable_vnet is true; empty otherwise. App Service VNet integration in Session 10 attaches here.')
output app_subnet_id string = enable_vnet ? vnet!.outputs.app_subnet_id : ''
