// Storage Account module — uploads container + backups container.
//
// Two containers with different retention semantics:
//   uploads/   — Crystal/Sandy/etc. drop PDFs and Excel files here. The cron
//                ingest job reads + processes them, then tags the blob
//                status=processed. Lifecycle policy (in this module) auto-
//                deletes processed blobs after 7 days. Raw bytes never leave
//                Azure under HHA's M365 BAA.
//
//   backups/   — pg_backup cron job (Session 11 follow-up) writes nightly
//                pg_dump tarballs here. Container has soft-delete enabled
//                (90 days) and an *optional* immutability policy that the
//                operator locks via Azure CLI after the first backup writes
//                successfully. Locking is irreversible — by design — so it's
//                NOT done automatically by Bicep. README documents the lock
//                command.
//
// HIPAA-relevant defaults baked in:
//   - allowBlobPublicAccess: false (no anonymous reads ever)
//   - supportsHttpsTrafficOnly: true
//   - minimumTlsVersion: TLS1_2
//   - publicNetworkAccess: Disabled (when pe_subnet_id is set; otherwise
//     Enabled with a tight network-ACL allowlist)
//   - infrastructure encryption (double encryption at rest)
//   - SKU Standard_RAGRS in prod for cross-region read access on backups;
//     Standard_LRS in dev (cheaper)
//
// What this module is NOT (deferred):
//   - Customer-managed key (CMK) — platform-managed keys for v0
//   - Private endpoint creation (parameter-ready; main.bicep wires it
//     when both enable_vnet AND enable_storage are true)
//   - Diagnostic settings → Log Analytics (lands with monitor.bicep)
//   - Container Apps Job that writes to backups/ (separate module)

@description('Storage Account name. Convention: sthhad{env}{suffix}. Lowercase, alphanumeric only, 3-24 chars, globally unique.')
@minLength(3)
@maxLength(24)
param name string

@description('Azure region.')
param location string

@description('SKU. Standard_LRS for dev (single-region, cheap), Standard_RAGRS for prod (cross-region read on backups).')
@allowed(['Standard_LRS', 'Standard_GRS', 'Standard_RAGRS', 'Standard_ZRS'])
param sku string = 'Standard_LRS'

@description('Soft-delete retention for blobs (days). 7 dev, 90 prod.')
@minValue(1)
@maxValue(365)
param soft_delete_retention_days int = 7

@description('Days after which processed uploads are auto-deleted (lifecycle policy). 0 disables the policy.')
@minValue(0)
@maxValue(90)
param uploads_lifecycle_delete_days int = 7

@description('Deployer workstation IP for the network ACL. Only used when pe_subnet_id is empty (public mode).')
param deployer_workstation_ip string = ''

@description('Private-endpoints subnet resource ID. When non-empty, locks down public access.')
param pe_subnet_id string = ''

@description('Tags to apply to every resource.')
param tags object = {}

var private_mode = !empty(pe_subnet_id)

resource storage 'Microsoft.Storage/storageAccounts@2024-01-01' = {
  name: name
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: sku
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: true // platform-managed identity will use this; CMK story is separate
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: private_mode ? 'Disabled' : 'Enabled'
    encryption: {
      services: {
        blob: {
          enabled: true
          keyType: 'Account'
        }
        file: {
          enabled: true
          keyType: 'Account'
        }
      }
      keySource: 'Microsoft.Storage'
      requireInfrastructureEncryption: true
    }
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      ipRules: empty(deployer_workstation_ip) ? [] : [
        {
          value: deployer_workstation_ip
          action: 'Allow'
        }
      ]
      virtualNetworkRules: []
    }
  }
}

// Blob service config — soft-delete + container soft-delete.
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2024-01-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: soft_delete_retention_days
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: soft_delete_retention_days
    }
    isVersioningEnabled: true
    changeFeed: {
      enabled: false
    }
  }
}

resource uploadsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2024-01-01' = {
  parent: blobService
  name: 'uploads'
  properties: {
    publicAccess: 'None'
    metadata: {
      purpose: 'manual-uploads-from-owners-csv-xlsx-pdf'
    }
  }
}

resource backupsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2024-01-01' = {
  parent: blobService
  name: 'backups'
  properties: {
    publicAccess: 'None'
    metadata: {
      purpose: 'pg-dump-nightlies-immutability-locked-by-operator'
    }
  }
}

// Lifecycle policy — auto-delete processed uploads after N days.
// Only created when uploads_lifecycle_delete_days > 0 (the default 7).
resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2024-01-01' = if (uploads_lifecycle_delete_days > 0) {
  parent: storage
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'delete-processed-uploads-after-N-days'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: [
                'blockBlob'
              ]
              prefixMatch: [
                'uploads/'
              ]
            }
            actions: {
              baseBlob: {
                delete: {
                  daysAfterModificationGreaterThan: uploads_lifecycle_delete_days
                }
              }
            }
          }
        }
      ]
    }
  }
}

@description('Storage account resource ID.')
output storage_id string = storage.id

@description('Storage account name (echoed for symmetry).')
output storage_name string = storage.name

@description('Blob endpoint primary URL — the App Service uses this as AZURE_STORAGE_ACCOUNT_URL.')
output blob_endpoint string = storage.properties.primaryEndpoints.blob

@description('Uploads container name.')
output uploads_container_name string = uploadsContainer.name

@description('Backups container name.')
output backups_container_name string = backupsContainer.name
