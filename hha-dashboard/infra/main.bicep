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

@description('Enable Storage Account module (uploads + backups containers). Public-access disabled when enable_vnet is also true (PE wiring follows in Session 11+); otherwise public with deployer-IP allowlist.')
param enable_storage bool = false

@description('Enable Log Analytics + App Insights (monitor.bicep) plus Diagnostic Settings on every audited resource. Required for HIPAA audit chain in prod; optional in dev.')
param enable_monitor bool = false

@description('Log Analytics retention in days. 30 dev, 90 prod.')
@minValue(30)
@maxValue(730)
param monitor_retention_days int = 30

@description('Storage Account name. Convention: sthhad{env} (lowercase, alphanumeric only, globally unique). Default composes from env.')
param storage_account_name string = 'sthha${env_name}${uniqueString(resourceGroup().id)}'

@description('Storage SKU. Standard_LRS for dev, Standard_RAGRS for prod (cross-region read on backups).')
@allowed(['Standard_LRS', 'Standard_GRS', 'Standard_RAGRS', 'Standard_ZRS'])
param storage_sku string = 'Standard_LRS'

@description('Storage soft-delete retention days. 7 dev, 90 prod.')
@minValue(1)
@maxValue(365)
param storage_soft_delete_retention_days int = 7

@description('Enable vendor-inbound Storage Account (Ventra ingest pipeline per ADR-006). Separate from the main storage account because HNS + SFTP are create-time-only properties. Containers: vendor-inbound, vendor-quarantine, vendor-deadletter.')
param enable_vendor_storage bool = false

@description('Vendor-storage account name. Convention: sthhavendor{env} (lowercase, alphanumeric, globally unique). Default composes from env.')
param vendor_storage_account_name string = 'sthhavendor${env_name}${uniqueString(resourceGroup().id)}'

@description('Vendor-storage SKU. Standard_LRS for dev, Standard_ZRS for prod (zone-redundant since vendor drops cannot be replayed if lost).')
@allowed(['Standard_LRS', 'Standard_GRS', 'Standard_RAGRS', 'Standard_ZRS'])
param vendor_storage_sku string = 'Standard_LRS'

@description('Days after which vendor-inbound + vendor-quarantine blobs are auto-deleted. 90 = HIPAA audit retention window.')
@minValue(0)
@maxValue(365)
param vendor_storage_lifecycle_delete_days int = 90

@description('Enable SFTP service on the vendor-storage account. Adds ~$220/mo. Leave false if Ventra picks Snowflake-direct (SAS-token external stage) instead. Toggled per the architecture A3 decision.')
param enable_sftp bool = false

@secure()
@description('Ventra SFTP public SSH key (full OpenSSH-format public key content). Only consumed when enable_sftp is true. Rotated quarterly via Key Vault.')
param ventra_sftp_public_key string = ''

@description('Enable Event Grid system topic + manifest subscription + Storage Queue on the vendor-storage account. Requires enable_vendor_storage = true. When this is false the vendor-storage account still exists but blob events are silently dropped.')
param enable_vendor_eventgrid bool = false

@description('Enable Azure Communication Services (Email) for the daily 7am exec digest + credential expiry alerts. Uses an Azure Managed Domain in v0 (sender DoNotReply@<random>.azurecomm.net); custom domain attachment is a follow-up.')
param enable_email bool = false

@description('Enable Container Apps environment + the example pg_backup scheduled job. Other crons (paycom_sync, ventra_ingest, alert_digest, cred_scan) come as additional Job resources in follow-up PRs.')
param enable_container_jobs bool = false

@description('Enable Azure Container Registry. Required before any cron job can pull a real (non-placeholder) image. Default off; flip to true once you have a real CI image-push step. Adds ~$5/mo dev, ~$20/mo prod.')
param enable_acr bool = false

@description('ACR SKU. Basic for dev; Standard for prod with replication option.')
@allowed(['Basic', 'Standard', 'Premium'])
param acr_sku string = 'Basic'

@description('Enable cross-resource RBAC role assignments (AcrPull, Storage Blob Data Contributor, ACS Contributor). Each role is independently gated on the underlying resource being deployed; this master toggle is for "skip RBAC entirely in dev to keep deploys fast."')
param enable_rbac bool = false

