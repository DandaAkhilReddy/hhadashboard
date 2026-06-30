// Vendor-inbound Storage Account — dedicated to receiving pre-aggregated
// CSVs from external vendors (Ventra Phase 1; future vendors reuse the
// pattern).
//
// WHY A SEPARATE STORAGE ACCOUNT (vs extending storage.bicep):
//   1. HNS (hierarchical namespace) is a CREATE-TIME property. The existing
//      storage account was provisioned without it; enabling it on the
//      existing account would require recreate. Cleaner to keep this account
//      isolated.
//   2. Different trust boundary. Vendor inbound is a different threat model
//      from operator uploads (different identity, different content
//      classification, different retention). Dedicated account = simpler
//      RBAC scoping (vendor MI only gets access to this account, not the
//      main one) and easier blast-radius control.
//   3. Different cost profile. SFTP service fee (~$220/mo when enabled) is
//      tied to this account only; the main storage stays at the standard
//      blob price.
//
// Containers created here (no Bicep-level RBAC; assigned via rbac.bicep):
//   vendor-inbound      — Ventra writes here (SFTP push OR Snowflake-direct
//                         via SAS token external stage). Container Apps Job
//                         reads + triggers the ingest pipeline. 90-day
//                         lifecycle delete for audit retention.
//   vendor-quarantine   — Failed validations get copied here for triage,
//                         plus a sidecar _REJECT_REASON.txt. 90-day delete.
//   vendor-deadletter   — Event Grid subscription dead-letters to this
//                         container when delivery fails after retries. No
//                         auto-delete; operator triages.
//
// DELIVERY CHANNEL — DUAL TRACK:
//   SFTP path: enable_sftp = true, ventra_sftp_public_key non-empty.
//              Adds a Ventra local user with home dir = vendor-inbound/ventra.
//   Snowflake-direct path: enable_sftp = false. Vendor writes via SAS token
//              against the same account (SAS generation is out-of-band; the
//              token is stored in KV by the deploy operator).
//
// The architecture supports either channel against the same downstream
// pipeline — see ADR-006 and Phase 1A.A3 of the plan.
//
// HIPAA-relevant defaults:
//   - allowBlobPublicAccess: false
//   - supportsHttpsTrafficOnly: true (SFTP uses SSH, not HTTP; this still
//     applies to all blob traffic and Snowflake-direct exports)
//   - minimumTlsVersion: TLS1_2
//   - infrastructure encryption (double encryption at rest)
//   - networkAcls.defaultAction: Deny with explicit allowlist
//
// What this module is NOT:
//   - Does not create the SAS token (out-of-band, KV-stored)
//   - Does not create the Event Grid subscription (vendor_eventgrid.bicep
//     in C6)
//   - Does not create the Container Apps Job (containerjobs.bicep in C7)
//   - Does not assign RBAC roles to the ingest job's Managed Identity
//     (rbac.bicep handles cross-resource role assignments)

@description('Vendor-storage account name. Convention: sthhavendor{env}{suffix}. Lowercase, alphanumeric only, 3-24 chars, globally unique.')
@minLength(3)
@maxLength(24)
param name string

@description('Azure region.')
param location string

@description('SKU. Standard_LRS for dev (cheap), Standard_ZRS for prod (zone-redundant — vendor drops cannot be replayed if lost).')
@allowed(['Standard_LRS', 'Standard_GRS', 'Standard_RAGRS', 'Standard_ZRS'])
param sku string = 'Standard_LRS'

@description('Blob soft-delete retention (days). 7 dev, 90 prod.')
@minValue(1)
@maxValue(365)
param soft_delete_retention_days int = 7

@description('Days after which vendor-inbound + vendor-quarantine blobs are auto-deleted. 0 disables. Default 90 = HIPAA audit retention window.')
@minValue(0)
@maxValue(365)
param vendor_lifecycle_delete_days int = 90

@description('Enable SFTP on the storage account. Adds a Ventra local user and SFTP service fee (~$220/mo). Leave false if the vendor uses Snowflake-direct via SAS token instead.')
param enable_sftp bool = false

@secure()
@description('Ventra SFTP public SSH key (full content of an OpenSSH-format public key file). Only used when enable_sftp is true. Rotated quarterly via KV.')
param ventra_sftp_public_key string = ''

@description('Deployer workstation IP for the network ACL allowlist. Only used in public-access mode.')
param deployer_workstation_ip string = ''

@description('Private-endpoint subnet resource ID. When non-empty, public access is fully disabled and all blob/SFTP traffic must go through the PE.')
param pe_subnet_id string = ''

