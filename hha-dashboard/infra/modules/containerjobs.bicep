// Container Apps environment + one example scheduled Job.
//
// Hosts the cron jobs documented in DASHBOARD_PLAN.md:
//   pg_backup       — nightly pg_dump → backups/ container
//   paycom_sync     — workforce data ingest (4-6 weeks gated on Paycom API)
//   ventra_ingest   — FL collections + AR aging (gated on Ventra BAA)
//   alert_digest    — 7am exec digest via ACS Email
//   cred_scan       — credential expiry alerts
//
// This module ships the *infrastructure* — the environment + one
// pg_backup job template using a placeholder image. The actual job
// images (pushed to a future Azure Container Registry) replace the
// placeholder via parameter override at deploy time. Other jobs land
// as additional `Microsoft.App/jobs` resources in follow-up PRs.
//
// What this module is NOT (deferred):
//   - VNet integration on the env (Container Apps needs /23+ subnet;
//     vnet.bicep currently has /24 subnets — adjust separately)
//   - Azure Container Registry (separate `acr.bicep` module when needed)
//   - The other 4 cron jobs (paycom, ventra, alert_digest, cred_scan)
//   - Job-level RBAC role assignments (each job's MI needs different
//     scopes — KV Secrets User for paycom_sync, Storage Blob Data
//     Contributor for pg_backup, etc.)

@description('Container Apps environment name. Convention: cae-hha-{env}.')
param env_name_prefix string

@description('Azure region.')
param location string

@description('Log Analytics customer ID (the GUID from monitor.outputs.workspace_customer_id). Pair with shared_key for env appLogsConfiguration. Empty string disables log forwarding.')
param log_analytics_customer_id string = ''

@secure()
@description('Log Analytics workspace shared key. Required by Container Apps env logging config (separate from the workspace ID itself).')
param log_analytics_shared_key string = ''

@description('Container image for the example pg_backup job. Default is a Microsoft sample; replace with a real image (e.g. acrhhaprod.azurecr.io/pg-backup:1.0) once a registry exists.')
param pg_backup_image string = 'mcr.microsoft.com/k8se/quickstart-jobs:latest'

@description('Cron expression for pg_backup. Default: 03:00 UTC daily.')
param pg_backup_schedule string = '0 3 * * *'

@description('Container image for alert_digest job. Default is the placeholder; replace with the registry-pushed image once ACR is wired (e.g. acrhhaprod.azurecr.io/alert-digest:1.0).')
param alert_digest_image string = 'mcr.microsoft.com/k8se/quickstart-jobs:latest'

@description('Cron expression for alert_digest. Default: 11:00 UTC weekdays (≈07:00 ET).')
param alert_digest_schedule string = '0 11 * * 1-5'

@description('Container image for cred_scan job.')
param cred_scan_image string = 'mcr.microsoft.com/k8se/quickstart-jobs:latest'

@description('Cron expression for cred_scan. Default: 12:00 UTC daily.')
param cred_scan_schedule string = '0 12 * * *'

@description('Master switch — turn on alert_digest + cred_scan jobs. Both gate independently on this AND enable_email being passed through (jobs no-op without ACS env).')
param enable_alert_jobs bool = false

@description('ACS endpoint URL. Required by alert_digest + cred_scan to send. Empty string disables those jobs at the env-var level (the cron will exit cleanly with "Email not configured").')
param azure_communication_endpoint string = ''

@description('ACS sender address (DoNotReply@<azurecomm>).')
param azure_communication_sender string = ''

@description('Async DATABASE_URL passed to alert_digest + cred_scan. KV reference in prod (full @Microsoft.KeyVault(...) string), literal in dev.')
@secure()
param database_url string = ''

@description('Tags applied to every resource.')
param tags object = {}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${env_name_prefix}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: !empty(log_analytics_customer_id) ? {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: log_analytics_customer_id
        sharedKey: log_analytics_shared_key
      }
    } : null
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
  }
}

