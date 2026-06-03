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
@description('Ventra SFTP public SSH key (full content of an OpenSSH-format public key file). Only used when enable_sftp is true. Rotated quarterly via KV. NOTE: this is the legacy single-user key from PR #54; the hybrid pipeline (Phase 4) uses ventra_stdspec_sftp_public_key + ventra_preagg_sftp_public_key instead. The legacy user stays for backward compatibility until the cutover in H14.')
param ventra_sftp_public_key string = ''

@description('Phase 4 hybrid — enable the row-level Standard Spec SFTP user. This is the PHI-bearing path; provision only when Ventra is ready to push and the V15 denylist + PHI-safety infrastructure is deployed. Creates the ventra-stdspec local user with homeDirectory = vendor-inbound/ventra/stdspec.')
param enable_ventra_stdspec bool = false

@secure()
@description('Phase 4 hybrid — Ventra SSH public key for the stdspec (row-level / PHI-bearing) SFTP user. Separate from ventra_sftp_public_key by design: rotated independently, scoped strictly to vendor-inbound/ventra/stdspec/, and key compromise of the stdspec path does NOT expose the preagg path. Stored in KV as ventra-stdspec-sftp-public-key.')
param ventra_stdspec_sftp_public_key string = ''

@description('Days after which blobs under vendor-inbound/ventra/stdspec/ auto-delete. Defaults to 30 (vs 90 for preagg) — PHI minimization per ADR-001. 0 disables.')
@minValue(0)
@maxValue(90)
param vendor_stdspec_lifecycle_delete_days int = 30

@description('Phase 4 hybrid — enable the pre-aggregated SFTP user. The pre-Phase-4 single ``ventra`` user stays for backward compatibility until H14 cuts the pre-agg pipeline over to this dedicated user. Setting both true is intentional during the transition window. Creates the ventra-preagg local user with homeDirectory = vendor-inbound/ventra/preagg.')
param enable_ventra_preagg bool = false

@secure()
@description('Phase 4 hybrid — Ventra SSH public key for the preagg (pre-aggregated / no-PHI) SFTP user. Separate from ventra_stdspec_sftp_public_key so the two paths can be rotated independently and a key leak on one path does not compromise the other. Stored in KV as ventra-preagg-sftp-public-key.')
param ventra_preagg_sftp_public_key string = ''

@description('Deployer workstation IP for the network ACL allowlist. Only used in public-access mode.')
param deployer_workstation_ip string = ''

@description('Private-endpoint subnet resource ID. When non-empty, public access is fully disabled and all blob/SFTP traffic must go through the PE.')
param pe_subnet_id string = ''

@description('Tags applied to every resource.')
param tags object = {}

var private_mode = !empty(pe_subnet_id)
var sftp_ready = enable_sftp && !empty(ventra_sftp_public_key)
// Phase 4 hybrid — stdspec user requires (a) SFTP service on, (b) the toggle
// flipped, and (c) Ventra's public key supplied. Any missing piece skips the
// local-user resource — Bicep ``if (...)`` resolves at compile-time.
var stdspec_ready = enable_sftp && enable_ventra_stdspec && !empty(ventra_stdspec_sftp_public_key)
// Phase 4 hybrid — preagg user gated symmetrically. Both stdspec_ready and
// preagg_ready can be true at the same time (intentional during the dual-run
// reconciliation window) — they own distinct home directories so they never
// collide on a path.
var preagg_ready = enable_sftp && enable_ventra_preagg && !empty(ventra_preagg_sftp_public_key)

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

// Lifecycle: auto-delete vendor-inbound + vendor-quarantine after their
// respective retention windows. vendor-deadletter is excluded by design
// (operator-triage only).
//
// Three rules:
//   1. delete-vendor-stdspec-after-N-days  — narrowest prefix; runs FIRST
//      so PHI-bearing rows land their 30-day window before the broader
//      90-day rule would apply. Lifecycle policies evaluate rules in
//      definition order; longest-prefix-wins is NOT automatic.
//   2. delete-vendor-inbound-after-N-days  — broader; catches preagg and
//      anything Ventra writes outside the stdspec subtree.
//   3. delete-vendor-quarantine-after-N-days — quarantine triage window.
resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2024-01-01' = if (vendor_lifecycle_delete_days > 0) {
  parent: storage
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'delete-vendor-stdspec-after-N-days'
          enabled: vendor_stdspec_lifecycle_delete_days > 0
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: [
                'blockBlob'
              ]
              prefixMatch: [
                'vendor-inbound/ventra/stdspec/'
              ]
            }
            actions: {
              baseBlob: {
                delete: {
                  daysAfterModificationGreaterThan: vendor_stdspec_lifecycle_delete_days
                }
              }
            }
          }
        }
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
//
// LEGACY (pre-Phase-4): single user 'ventra' with home dir vendor-inbound/ventra.
// Stays for backward compatibility until H14 cuts the pre-agg pipeline over to
// the dedicated 'ventra-preagg' user.
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