@description('Tags applied to every resource.')
param tags object = {}

var private_mode = !empty(pe_subnet_id)
var sftp_ready = enable_sftp && !empty(ventra_sftp_public_key)

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
    allowSharedKeyAccess: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: private_mode ? 'Disabled' : 'Enabled'
    // HNS + SFTP both require create-time enablement. We turn HNS on
    // unconditionally so the storage account is SFTP-capable from day 1
    // even if SFTP isn't activated yet — flipping enable_sftp later costs
    // only the SFTP service fee, not a recreate.
    isHnsEnabled: true
    isSftpEnabled: enable_sftp
    encryption: {
      services: {
        blob: {
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

resource vendorInboundContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2024-01-01' = {
  parent: blobService
  name: 'vendor-inbound'
  properties: {
    publicAccess: 'None'
    metadata: {
      purpose: 'pre-aggregated-csvs-from-ventra-and-future-vendors'
      retention: '90-days-then-auto-delete-for-audit-window'
    }
  }
}

resource vendorQuarantineContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2024-01-01' = {
  parent: blobService
  name: 'vendor-quarantine'
  properties: {
    publicAccess: 'None'
    metadata: {
      purpose: 'failed-validation-drops-with-reject-reason-sidecar'
      retention: '90-days-then-auto-delete-after-triage'
    }
  }
}

resource vendorDeadletterContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2024-01-01' = {
  parent: blobService
  name: 'vendor-deadletter'
  properties: {
    publicAccess: 'None'
    metadata: {
      purpose: 'event-grid-deadletter-target-for-undeliverable-events'
      retention: 'no-auto-delete-operator-triages-manually'
    }
  }
}

// Lifecycle: auto-delete vendor-inbound + vendor-quarantine after
// vendor_lifecycle_delete_days. vendor-deadletter is excluded by design
// (operator-triage only).
resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2024-01-01' = if (vendor_lifecycle_delete_days > 0) {
  parent: storage
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'delete-vendor-inbound-after-N-days'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: [
                'blockBlob'
              ]
              prefixMatch: [
                'vendor-inbound/'
              ]
            }
            actions: {
              baseBlob: {
                delete: {
                  daysAfterModificationGreaterThan: vendor_lifecycle_delete_days
                }
              }
            }
          }
        }
        {
          name: 'delete-vendor-quarantine-after-N-days'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: [
                'blockBlob'
              ]
              prefixMatch: [
                'vendor-quarantine/'
              ]
            }
            actions: {
              baseBlob: {
                delete: {
                  daysAfterModificationGreaterThan: vendor_lifecycle_delete_days
                }
              }
            }
          }
        }
      ]
    }
  }
}

// Ventra SFTP local user — only provisioned when enable_sftp AND public key
// is supplied. Scope is strictly the home directory; rwcd within it, no
// access to vendor-quarantine or vendor-deadletter.
resource ventraSftpUser 'Microsoft.Storage/storageAccounts/localUsers@2024-01-01' = if (sftp_ready) {
  parent: storage
  name: 'ventra'
  properties: {
    homeDirectory: 'vendor-inbound/ventra'
    sshAuthorizedKeys: [
      {
        description: 'Ventra production SFTP key — rotate quarterly via KV'
        key: ventra_sftp_public_key
      }
    ]
    permissionScopes: [
      {
        permissions: 'rwcd'
        service: 'blob'
        resourceName: 'vendor-inbound'
      }
    ]
    hasSshPassword: false
    hasSharedKey: false
  }
}

@description('Vendor-storage account resource ID.')
output storage_id string = storage.id

@description('Vendor-storage account name.')
output storage_name string = storage.name

@description('Blob endpoint primary URL — Container Apps Job reads vendor drops from here.')
output blob_endpoint string = storage.properties.primaryEndpoints.blob

@description('SFTP endpoint primary URL — only meaningful when enable_sftp is true. Ventra connects to this hostname:22 with the local-user credentials.')
output sftp_endpoint string = enable_sftp ? '${storage.name}.blob.${environment().suffixes.storage}' : ''

@description('vendor-inbound container name.')
output vendor_inbound_container_name string = vendorInboundContainer.name

@description('vendor-quarantine container name.')
output vendor_quarantine_container_name string = vendorQuarantineContainer.name

@description('vendor-deadletter container name (Event Grid DLQ target).')
output vendor_deadletter_container_name string = vendorDeadletterContainer.name