// Example scheduled job — pg_backup. The image is a placeholder; the real
// job (when a registry exists) writes pg_dump output to the storage
// account's backups/ container.
resource pgBackupJob 'Microsoft.App/jobs@2024-03-01' = {
  name: 'job-pg-backup-${env_name_prefix}'
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    environmentId: env.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: 1800 // 30 min ceiling on a single backup
      replicaRetryLimit: 1
      scheduleTriggerConfig: {
        cronExpression: pg_backup_schedule
        parallelism: 1
        replicaCompletionCount: 1
      }
    }
    template: {
      containers: [
        {
          name: 'pg-backup'
          image: pg_backup_image
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'ENV_NAME'
              value: env_name_prefix
            }
            // Real implementation reads DATABASE_URL_SYNC from KV,
            // AZURE_STORAGE_ACCOUNT_URL from main.bicep outputs.
            // Placeholder image ignores both.
          ]
        }
      ]
    }
  }
}

// alert_digest — daily exec digest of variance flags. Sends via ACS.
resource alertDigestJob 'Microsoft.App/jobs@2024-03-01' = if (enable_alert_jobs) {
  name: 'job-alert-digest-${env_name_prefix}'
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    environmentId: env.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: 600 // 10 min ceiling — should finish in under 60s
      replicaRetryLimit: 1
      scheduleTriggerConfig: {
        cronExpression: alert_digest_schedule
        parallelism: 1
        replicaCompletionCount: 1
      }
      secrets: [
        {
          name: 'database-url'
          value: database_url
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'alert-digest'
          image: alert_digest_image
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            { name: 'ENV_NAME', value: env_name_prefix }
            { name: 'AZURE_COMMUNICATION_ENDPOINT', value: azure_communication_endpoint }
            { name: 'AZURE_COMMUNICATION_SENDER', value: azure_communication_sender }
            { name: 'DATABASE_URL', secretRef: 'database-url' }
          ]
        }
      ]
    }
  }
}

// cred_scan — daily credential expiry alerts. Same ACS env shape.
resource credScanJob 'Microsoft.App/jobs@2024-03-01' = if (enable_alert_jobs) {
  name: 'job-cred-scan-${env_name_prefix}'
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    environmentId: env.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: 600
      replicaRetryLimit: 1
      scheduleTriggerConfig: {
        cronExpression: cred_scan_schedule
        parallelism: 1
        replicaCompletionCount: 1
      }
      secrets: [
        {
          name: 'database-url'
          value: database_url
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'cred-scan'
          image: cred_scan_image
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            { name: 'ENV_NAME', value: env_name_prefix }
            { name: 'AZURE_COMMUNICATION_ENDPOINT', value: azure_communication_endpoint }
            { name: 'AZURE_COMMUNICATION_SENDER', value: azure_communication_sender }
            { name: 'DATABASE_URL', secretRef: 'database-url' }
          ]
        }
      ]
    }
  }
}

@description('Container Apps environment resource ID — used by main.bicep to wire additional Job resources later.')
output env_id string = env.id

@description('Container Apps environment name.')
output env_resource_name string = env.name

@description('pg_backup job resource ID — for follow-up RBAC role assignments (Storage Blob Data Contributor on the backups container).')
output pg_backup_job_id string = pgBackupJob.id

@description('pg_backup job principal ID (managed identity). Wire to Storage RBAC in main.bicep follow-up.')
output pg_backup_principal_id string = pgBackupJob.identity.principalId

@description('alert_digest job principal ID — wire to ACS Contributor (or "Email Communication Service Contributor") for managed-identity sends.')
output alert_digest_principal_id string = enable_alert_jobs ? alertDigestJob!.identity.principalId : ''

@description('cred_scan job principal ID — same role assignment as alert_digest.')
output cred_scan_principal_id string = enable_alert_jobs ? credScanJob!.identity.principalId : ''