@description('Container image for the pg_backup job. Default is a Microsoft sample; replace with a real image once an Azure Container Registry exists.')
param pg_backup_image string = 'mcr.microsoft.com/k8se/quickstart-jobs:latest'

@secure()
@description('Log Analytics workspace shared key for the Container Apps env appLogsConfiguration. Optional — when empty, container logs are not forwarded.')
param log_analytics_shared_key string = ''

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
var log_analytics_name = 'log-hha-${env_name}'
var app_insights_name = 'appi-hha-${env_name}'
var acs_name = 'acs-hha-${env_name}'
var email_service_name = 'ecs-hha-${env_name}'
// ACR rejects names with hyphens; convention is concatenated lowercase.
var acr_name = 'acrhha${env_name}'

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

// Storage Account — only deployed when enable_storage is true. Holds the
// `uploads` container (Crystal/Sandy/etc. drop files for the cron ingest
// to consume; auto-deleted after 7 days via lifecycle policy) and the
// `backups` container (pg_dump nightlies; immutability lock applied
// out-of-band by the operator after first backup writes successfully).
module storage './modules/storage.bicep' = if (enable_storage) {
  name: 'storage-deploy'
  params: {
    name: storage_account_name
    location: location
    sku: storage_sku
    soft_delete_retention_days: storage_soft_delete_retention_days
    deployer_workstation_ip: deployer_workstation_ip
    pe_subnet_id: enable_vnet ? vnet!.outputs.pe_subnet_id : ''
    tags: tags
  }
}

// Vendor-inbound Storage Account — Ventra ingest pipeline per ADR-006.
// Separate account because HNS + SFTP are create-time-only properties; the
// existing storage account was provisioned without them. Containers:
// vendor-inbound, vendor-quarantine, vendor-deadletter. Local user `ventra`
// is provisioned only when both enable_sftp is true AND a public key is
// supplied — otherwise the account is still SAS-token-accessible for the
// Snowflake-direct delivery channel (per Phase 1A.A3 of the plan).
module vendorStorage './modules/vendor_storage.bicep' = if (enable_vendor_storage) {
  name: 'vendor-storage-deploy'
  params: {
    name: vendor_storage_account_name
    location: location
    sku: vendor_storage_sku
    soft_delete_retention_days: storage_soft_delete_retention_days
    vendor_lifecycle_delete_days: vendor_storage_lifecycle_delete_days
    enable_sftp: enable_sftp
    ventra_sftp_public_key: ventra_sftp_public_key
    deployer_workstation_ip: deployer_workstation_ip
    pe_subnet_id: enable_vnet ? vnet!.outputs.pe_subnet_id : ''
    tags: tags
  }
}

// Vendor Event Grid — System Topic on vendor-storage + manifest-filtered
// subscription → q-ventra-manifests Storage Queue. Requires
// enable_vendor_storage = true (the topic source is the vendor account).
// When this is false the storage account still exists but blob events are
// silently dropped (operator can only see blob arrivals via manual scan).
//
// Gated separately from enable_vendor_storage so we can stand up the
// storage account first (e.g. to seed a sample drop manually) and wire
// the EG path in a follow-up deploy once the queue + topic are validated.
module vendorEventGrid './modules/vendor_eventgrid.bicep' = if (enable_vendor_storage && enable_vendor_eventgrid) {
  name: 'vendor-eventgrid-deploy'
  params: {
    vendor_storage_account_name: vendor_storage_account_name
    location: location
    tags: tags
  }
  dependsOn: [
    vendorStorage
  ]
}

// Log Analytics workspace + Application Insights — observability foundation.
// Diagnostic Settings on each downstream resource (postgres, app service,
// keyvault, storage) point at the workspace. Defined in this file (not the
// module) because each Diagnostic Setting is scoped to its target resource.
module monitor './modules/monitor.bicep' = if (enable_monitor) {
  name: 'monitor-deploy'
  params: {
    log_analytics_name: log_analytics_name
    app_insights_name: app_insights_name
    location: location
    retention_days: monitor_retention_days
    tags: tags
  }
}

