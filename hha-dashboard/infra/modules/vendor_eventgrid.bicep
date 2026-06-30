// Vendor-ingest Event Grid wiring — System Topic on vendor storage,
// subscription filtered to _MANIFEST.csv, dest = Storage Queue, DLQ = blob
// container.
//
// Per Phase 1A.A4 of the plan: when Ventra writes _MANIFEST.csv as the
// LAST file in /vendor-inbound/ventra/YYYY-MM-DD/, that BlobCreated event
// matches this subscription's filter and enqueues a message to
// q-ventra-manifests. KEDA azure-queue scaler on the Container Apps Job
// (C7) picks it up, drains the queue, runs validators V1-V14.
//
// The manifest-last pattern is critical: the subscription filter excludes
// all non-manifest files so partial drops never trigger the job. The job
// then reads the manifest, downloads + checksums each listed file, and
// proceeds only if all are present.
//
// Failure modes covered by this module:
//   - Subscription delivery fails 5x → message goes to vendor-deadletter
//     blob container (operator triages from there)
//   - Event Grid outage → manifest stays in vendor-inbound; safety-net
//     cron in Phase 1A.A5 (added in C7 or follow-up) scans for orphans
//   - Queue message expiry → 7-day TTL gives operators time to react
//
// What this module is NOT:
//   - Does not create the Container Apps Job (C7)
//   - Does not assign roles (rbac.bicep / C7)
//   - Does not create the storage account or containers (vendor_storage.bicep)
//   - Does not register the EventGrid resource provider — that's a
//     subscription-level concern done out-of-band on first use

@description('Name of the vendor-inbound storage account (created in vendor_storage.bicep). The system topic is bound to this account.')
param vendor_storage_account_name string

@description('Azure region.')
param location string

@description('Tags applied to every resource.')
param tags object = {}

@description('Storage Queue name for manifest events. Convention: q-ventra-manifests.')
param manifest_queue_name string = 'q-ventra-manifests'

@description('Blob container name for dead-lettered events. Must exist on the storage account (vendor_storage.bicep creates it).')
param deadletter_container_name string = 'vendor-deadletter'

@description('Subject filter prefix. Matches blobs under /vendor-inbound/ventra/. Adjust if the container or vendor folder ever changes.')
param subject_prefix string = '/blobServices/default/containers/vendor-inbound/blobs/ventra/'

@description('Subject filter suffix. Matches only manifest files so partial drops never trigger.')
param subject_suffix string = '/_MANIFEST.csv'

@description('Max delivery attempts before dead-letter. 5 = ~30 min retry window with default backoff.')
@minValue(1)
@maxValue(30)
param max_delivery_attempts int = 5

@description('Event TTL in minutes. 1440 = 24 hours; operators have a day to revive a stuck subscription before events fall off.')
@minValue(60)
@maxValue(43200)
param event_ttl_minutes int = 1440

@description('Queue message TTL in seconds. 604800 = 7 days; long enough for weekend gaps in operator attention.')
@minValue(60)
@maxValue(2592000)
param queue_message_ttl_seconds int = 604800

// Reference the existing vendor-storage account so we can attach the queue
// + system topic without taking ownership of the resource. vendor_storage
// module owns lifecycle of the account itself.
resource vendorStorage 'Microsoft.Storage/storageAccounts@2024-01-01' existing = {
  name: vendor_storage_account_name
}

// Queue service (default, one-per-account). Creating it is idempotent — if
// it already exists from a prior deploy, Bicep no-ops.
resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2024-01-01' = {
  parent: vendorStorage
  name: 'default'
  properties: {}
}

resource manifestQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2024-01-01' = {
  parent: queueService
  name: manifest_queue_name
  properties: {
    metadata: {
      purpose: 'event-grid-target-for-vendor-manifest-blob-created-events'
    }
  }
}

// System topic — one per storage account; receives ALL blob events from
// the account. The subscription below filters to only the manifest pattern.
resource systemTopic 'Microsoft.EventGrid/systemTopics@2023-12-15-preview' = {
  name: 'evgt-${vendor_storage_account_name}'
  location: location
  tags: tags
  properties: {
    source: vendorStorage.id
    topicType: 'Microsoft.Storage.StorageAccounts'
  }
}

// Subscription — filters to manifest-only, delivers to the queue, dead-
// letters to the deadletter blob container.
resource ventraManifestSubscription 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2023-12-15-preview' = {
  parent: systemTopic
  name: 'sub-ventra-manifest'
  properties: {
    destination: {
      endpointType: 'StorageQueue'
      properties: {
        resourceId: vendorStorage.id
        queueName: manifestQueue.name
        queueMessageTimeToLiveInSeconds: queue_message_ttl_seconds
      }
    }
    filter: {
      includedEventTypes: [
        'Microsoft.Storage.BlobCreated'
      ]
      subjectBeginsWith: subject_prefix
      subjectEndsWith: subject_suffix
      // Avoid duplicate triggers from overwrite-style writes; only emit
      // when the blob is *newly* created with content.
      advancedFilters: [
        {
          operatorType: 'StringContains'
          key: 'data.api'
          values: [
            'PutBlob'
            'PutBlockList'
            'FlushWithClose'
            'CopyBlob'
          ]
        }
      ]
    }
    deadLetterDestination: {
      endpointType: 'StorageBlob'
      properties: {
        resourceId: vendorStorage.id
        blobContainerName: deadletter_container_name
      }
    }
    retryPolicy: {
      maxDeliveryAttempts: max_delivery_attempts
      eventTimeToLiveInMinutes: event_ttl_minutes
    }
    eventDeliverySchema: 'EventGridSchema'
  }
}

@description('System topic resource ID.')
output system_topic_id string = systemTopic.id

@description('System topic name.')
output system_topic_name string = systemTopic.name

@description('Manifest subscription resource ID.')
output subscription_id string = ventraManifestSubscription.id

@description('Manifest queue name — Container Apps Job KEDA scaler binds to this.')
output manifest_queue_name string = manifestQueue.name

@description('Fully-qualified queue resource ID — for diagnostic settings and role assignments.')
output manifest_queue_id string = manifestQueue.id
