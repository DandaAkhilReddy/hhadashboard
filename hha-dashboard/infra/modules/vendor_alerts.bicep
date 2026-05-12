// Vendor-ingest Azure Monitor alerts per Phase 1A.A9 of the plan.
//
// Subscribes to the App Insights custom events emitted by the
// jobs/ventra_ingest container (ventra.validation_failed,
// ventra.adr005_violation, ventra.ingest_failed) and fires email alerts
// through a dedicated Action Group.
//
// One Action Group (ag-vendor-ingest) with email recipients fan-out;
// scheduled query rules use Log Analytics-bound KQL to evaluate the
// recent custom-event stream every 5 minutes.
//
// Scoped to log alerts only in this commit. Metric alerts (Container App
// job exit code != 0, vendor-deadletter blob count > 0, KV access denied)
// are a follow-up — they require subscription-scope metric IDs that
// aren't fully available at module-build time without explicit resource
// references, and they don't add immediate signal beyond what the log
// events already cover.

@description('Resource name prefix. Convention: env_name (dev/prod). Used for unique alert + action group names.')
param env_name_prefix string

@description('Azure region.')
param location string = 'global' // Metric/log alerts are global resources

@description('App Insights resource ID. Required — scoped to receive ventra.* custom events.')
param app_insights_id string

@description('Action group display name (short — max 12 chars per Azure constraint). Default vendor-ingst.')
@maxLength(12)
param action_group_short_name string = 'vendor-ingst'

@description('Email recipient list for vendor-ingest alerts. Array of {name, emailAddress} objects.')
param email_receivers array = []

@description('Tags applied to every resource.')
param tags object = {}

// =========================================================================
// Action Group — fan-out target for every alert rule below.
// =========================================================================
resource actionGroup 'Microsoft.Insights/actionGroups@2023-09-01-preview' = {
  name: 'ag-vendor-ingest-${env_name_prefix}'
  location: location
  tags: tags
  properties: {
    groupShortName: action_group_short_name
    enabled: true
    emailReceivers: [for r in email_receivers: {
      name: r.name
      emailAddress: r.emailAddress
      useCommonAlertSchema: true
    }]
  }
}

// =========================================================================
// Alert 1: V1-V13 validation failure (Sev 2 — Warn).
//   Triggers on any ventra.validation_failed custom event in the last 5
//   minutes. Drop is quarantined; operator triages the reject sidecar.
// =========================================================================
resource alertValidationFailed 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-ventra-validation-failed-${env_name_prefix}'
  location: location
  tags: tags
  properties: {
    description: 'Fires when jobs/ventra_ingest quarantines a drop (V1-V13). Action: review vendor-quarantine/ventra/{drop_date}/_REJECT_REASON.txt and decide whether to push back on vendor or retry after a content fix.'
    displayName: 'Ventra ingest: validation_failed'
    severity: 2
    enabled: true
    scopes: [
      app_insights_id
    ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    autoMitigate: false
    criteria: {
      allOf: [
        {
          query: 'customEvents | where name == "ventra.validation_failed"'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: [
        actionGroup.id
      ]
    }
  }
}

// =========================================================================
// Alert 2: ADR-005 violation (Sev 0 — Critical).
//   V12 — non-FL facility_no in a Ventra drop. Immediate INCIDENT per the
//   security playbook; triggers email + (when Action Group gains SMS in a
//   follow-up) page. Auto-mitigate disabled — incident closure is manual.
// =========================================================================
resource alertAdr005Violation 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-ventra-adr005-violation-${env_name_prefix}'
  location: location
  tags: tags
  properties: {
    description: 'CRITICAL: Ventra delivered a row with a non-Florida facility_no, violating ADR-005 FL-only invariant. Open docs/04-operations/SECURITY_INCIDENT_PLAYBOOK.md and investigate immediately. Drop is quarantined; no data written.'
    displayName: 'Ventra ingest: ADR-005 violation (TX facility in feed)'
    severity: 0
    enabled: true
    scopes: [
      app_insights_id
    ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    autoMitigate: false
    criteria: {
      allOf: [
        {
          query: 'customEvents | where name == "ventra.adr005_violation"'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: [
        actionGroup.id
      ]
    }
  }
}

// =========================================================================
// Alert 3: Job exception / unhandled failure (Sev 1 — Error).
//   Distinguishes from validation_failed (which is the expected quarantine
//   path); ingest_failed indicates a code bug, DB outage, or environmental
//   problem — needs triage in App Insights traces.
// =========================================================================
resource alertIngestFailed 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-ventra-ingest-failed-${env_name_prefix}'
  location: location
  tags: tags
  properties: {
    description: 'jobs/ventra_ingest exited with a non-quarantine error (exception, DB connection failure, etc.). KEDA will retry up to 3x before dead-lettering. Triage in App Insights via correlation_id from the event payload.'
    displayName: 'Ventra ingest: ingest_failed (exception path)'
    severity: 1
    enabled: true
    scopes: [
      app_insights_id
    ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    autoMitigate: false
    criteria: {
      allOf: [
        {
          query: 'customEvents | where name == "ventra.ingest_failed"'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: [
        actionGroup.id
      ]
    }
  }
}

@description('Action Group resource ID — for downstream rbac.bicep wiring (Monitoring Contributor on the AG for the API to fire ad-hoc alerts later).')
output action_group_id string = actionGroup.id

@description('Action Group name.')
output action_group_name string = actionGroup.name

@description('Validation-failed alert rule resource ID.')
output alert_validation_failed_id string = alertValidationFailed.id

@description('ADR-005 violation alert rule resource ID.')
output alert_adr005_id string = alertAdr005Violation.id

@description('Ingest-failed alert rule resource ID.')
output alert_ingest_failed_id string = alertIngestFailed.id