// ACS + Email — only deployed when enable_email is true. The api uses
// AZURE_COMMUNICATION_ENDPOINT + the system-assigned managed identity
// (after a future RBAC role assignment) to send the 7am digest. v0 uses
// an Azure Managed Domain (sender DoNotReply@<random>.azurecomm.net);
// custom domain attachment is a follow-up.
module acsEmail './modules/acs-email.bicep' = if (enable_email) {
  name: 'acs-email-deploy'
  params: {
    acs_name: acs_name
    email_service_name: email_service_name
    tags: tags
  }
}

// Azure Container Registry — hosts the cron job images. Required before
// any cron can pull a non-placeholder image. dev defaults to off because
// the placeholder MS sample image is sufficient for compile-only verification.
module acr './modules/acr.bicep' = if (enable_acr) {
  name: 'acr-deploy'
  params: {
    acr_name: acr_name
    location: location
    sku: acr_sku
    tags: tags
  }
}

// Container Apps environment + example pg_backup scheduled job. The
// other 4 crons (paycom_sync, ventra_ingest, alert_digest, cred_scan)
// land as additional Job resources in follow-up PRs once a Container
// Registry exists for their images. log_analytics_customer_id pulls
// from monitor.outputs.workspace_customer_id when both flags are on,
// so container env logs flow into the same workspace as everything
// else; empty otherwise.
module containerjobs './modules/containerjobs.bicep' = if (enable_container_jobs) {
  name: 'containerjobs-deploy'
  params: {
    env_name_prefix: env_name
    location: location
    log_analytics_customer_id: enable_monitor ? monitor!.outputs.workspace_customer_id : ''
    log_analytics_shared_key: log_analytics_shared_key
    pg_backup_image: pg_backup_image
    // alert_digest + cred_scan: gated on email being configured. When
    // enable_email is false the cron jobs would no-op anyway, so we save
    // the resource cost by not provisioning them.
    enable_alert_jobs: enable_email
    azure_communication_endpoint: enable_email ? acsEmail!.outputs.acs_endpoint : ''
    azure_communication_sender: enable_email ? acsEmail!.outputs.sender_address : ''
    database_url: enable_keyvault
      ? '@Microsoft.KeyVault(VaultName=${kv_name};SecretName=database-url)'
      : database_url_literal
    tags: tags
  }
}

// Cross-resource role assignments (AcrPull, Storage Blob Data Contributor,
// ACS Contributor). Each assignment is independently gated on the
// underlying resource being deployed, so partial-state envs degrade
// cleanly. The master `enable_rbac` toggle exists so dev can skip role
// propagation entirely (faster deploys; nothing in dev needs MI auth).
module rbac './modules/rbac.bicep' = if (enable_rbac) {
  name: 'rbac-deploy'
  params: {
    acr_id: enable_acr ? acr!.outputs.acr_id : ''
    storage_id: enable_storage ? storage!.outputs.storage_id : ''
    acs_id: enable_email ? acsEmail!.outputs.acs_id : ''
    pg_backup_principal_id: enable_container_jobs ? containerjobs!.outputs.pg_backup_principal_id : ''
    alert_digest_principal_id: enable_container_jobs ? containerjobs!.outputs.alert_digest_principal_id : ''
    cred_scan_principal_id: enable_container_jobs ? containerjobs!.outputs.cred_scan_principal_id : ''
    api_principal_id: appservice.outputs.api_principal_id
  }
}

// Compose connection strings.
//
// App Service resolves `@Microsoft.KeyVault(...)` references only when the
// reference is the ENTIRE app_setting value, not a substring. So when KV is
// on, the connection strings themselves are stored in KV (seeded by
// bootstrap.sh as `database-url` + `database-url-sync` secrets), and
// app_settings just reference those secrets. When KV is off, app_settings
// gets the full literal string composed inline — Session 8 behavior.
//
// The literal-when-off path also serves as the deploy-time fallback: even
// in prod, the FIRST deploy lands with KV on but the secrets unseeded; the
// reference resolves to the literal `@Microsoft.KeyVault(...)` text and
// App Service logs the failed lookup. The operator runs bootstrap.sh and
// the next App Service restart picks up the resolved value.
var pg_host = postgres.outputs.host
var database_url_literal = 'postgresql+asyncpg://${postgres_admin_login}:${postgres_admin_password}@${pg_host}:5432/${database_name}?ssl=require'
var database_url_sync_literal = 'postgresql+psycopg://${postgres_admin_login}:${postgres_admin_password}@${pg_host}:5432/${database_name}?sslmode=require'
var database_url = enable_keyvault
  ? '@Microsoft.KeyVault(VaultName=${kv_name};SecretName=database-url)'
  : database_url_literal
