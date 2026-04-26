// VNet + 3 subnets + 2 private DNS zones for the prod posture.
//
// Subnet layout (10.20.0.0/16):
//   10.20.1.0/24  app                — delegated to Microsoft.Web/serverFarms
//                                       (App Service VNet integration in Session 10)
//   10.20.2.0/24  postgres           — delegated to Microsoft.DBforPostgreSQL/flexibleServers
//                                       (server NIC lives here via VNet injection)
//   10.20.3.0/24  private-endpoints  — no delegation, privateEndpointNetworkPolicies: Disabled
//                                       (KV PE attaches here; future PEs join too)
//
// Private DNS zones (linked to this VNet):
//   privatelink.postgres.database.azure.com  — auto-populated by the Postgres injection
//   privatelink.vaultcore.azure.net          — populated by KV's privateDnsZoneGroup
//
// NOT in this module (deferred):
//   - NSGs (subnets are private, default-deny isn't required for v0)
//   - VNet peering (single-region, single-environment for now)
//   - Diagnostic settings / flow logs (lands with monitor.bicep, Session 11)

@description('VNet name. Convention: vnet-hha-{env}.')
param name string

@description('Azure region. Must match the resource group.')
param location string

@description('Address space for the VNet. Default 10.20.0.0/16 per the architecture diagram.')
param address_prefix string = '10.20.0.0/16'

@description('App subnet CIDR. Delegated to App Service.')
param app_subnet_prefix string = '10.20.1.0/24'

@description('Postgres subnet CIDR. Delegated to Flex Server.')
param postgres_subnet_prefix string = '10.20.2.0/24'

@description('Private endpoints subnet CIDR.')
param pe_subnet_prefix string = '10.20.3.0/24'

@description('Tags to apply to every resource in this module.')
param tags object = {}

resource vnet 'Microsoft.Network/virtualNetworks@2024-01-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        address_prefix
      ]
    }
    subnets: [
      {
        name: 'app'
        properties: {
          addressPrefix: app_subnet_prefix
          delegations: [
            {
              name: 'app-service-delegation'
              properties: {
                serviceName: 'Microsoft.Web/serverFarms'
              }
            }
          ]
          // No PE policy override needed here — app subnet doesn't host PEs.
        }
      }
      {
        name: 'postgres'
        properties: {
          addressPrefix: postgres_subnet_prefix
          delegations: [
            {
              name: 'postgres-flex-delegation'
              properties: {
                serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers'
              }
            }
          ]
        }
      }
      {
        name: 'private-endpoints'
        properties: {
          addressPrefix: pe_subnet_prefix
          // Required so PE NICs can attach; without this, deployment errors.
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
    ]
  }
}

// ---------------------------------------------------------------------------
// Private DNS zones — one per privatelink-aware service we use.
// Subscription-level resources, but in Bicep we treat them as RG-scoped.
// ---------------------------------------------------------------------------

resource pgDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.postgres.database.azure.com'
  location: 'global'
  tags: tags
}

resource kvDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.vaultcore.azure.net'
  location: 'global'
  tags: tags
}

// ---------------------------------------------------------------------------
// VNet links — let A records inside the zones resolve from this VNet.
// ---------------------------------------------------------------------------

resource pgDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: pgDnsZone
  name: '${name}-link'
  location: 'global'
  tags: tags
  properties: {
    virtualNetwork: {
      id: vnet.id
    }
    registrationEnabled: false
  }
}

resource kvDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: kvDnsZone
  name: '${name}-link'
  location: 'global'
  tags: tags
  properties: {
    virtualNetwork: {
      id: vnet.id
    }
    registrationEnabled: false
  }
}

@description('VNet resource ID — passed to App Service VNet integration in Session 10.')
output vnet_id string = vnet.id

@description('App subnet resource ID.')
output app_subnet_id string = '${vnet.id}/subnets/app'

@description('Postgres subnet resource ID. Pass to postgres.bicep delegated_subnet_id.')
output postgres_subnet_id string = '${vnet.id}/subnets/postgres'

@description('Private-endpoints subnet ID. Pass to keyvault.bicep pe_subnet_id.')
output pe_subnet_id string = '${vnet.id}/subnets/private-endpoints'

@description('Postgres private DNS zone ID. Pass to postgres.bicep private_dns_zone_id.')
output pg_dns_zone_id string = pgDnsZone.id

@description('Key Vault private DNS zone ID. Pass to keyvault.bicep dns_zone_id.')
output kv_dns_zone_id string = kvDnsZone.id
