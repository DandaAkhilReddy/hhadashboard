// Postgres Flexible Server module — HIPAA-conscious defaults.
//
// What this module is NOT (deferred to Session 9+):
//   - VNet integration / private endpoint (publicNetworkAccess stays Enabled
//     here, gated by a tight firewall allowlist instead)
//   - Customer-managed key (CMK) encryption — using platform-managed keys
//   - Diagnostic settings → Log Analytics (lands with monitor.bicep)
//
// Outputs deliberately exclude the connection string and password — main.bicep
// composes the connection strings inline to keep secrets out of deployment
// outputs (which are visible to anyone with Reader on the resource group).

@description('Resource name. Convention: psql-hha-{env}.')
param name string

@description('Azure region.')
param location string

@description('SKU name, e.g. Standard_B2ms (dev), Standard_D2ds_v5 (prod).')
param sku_name string

@description('SKU tier: Burstable (dev) or GeneralPurpose (prod).')
@allowed(['Burstable', 'GeneralPurpose', 'MemoryOptimized'])
param sku_tier string

@description('Storage size in GB. Min 32 for Flex Server.')
@minValue(32)
param storage_gb int = 32

@description('Backup retention in days. 7 (dev) to 35 (max for Flex Server).')
@minValue(7)
@maxValue(35)
param backup_retention_days int

@description('Geo-redundant backup. Enable in prod.')
@allowed(['Enabled', 'Disabled'])
param geo_redundant_backup string

@description('High-availability mode. ZoneRedundant in prod, Disabled in dev.')
@allowed(['ZoneRedundant', 'SameZone', 'Disabled'])
param ha_mode string

@description('Postgres admin login. Cannot be "admin", "azure_superuser", or other reserved names.')
param admin_login string

@secure()
@description('Postgres admin password. Supplied at deploy time, never persisted.')
param admin_password string

@description('Logical database to create on the server. Matches docker-compose.')
param database_name string = 'hha_dashboard'

@description('Deployer workstation IP for the firewall allowlist. Only used in public mode (when delegated_subnet_id is empty). No 0.0.0.0 rule is created.')
param deployer_workstation_ip string

@description('Delegated subnet resource ID for VNet injection. When non-empty, the server gets a private NIC in this subnet and publicNetworkAccess flips to Disabled. When empty, the server stays public with the deployer firewall rule (Session 8 behavior).')
param delegated_subnet_id string = ''

@description('Private DNS zone resource ID for privatelink.postgres.database.azure.com. Required when delegated_subnet_id is non-empty.')
param private_dns_zone_id string = ''

@description('Tags to apply to the server.')
param tags object = {}

var private_mode = !empty(delegated_subnet_id)

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: sku_name
    tier: sku_tier
  }
  properties: {
    version: '16'
    administratorLogin: admin_login
    administratorLoginPassword: admin_password
    storage: {
      storageSizeGB: storage_gb
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: backup_retention_days
      geoRedundantBackup: geo_redundant_backup
    }
    highAvailability: {
      mode: ha_mode
    }
    network: private_mode ? {
      publicNetworkAccess: 'Disabled'
      delegatedSubnetResourceId: delegated_subnet_id
      privateDnsZoneArmResourceId: private_dns_zone_id
    } : {
      publicNetworkAccess: 'Enabled'
    }
    authConfig: {
      passwordAuth: 'Enabled'
      activeDirectoryAuth: 'Disabled'
    }
  }
}

// Enforce TLS 1.2+ via server parameter (the Flex Server property is exposed
// as a configuration knob, not a top-level field).
resource sslMinTls 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: server
  name: 'ssl_min_protocol_version'
  properties: {
    value: 'TLSv1.2'
    source: 'user-override'
  }
}

resource db 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: server
  name: database_name
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

// Single firewall rule for the deployer workstation. Only created in public
// mode — VNet injection has no notion of public IP allowlists. The App
// Service outbound IP allowlist is added by main.bicep after appservice
// deploys (deferred-output pattern documented in infra/README.md).
resource fwDeployer 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = if (!private_mode) {
  parent: server
  name: 'deployer-workstation'
  properties: {
    startIpAddress: deployer_workstation_ip
    endIpAddress: deployer_workstation_ip
  }
}

@description('Server FQDN — main.bicep composes the connection string from this.')
output host string = server.properties.fullyQualifiedDomainName

@description('Database name — passed through for symmetry.')
output database_name string = db.name

@description('Server resource ID — useful for diagnostic-settings wiring later.')
output server_resource_id string = server.id

@description('Server name — useful when downstream firewall rules are added by the orchestrator.')
output server_name string = server.name
