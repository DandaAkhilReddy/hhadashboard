// Azure Communication Services + Email Communications Service.
//
// Why ACS Email instead of SendGrid / Resend / SES:
//   - BAA-covered out of the box under HHA's Microsoft tenant
//   - Same identity model as the rest of the stack (managed identity)
//   - The 7am exec digest + credential expiry alerts (per
//     DASHBOARD_PLAN.md § Alerting) are the only email path; no
//     transactional volume to justify a third-party
//
// Domain strategy:
//   - v0 uses an Azure Managed Domain (sender like
//     `donotreply@<random>.azurecomm.net`) — works immediately, no DNS
//   - v1 (post-launch) attaches a custom domain like
//     `alerts@hhamedicine.com` — needs DNS records (TXT, SPF, DKIM, DMARC)
//     in HHA's M365 zone. Out of scope here.
//
// What this module is NOT (deferred):
//   - Custom domain attachment + DNS verification
//   - SMTP credentials (we use the ACS REST API + managed identity)
//   - Diagnostic Settings → Log Analytics (lands with monitor.bicep
//     extension; for now ACS audit logs route via the ACS resource's
//     own logs, not into our workspace yet)

@description('ACS resource name. Convention: acs-hha-{env}.')
param acs_name string

@description('Email Communications Service name. Convention: ecs-hha-{env}. Globally scoped.')
param email_service_name string

@description('Azure region for ACS. Note: ACS Data Location is independent — set by data_location, not location.')
param location string = 'global'

@description('ACS Data Location. Where Communication Services data is stored at rest. United States is the typical choice for HHA.')
@allowed(['UnitedStates', 'Europe', 'Asia Pacific', 'Australia', 'Brazil', 'Canada', 'France', 'Germany', 'India', 'Japan', 'Korea', 'Norway', 'Switzerland', 'United Kingdom', 'United Arab Emirates'])
param data_location string = 'UnitedStates'

@description('Tags applied to every resource.')
param tags object = {}

// Email Communications Service — provides the email-sending substrate.
// Attaches an Azure Managed Domain for v0; custom domain wiring is
// out-of-scope.
resource emailService 'Microsoft.Communication/emailServices@2023-04-01' = {
  name: email_service_name
  location: location
  tags: tags
  properties: {
    dataLocation: data_location
  }
}

resource managedDomain 'Microsoft.Communication/emailServices/domains@2023-04-01' = {
  parent: emailService
  name: 'AzureManagedDomain'
  location: location
  tags: tags
  properties: {
    domainManagement: 'AzureManaged'
    userEngagementTracking: 'Disabled' // disable click/open tracking — adds tracking pixels we don't want for HIPAA-aware messages
  }
}

// Communication Services resource — the SDK target. Linked to the email
// service via the linkedDomains property below.
resource acs 'Microsoft.Communication/communicationServices@2023-04-01' = {
  name: acs_name
  location: location
  tags: tags
  properties: {
    dataLocation: data_location
    linkedDomains: [
      managedDomain.id
    ]
  }
}

@description('ACS resource ID — used for cross-resource references and downstream RBAC.')
output acs_id string = acs.id

@description('ACS resource name (echoed for symmetry).')
output acs_name string = acs.name

@description('ACS endpoint URL — the api uses this as AZURE_COMMUNICATION_ENDPOINT for the SDK client.')
output acs_endpoint string = 'https://${acs.name}.communication.azure.com'

@description('Sender address from the Azure Managed Domain. Use for digest/alerts From: header.')
output sender_address string = 'DoNotReply@${managedDomain.properties.mailFromSenderDomain}'

@description('Email service resource ID — for diagnostic settings + custom-domain attachment later.')
output email_service_id string = emailService.id