var database_url_sync = enable_keyvault
  ? '@Microsoft.KeyVault(VaultName=${kv_name};SecretName=database-url-sync)'
  : database_url_sync_literal

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
  AZURE_STORAGE_ACCOUNT_URL: enable_storage ? storage!.outputs.blob_endpoint : ''
  AZURE_STORAGE_UPLOADS_CONTAINER: enable_storage ? storage!.outputs.uploads_container_name : 'uploads'
  APPLICATIONINSIGHTS_CONNECTION_STRING: enable_monitor ? monitor!.outputs.app_insights_connection_string : ''
  AZURE_COMMUNICATION_ENDPOINT: enable_email ? acsEmail!.outputs.acs_endpoint : ''
  AZURE_COMMUNICATION_SENDER: enable_email ? acsEmail!.outputs.sender_address : ''
  // Defer to Session 13+: Doc Intelligence endpoint
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
    app_subnet_id: enable_vnet ? vnet!.outputs.app_subnet_id : ''
    tags: tags
  }
}

// ---------------------------------------------------------------------------
// KV → App Service RBAC role assignments.
//
// Built-in role: Key Vault Secrets User
// (4633458b-17de-408a-b874-0445c86b69e6). Both App Service MIs need this on
// the vault for `@Microsoft.KeyVault(...)` references in app_settings to
// resolve. Conditional on enable_keyvault — when KV is off there's nothing
// to assign.
//
// Role assignment names use guid() of (vault_id, principal_id, role_id) so
// they're deterministic and idempotent across re-deploys.
// ---------------------------------------------------------------------------

var kv_secrets_user_role_id = '4633458b-17de-408a-b874-0445c86b69e6'

resource kvVaultExisting 'Microsoft.KeyVault/vaults@2024-04-01-preview' existing = if (enable_keyvault) {
  name: kv_name
}

// Role-assignment NAMES use guid() seeded with deploy-start values
// (vault id, app name, role id). The MI principalId is a deploy-time
// output from the appservice module, which Bicep refuses inside name
// (BCP120). Seeding the name with the app name is fine: it's unique
// per (vault, app, role) tuple and stable across re-deploys.
resource webKvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enable_keyvault) {
  scope: kvVaultExisting
  name: guid(kv_name, web_name, kv_secrets_user_role_id)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kv_secrets_user_role_id)
    principalId: appservice.outputs.web_principal_id
    principalType: 'ServicePrincipal'
  }
}

resource apiKvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enable_keyvault) {
  scope: kvVaultExisting
  name: guid(kv_name, api_name, kv_secrets_user_role_id)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kv_secrets_user_role_id)
    principalId: appservice.outputs.api_principal_id
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Diagnostic Settings — wire every audited resource to the Log Analytics
// workspace when enable_monitor is true. Each setting is scoped to its
// target resource via the `existing` reference pattern.
//
// Categories chosen for HIPAA audit relevance:
//   - Postgres: PostgreSQLLogs (connection events) + PostgreSQLFlexSessions
//   - App Service: AppServiceConsoleLogs, AppServiceHTTPLogs, AppServiceAuditLogs
//   - Key Vault: AuditEvent (every secret read/write)
//   - Storage (blob service): StorageRead, StorageWrite, StorageDelete
//
// AllMetrics enabled on every target so platform metrics flow alongside.
// ---------------------------------------------------------------------------

resource pgServerForDiag 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' existing = if (enable_monitor) {
  name: postgres_name
}

resource webForDiag 'Microsoft.Web/sites@2024-04-01' existing = if (enable_monitor) {
  name: web_name
}

resource apiForDiag 'Microsoft.Web/sites@2024-04-01' existing = if (enable_monitor) {
  name: api_name
}

