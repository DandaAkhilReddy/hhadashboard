// App Service Plan + 2 Linux App Services (web + api).
//
// HIPAA-relevant defaults:
//   - httpsOnly: true on both apps
//   - minTlsVersion: 1.2
//   - ftpsState: Disabled (no FTP at all)
//   - System-assigned managed identity (for future Key Vault references)
//   - healthCheckPath wired (FastAPI /health, Next.js /)
//
// Known limitation (documented in the plan): both apps share one App Service
// Plan. In prod (P1v3, 2 instances) they noisy-neighbor each other on scale
// events. Splitting into two plans is a one-line change later.

@description('App Service Plan name. Convention: plan-hha-{env}.')
param plan_name string

@description('Web app name. Convention: app-hha-web-{env}.')
param web_name string

@description('API app name. Convention: app-hha-api-{env}.')
param api_name string

@description('Azure region.')
param location string

@description('Plan SKU: B2 (dev), P1v3 (prod).')
param plan_sku_name string

@description('Plan SKU tier: Basic (dev), PremiumV3 (prod).')
@allowed(['Basic', 'Standard', 'PremiumV2', 'PremiumV3'])
param plan_sku_tier string

@description('Worker count. 1 (dev), 2 (prod).')
@minValue(1)
param worker_count int

@description('Linux runtime stack for the API. e.g. PYTHON|3.12.')
param api_linux_fx_version string = 'PYTHON|3.12'

@description('Linux runtime stack for the web app. e.g. NODE|20-lts.')
param web_linux_fx_version string = 'NODE|20-lts'

@description('App settings for the web app (Next.js).')
param app_settings_web object

@description('App settings for the api app (FastAPI).')
param app_settings_api object

@description('Optional app subnet resource ID for regional VNet integration. When set, both apps attach to the subnet so outbound traffic (Postgres, Key Vault) flows through the VNet. Empty string keeps them on the public outbound IP set.')
param app_subnet_id string = ''

@description('Tags to apply to all resources.')
param tags object = {}

var vnet_integrated = !empty(app_subnet_id)

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: plan_name
  location: location
  tags: tags
  sku: {
    name: plan_sku_name
    tier: plan_sku_tier
    capacity: worker_count
  }
  kind: 'linux'
  properties: {
    reserved: true // required for Linux
    zoneRedundant: false
  }
}

// Convert {key: value} app_settings object into the [{name, value}] form
// the platform expects.
var web_settings_array = [for k in items(app_settings_web): {
  name: k.key
  value: k.value
}]

var api_settings_array = [for k in items(app_settings_api): {
  name: k.key
  value: k.value
}]

resource web 'Microsoft.Web/sites@2024-04-01' = {
  name: web_name
  location: location
  tags: tags
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    clientAffinityEnabled: false
    virtualNetworkSubnetId: vnet_integrated ? app_subnet_id : null
    siteConfig: {
      linuxFxVersion: web_linux_fx_version
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      http20Enabled: true
      alwaysOn: true
      healthCheckPath: '/'
      vnetRouteAllEnabled: vnet_integrated
      appSettings: web_settings_array
    }
  }
}

resource api 'Microsoft.Web/sites@2024-04-01' = {
  name: api_name
  location: location
  tags: tags
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    clientAffinityEnabled: false
    virtualNetworkSubnetId: vnet_integrated ? app_subnet_id : null
    siteConfig: {
      linuxFxVersion: api_linux_fx_version
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      http20Enabled: true
      alwaysOn: true
      healthCheckPath: '/health'
      vnetRouteAllEnabled: vnet_integrated
      appSettings: api_settings_array
    }
  }
}

// Regional VNet integration: when an app subnet is provided, attach via the
// virtualNetwork subresource. This is the modern approach replacing the
// legacy Microsoft.Web/sites/networkConfig where possible. We use the
// virtualNetworkSubnetId top-level property above; the subresource below is
// kept conditional and explicit for the cases where the platform expects it.
//
// When app_subnet_id is empty, neither apps gets VNet integration —
// outbound traffic continues through the public outbound IP set.

@description('Web app default hostname.')
output web_hostname string = web.properties.defaultHostName

@description('API app default hostname.')
output api_hostname string = api.properties.defaultHostName

@description('Web app outbound IP set (newline-separated). Useful for downstream firewall rules.')
output web_outbound_ips string = web.properties.outboundIpAddresses

@description('API app outbound IP set (newline-separated). Useful for Postgres firewall rules.')
output api_outbound_ips string = api.properties.outboundIpAddresses

@description('Web app principal ID (managed identity).')
output web_principal_id string = web.identity.principalId

@description('API app principal ID (managed identity).')
output api_principal_id string = api.identity.principalId

@description('App Service Plan resource ID.')
output plan_id string = plan.id
