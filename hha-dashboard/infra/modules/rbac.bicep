// Cross-resource role assignments — managed identities → roles → resources.
//
// Why a separate module:
//   - Each role assignment crosses two resources (the principal's MI and
//     the resource being granted-on). Inlining in main.bicep made it hard
//     to scan; this module concentrates "who can touch what."
//   - Conditional toggles (acr / storage / email) gate naturally here.
//
// What's NOT in this module:
//   - KV Secrets User for web/api (already inline in main.bicep, predates
//     this module — they're co-located with the KV resource for clarity).
//   - PG-level RBAC (per ADR-002 Part 3, schemas are separated for future
//     GRANT USAGE; not exercised today).
//
// Role IDs are built-in role definitions copied from Azure docs. Stable.
// See: https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles

@description('ACR resource ID. Empty disables the AcrPull assignments.')
param acr_id string = ''

@description('Storage Account resource ID. Empty disables Storage Blob Data Contributor assignments.')
param storage_id string = ''

@description('ACS (Azure Communication Services) resource ID. Empty disables email role assignments.')
param acs_id string = ''

@description('pg_backup job principal ID. Empty disables the assignment.')
param pg_backup_principal_id string = ''

@description('alert_digest job principal ID.')
param alert_digest_principal_id string = ''

@description('cred_scan job principal ID.')
param cred_scan_principal_id string = ''

@description('api App Service principal ID — used for ACS so the api can send transactional email when needed.')
param api_principal_id string = ''

// ---------- Built-in role IDs ----------

// Storage Blob Data Contributor — full read/write on blob data plane (NOT
// management plane). This is what lets pg_backup MI upload .dump files
// without needing a Storage account key.
var ROLE_STORAGE_BLOB_DATA_CONTRIBUTOR = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

// AcrPull — pull images from a container registry. Does NOT grant push.
var ROLE_ACR_PULL = '7f951dda-4ed3-11e8-89ce-9f0bf9c2bcae'

// Contributor (on the ACS resource specifically) — required to issue
// EmailMessage operations via managed identity. ACS doesn't have a
// finer-grained "send only" role; this is the documented best-fit.
// https://learn.microsoft.com/en-us/azure/communication-services/concepts/authentication
var ROLE_CONTRIBUTOR = 'b24988ac-6180-42a0-ab88-20f7382dd24c'

// ---------- ACR pull (cron jobs) ----------

resource pgBackupAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(acr_id) && !empty(pg_backup_principal_id)) {
  name: guid(acr_id, pg_backup_principal_id, 'AcrPull')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', ROLE_ACR_PULL)
    principalId: pg_backup_principal_id
    principalType: 'ServicePrincipal'
    description: 'pg_backup MI can pull its image from ACR'
  }
}

resource alertDigestAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(acr_id) && !empty(alert_digest_principal_id)) {
  name: guid(acr_id, alert_digest_principal_id, 'AcrPull')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', ROLE_ACR_PULL)
    principalId: alert_digest_principal_id
    principalType: 'ServicePrincipal'
    description: 'alert_digest MI can pull its image from ACR'
  }
}

resource credScanAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(acr_id) && !empty(cred_scan_principal_id)) {
  name: guid(acr_id, cred_scan_principal_id, 'AcrPull')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', ROLE_ACR_PULL)
    principalId: cred_scan_principal_id
    principalType: 'ServicePrincipal'
    description: 'cred_scan MI can pull its image from ACR'
  }
}

// ---------- Storage Blob Data Contributor (pg_backup) ----------

resource pgBackupStorageBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(storage_id) && !empty(pg_backup_principal_id)) {
  name: guid(storage_id, pg_backup_principal_id, 'StorageBlobDataContributor')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', ROLE_STORAGE_BLOB_DATA_CONTRIBUTOR)
    principalId: pg_backup_principal_id
    principalType: 'ServicePrincipal'
    description: 'pg_backup MI uploads dumps to backups/ via managed identity (no account key)'
  }
}

// ---------- ACS Contributor (email senders) ----------
//
// ACS auth via MI requires Contributor on the resource. There's no narrower
// built-in role for "send only" — Microsoft documents Contributor as the
// expected role. If compliance asks, can be revisited via custom role.

resource alertDigestAcsContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(acs_id) && !empty(alert_digest_principal_id)) {
  name: guid(acs_id, alert_digest_principal_id, 'AcsContributor')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', ROLE_CONTRIBUTOR)
    principalId: alert_digest_principal_id
    principalType: 'ServicePrincipal'
    description: 'alert_digest MI can send via ACS Email'
  }
}

resource credScanAcsContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(acs_id) && !empty(cred_scan_principal_id)) {
  name: guid(acs_id, cred_scan_principal_id, 'AcsContributor')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', ROLE_CONTRIBUTOR)
    principalId: cred_scan_principal_id
    principalType: 'ServicePrincipal'
    description: 'cred_scan MI can send via ACS Email'
  }
}

resource apiAcsContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(acs_id) && !empty(api_principal_id)) {
  name: guid(acs_id, api_principal_id, 'AcsContributor')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', ROLE_CONTRIBUTOR)
    principalId: api_principal_id
    principalType: 'ServicePrincipal'
    description: 'api MI can send transactional email (e.g. cred-rotation notices) via ACS'
  }
}