// Phase 4 hybrid — Ventra Standard-Spec SFTP local user.
//
// Threat model deltas vs the legacy 'ventra' user:
//   - PHI bearer: Ventra writes row-level Invoice + Guarantor CSVs here.
//   - Key compromise containment: separate SSH key from preagg path, so a
//     key leak only affects the row-level inbound — preagg keeps running.
//   - Scope: strictly vendor-inbound/ventra/stdspec/<YYYY-MM-DD>/. The
//     homeDirectory pins it; the permissionScope on vendor-inbound is the
//     full container but the user's path resolution is rooted at the home
//     dir, so they cannot list or write outside it via standard SFTP clients.
//   - Retention: covered by a 30-day lifecycle rule below (vs 90-day for
//     the rest of vendor-inbound) — PHI minimization per ADR-001.
//
// The Container App Job processing this user's drops (caj-ventra-ingest-stdspec,
// added in H5) strips PHI before any column reaches the DB. Raw blobs land
// here, get aggregated in-memory by the job, then auto-delete on day 30.
resource ventraStdspecSftpUser 'Microsoft.Storage/storageAccounts/localUsers@2024-01-01' = if (stdspec_ready) {
  parent: storage
  name: 'ventra-stdspec'
  properties: {
    homeDirectory: 'vendor-inbound/ventra/stdspec'
    sshAuthorizedKeys: [
      {
        description: 'Ventra Standard-Spec (row-level / PHI) SFTP key — rotate quarterly via KV; separate from ventra-preagg key by design'
        key: ventra_stdspec_sftp_public_key
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

// Phase 4 hybrid — Ventra pre-aggregated SFTP local user.
//
// Mirrors the legacy 'ventra' user from PR #54 but with a dedicated home
// directory and SSH key. Reasons to add this user instead of just renaming:
//   - Co-existence with the legacy user during the transition window. H14
//     cuts the pre-agg pipeline over to this user; deleting the legacy user
//     happens AFTER Ventra confirms they've switched their config.
//   - SSH key isolation from the stdspec path — key rotation of one user
//     does not require coordinating with the other.
//
// No PHI on this path (Ventra aggregates at source per ADR-006), so the
// retention follows the standard 90-day vendor-inbound lifecycle rule
// (handled by the broad ``delete-vendor-inbound-after-N-days`` rule below;
// no separate lifecycle override needed).
resource ventraPreaggSftpUser 'Microsoft.Storage/storageAccounts/localUsers@2024-01-01' = if (preagg_ready) {
  parent: storage
  name: 'ventra-preagg'
  properties: {
    homeDirectory: 'vendor-inbound/ventra/preagg'
    sshAuthorizedKeys: [
      {
        description: 'Ventra pre-aggregated (no-PHI) SFTP key — rotate quarterly via KV; separate from ventra-stdspec key by design'
        key: ventra_preagg_sftp_public_key
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

@description('Phase 4 hybrid — full SFTP connection string for the Ventra Standard-Spec (row-level) user. Empty when stdspec is disabled. Pass this to Ventra via secure channel.')
output ventra_stdspec_sftp_connection string = stdspec_ready ? '${storage.name}.${storage.name}.blob.${environment().suffixes.storage}:22 (user: ventra-stdspec, path: /vendor-inbound/ventra/stdspec/)' : ''

@description('Phase 4 hybrid — whether the stdspec local user was provisioned in this deployment. Downstream modules gate their own provisioning on this.')
output stdspec_ready bool = stdspec_ready

@description('Phase 4 hybrid — full SFTP connection string for the Ventra pre-aggregated user. Empty when preagg is disabled. Pass this to Ventra via secure channel.')
output ventra_preagg_sftp_connection string = preagg_ready ? '${storage.name}.${storage.name}.blob.${environment().suffixes.storage}:22 (user: ventra-preagg, path: /vendor-inbound/ventra/preagg/)' : ''

@description('Phase 4 hybrid — whether the preagg local user was provisioned in this deployment. Downstream modules (Event Grid filter, Container App Job) gate on this.')
output preagg_ready bool = preagg_ready

@description('vendor-inbound container name.')
output vendor_inbound_container_name string = vendorInboundContainer.name

@description('vendor-quarantine container name.')
output vendor_quarantine_container_name string = vendorQuarantineContainer.name

@description('vendor-deadletter container name (Event Grid DLQ target).')
output vendor_deadletter_container_name string = vendorDeadletterContainer.name
