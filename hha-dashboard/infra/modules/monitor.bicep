// Log Analytics workspace + Application Insights — observability foundation.
//
// HIPAA notes:
//   - Diagnostic settings on every audited resource (Postgres, App Service,
//     Key Vault, Storage) flow into this workspace
//   - Workspace retention is 30 days dev / 90 days prod (HHA's HIPAA audit
//     retention is 6+ years for the audit_log TABLE in Postgres — that's a
//     separate retention concern, handled at the database level)
//   - PII-scrubbing happens upstream in `app/core/logging.py` (structlog
//     processor). Workspace ingests already-scrubbed entries
//
// What this module is NOT (deferred):
//   - Diagnostic Settings on individual resources (those are wired in
//     main.bicep to keep the dependency direction clean: each resource
//     depends on the workspace, not the workspace on each resource)
//   - Action Groups / alert rules (Session 13+; needs business sign-off
//     on thresholds)
//   - Workbooks / saved KQL queries (post-launch polish)

@description('Log Analytics workspace name. Convention: log-hha-{env}.')
param log_analytics_name string

@description('Application Insights name. Convention: appi-hha-{env}.')
param app_insights_name string

@description('Azure region.')
param location string

@description('Workspace retention in days. 30 dev, 90 prod. HIPAA technical-records retention runs longer in Postgres; this is the operational-log window.')
@minValue(30)
@maxValue(730)
param retention_days int = 30

@description('Workspace SKU. PerGB2018 is the modern standard tier.')
@allowed(['PerGB2018', 'CapacityReservation', 'Free', 'Standalone', 'Standard', 'Premium', 'PerNode'])
param sku string = 'PerGB2018'

@description('Daily ingestion cap in GB to bound runaway log costs. -1 disables the cap.')
param daily_quota_gb int = -1

@description('Tags applied to every resource.')
param tags object = {}

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: log_analytics_name
  location: location
  tags: tags
  properties: {
    sku: {
      name: sku
    }
    retentionInDays: retention_days
    workspaceCapping: daily_quota_gb >= 0 ? {
      dailyQuotaGb: daily_quota_gb
    } : null
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: app_insights_name
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    IngestionMode: 'LogAnalytics'
    DisableIpMasking: false // mask client IPs by default
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

@description('Log Analytics workspace resource ID — used as targetWorkspaceId on each Diagnostic Setting.')
output workspace_id string = workspace.id

@description('Workspace customer ID (GUID) — for diagnostic-settings configurations that want the customer key, not the ARM ID.')
output workspace_customer_id string = workspace.properties.customerId

@description('Application Insights instrumentation key. Older SDKs still use this; modern SDKs prefer the connection string.')
output app_insights_instrumentation_key string = appInsights.properties.InstrumentationKey

@description('Application Insights connection string. Wire into api app_settings as APPLICATIONINSIGHTS_CONNECTION_STRING.')
output app_insights_connection_string string = appInsights.properties.ConnectionString

@description('Application Insights resource ID — for cross-resource references (e.g., metric alerts).')
output app_insights_id string = appInsights.id