resource pgDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enable_monitor) {
  scope: pgServerForDiag
  name: 'to-log-analytics'
  properties: {
    workspaceId: monitor!.outputs.workspace_id
    logs: [
      {
        category: 'PostgreSQLLogs'
        enabled: true
      }
      {
        category: 'PostgreSQLFlexSessions'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

resource webDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enable_monitor) {
  scope: webForDiag
  name: 'to-log-analytics'
  properties: {
    workspaceId: monitor!.outputs.workspace_id
    logs: [
      {
        category: 'AppServiceConsoleLogs'
        enabled: true
      }
      {
        category: 'AppServiceHTTPLogs'
        enabled: true
      }
      {
        category: 'AppServiceAuditLogs'
        enabled: true
      }
      {
        category: 'AppServiceAppLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

resource apiDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enable_monitor) {
  scope: apiForDiag
  name: 'to-log-analytics'
  properties: {
    workspaceId: monitor!.outputs.workspace_id
    logs: [
      {
        category: 'AppServiceConsoleLogs'
        enabled: true
      }
      {
        category: 'AppServiceHTTPLogs'
        enabled: true
      }
      {
        category: 'AppServiceAuditLogs'
        enabled: true
      }
      {
        category: 'AppServiceAppLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

resource kvDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enable_monitor && enable_keyvault) {
  scope: kvVaultExisting
  name: 'to-log-analytics'
  properties: {
    workspaceId: monitor!.outputs.workspace_id
    logs: [
      {
        category: 'AuditEvent'
        enabled: true
      }
      {
        category: 'AzurePolicyEvaluationDetails'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

// Storage Account diagnostic settings target the blob service sub-resource
// (audit at the data-plane level); the account-level settings are minimal.
resource blobServiceForDiag 'Microsoft.Storage/storageAccounts/blobServices@2024-01-01' existing = if (enable_monitor && enable_storage) {
  name: '${storage_account_name}/default'
}

resource blobDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enable_monitor && enable_storage) {
  scope: blobServiceForDiag
  name: 'to-log-analytics'
  properties: {
    workspaceId: monitor!.outputs.workspace_id
    logs: [
      {
        category: 'StorageRead'
        enabled: true
      }
      {
        category: 'StorageWrite'
        enabled: true
      }
      {
        category: 'StorageDelete'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'Transaction'
        enabled: true
      }
    ]
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

@description('Storage account blob endpoint when enable_storage is true; empty otherwise. Used as AZURE_STORAGE_ACCOUNT_URL in api app_settings.')
output storage_blob_endpoint string = enable_storage ? storage!.outputs.blob_endpoint : ''

@description('Storage account name when enable_storage is true; empty otherwise. Used by bootstrap/operator commands that target the account directly (e.g. setting the immutability lock on the backups container).')
output storage_account_name string = enable_storage ? storage!.outputs.storage_name : ''

@description('ACS endpoint URL when enable_email is true; empty otherwise. The api uses this as AZURE_COMMUNICATION_ENDPOINT for the SDK client.')
output acs_endpoint string = enable_email ? acsEmail!.outputs.acs_endpoint : ''

@description('Sender address from the Azure Managed Domain when enable_email is true; empty otherwise.')
output acs_sender_address string = enable_email ? acsEmail!.outputs.sender_address : ''

@description('Container Apps environment ID when enable_container_jobs is true; empty otherwise. Used to attach future Job resources (paycom_sync, alert_digest, etc).')
output container_env_id string = enable_container_jobs ? containerjobs!.outputs.env_id : ''

@description('pg_backup job principal ID (managed identity) when enable_container_jobs is true; empty otherwise. Wired to Storage Blob Data Contributor + AcrPull via rbac.bicep.')
output pg_backup_principal_id string = enable_container_jobs ? containerjobs!.outputs.pg_backup_principal_id : ''

@description('ACR resource ID when enable_acr is true; empty otherwise. Used by deploy workflows for `az acr login`.')
output acr_id string = enable_acr ? acr!.outputs.acr_id : ''

@description('ACR login server (e.g. acrhhaprod.azurecr.io) when enable_acr is true; empty otherwise. Used by deploy workflows for image push.')
output acr_login_server string = enable_acr ? acr!.outputs.login_server : ''
