// Key Vault module — HIPAA-conscious defaults.
//
// Permission model: RBAC only. No legacy access policies.
//   - App Service managed identities get `Key Vault Secrets User` via main.bicep
//   - Deployer (operator running az deployment) needs Key Vault Secrets Officer
//     to write the initial secrets via bootstrap.sh (Session 10)
//
// Network: when pe_subnet_id is provided, this module creates a private
// endpoint + DNS zone group, sets publicNetworkAccess: Disabled, and the
// vault is reachable only from inside the VNet. When pe_subnet_id is empty,
// the vault stays public (gated by network ACLs default-deny + IP allowlist
// from deployer_workstation_ip) — useful for dev where VNet costs are
// avoided.
//
// What this module is NOT (deferred):
//   - CMK / key rotation policy (for Postgres/Storage data-at-rest CMK)
//     → keys can be added later as child resources
//   - Diagnostic settings → Log Analytics (lands with monitor.bicep)
//   - Initial secret seeding (Postgres password etc.) → bootstrap.sh in Session 10

@description('Vault name. Convention: kv-hha-{env}. Must be globally unique, 3-24 chars, alphanumeric + hyphens.')
@minLength(3)
@maxLength(24)
param name string

@description('Azure region.')
param location string

@description('Tenant ID. KV requires this even when using RBAC.')
param tenant_id string

@description('Soft-delete retention in days. Min 7, max 90. 90 is the HIPAA-friendlier default.')
@minValue(7)
@maxValue(90)
param soft_delete_retention_days int = 90

@description('Enable purge protection. WARNING: this is a one-way switch — once true, you cannot disable it on this vault. Default true (HIPAA-friendlier). Set false on first deploy if you expect botched deploys to soft-delete-lock the name.')
param enable_purge_protection bool = true

@description('Workstation IP for the network ACL allowlist. Used only when pe_subnet_id is empty (no private endpoint).')
param deployer_workstation_ip string = ''

@description('Private-endpoints subnet ID. When non-empty, creates a PE and disables public access.')
param pe_subnet_id string = ''

@description('Private DNS zone ID for privatelink.vaultcore.azure.net. Required when pe_subnet_id is non-empty.')
param dns_zone_id string = ''

@description('Tags applied to every resource in this module.')
param tags object = {}

var private_mode = !empty(pe_subnet_id)

resource vault 'Microsoft.KeyVault/vaults@2024-04-01-preview' = {
  name: name
  location: location
  tags: tags
  properties: {
    tenantId: tenant_id
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: soft_delete_retention_days
    enablePurgeProtection: enable_purge_protection ? true : null
    enabledForDeployment: false
    enabledForDiskEncryption: false
    enabledForTemplateDeployment: false
    publicNetworkAccess: private_mode ? 'Disabled' : 'Enabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      ipRules: empty(deployer_workstation_ip) ? [] : [
        {
          value: deployer_workstation_ip
        }
      ]
      virtualNetworkRules: []
    }
  }
}

// ---------------------------------------------------------------------------
// Private endpoint (only when a PE subnet is supplied).
// ---------------------------------------------------------------------------

resource pe 'Microsoft.Network/privateEndpoints@2024-01-01' = if (private_mode) {
  name: 'pe-${name}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: pe_subnet_id
    }
    privateLinkServiceConnections: [
      {
        name: 'plsc-${name}'
        properties: {
          privateLinkServiceId: vault.id
          groupIds: [
            'vault'
          ]
        }
      }
    ]
  }
}

// DNS zone group — ties the PE NIC's IP to an A record in the privatelink
// zone, which the VNet link resolves for callers inside the VNet.
resource peDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-01-01' = if (private_mode) {
  parent: pe
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-vaultcore-azure-net'
        properties: {
          privateDnsZoneId: dns_zone_id
        }
      }
    ]
  }
}

@description('Vault resource ID. Used by main.bicep for RBAC role assignments.')
output vault_id string = vault.id

@description('Vault URI for app_settings KV references — the privatelink-aware URI the platform exposes.')
output vault_uri string = vault.properties.vaultUri

@description('Vault name (passed through for symmetry).')
output vault_name string = vault.name
