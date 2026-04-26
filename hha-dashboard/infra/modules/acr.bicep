// Azure Container Registry — hosts the cron job images.
//
// What lives here:
//   acrhha{env}.azurecr.io/pg-backup:<tag>
//   acrhha{env}.azurecr.io/alert-digest:<tag>
//   acrhha{env}.azurecr.io/cred-scan:<tag>
//   acrhha{env}.azurecr.io/paycom-sync:<tag>     (when API access lands)
//   acrhha{env}.azurecr.io/ventra-ingest:<tag>   (when Ventra delivery confirmed)
//   acrhha{env}.azurecr.io/upload-ingest:<tag>
//
// Auth model:
//   - Pull: Container Apps Job MIs use AcrPull role assignment (rbac.bicep).
//   - Push: GitHub Actions deploy workflow uses an `az acr login` against
//           OIDC-federated identity. No admin user, no static credentials.
//
// SKU notes:
//   - dev: Basic (cheapest, ~$5/mo, 10GB storage)
//   - prod: Standard ($20/mo, 100GB, geo-replication-capable)
//   - Premium ($100+/mo) only needed for content trust signing or VNet
//     integration; we'll add when compliance asks. Current network rules
//     are public-with-Azure-Services-bypass — sufficient when push is
//     done by a federated identity with limited blast radius.
//
// Image lifecycle:
//   - Cleanup task: monthly purge of untagged manifests + tags older than
//     30 days. Implemented via `az acr task` post-deploy, not in Bicep.

@description('Registry name. Convention: acrhha{env}. Globally unique; ACR rejects names with hyphens.')
@minLength(5)
@maxLength(50)
param acr_name string

@description('Azure region.')
param location string

@description('SKU. Basic = $5/mo dev. Standard = $20/mo prod with replication option.')
@allowed(['Basic', 'Standard', 'Premium'])
param sku string = 'Basic'

@description('Tags applied to every resource.')
param tags object = {}

resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: acr_name
  location: location
  tags: tags
  sku: {
    name: sku
  }
  properties: {
    // No admin user — ACR auth is OIDC + RBAC only.
    adminUserEnabled: false
    // Default soft-delete retention — gives 7-day grace period if a
    // tag is deleted by mistake.
    policies: {
      softDeletePolicy: {
        retentionDays: 7
        status: 'enabled'
      }
      // Prevent untagged manifests from accumulating storage cost.
      // Manifests deleted automatically when the only reference is dropped.
      retentionPolicy: {
        days: 30
        status: 'enabled'
      }
      // Trust + scanning — Premium only, would require SKU bump
      // when compliance asks. Currently null defaults.
    }
    // publicNetworkAccess: 'Enabled' is the default. Container Apps Jobs
    // can reach ACR over the Azure backbone without VNet integration on
    // either side. When we move ACR behind a private endpoint, that's
    // a Premium-SKU + vnet.bicep extension.
  }
}

@description('Registry resource ID — used by rbac.bicep for AcrPull role assignments.')
output acr_id string = registry.id

@description('Login server — e.g. acrhhaprod.azurecr.io. Used in containerjobs.bicep image params.')
output login_server string = registry.properties.loginServer

@description('Registry name — needed by az acr push commands in deploy workflows.')
output registry_name string = registry.name
