// Prod environment parameters.
//
// SKUs sized for the live HHA dashboard: 5–10 exec users, audit retention,
// HA across availability zones, geo-redundant backups.
//
// Approximate monthly cost (eastus2):
//   Postgres D2ds_v5 ZoneRedundant + 35d retention   ~$310
//   App Service P1v3 (2 instances, shared by web+api) ~$155
//   Total before storage / observability             ~$465
//
// At deploy time, supply secure params from Key Vault:
//   az deployment group create -g rg-hha-dashboard-prod -f infra/main.bicep \
//     -p infra/env/prod.bicepparam \
//     -p postgres_admin_password=$(az keyvault secret show --vault-name kv-hha-prod -n postgres-admin --query value -o tsv) \
//     -p deployer_workstation_ip=$(curl -s ifconfig.me)

using '../main.bicep'

// MUST be overridden at deploy time. In prod, postgres_admin_password should
// come from Key Vault via:
//   -p postgres_admin_password=$(az keyvault secret show --vault-name kv-hha-prod -n postgres-admin --query value -o tsv)
// Empty placeholder here so the bicepparam compiles; deploy will fail safely
// without an override.
param postgres_admin_password = '__OVERRIDE_AT_DEPLOY_TIME__'
param deployer_workstation_ip = '162.227.196.122'

param env_name = 'prod'

// Suffix added to KV name. The first prod attempt's `kv-hha-prod` is now
// soft-deleted with purge protection enabled (cannot be purged for 90 days).
// Use a different name on retry; future deploys reuse this one.
param kv_name_suffix = '1'

// Region: centralus. The HHA subscription's Postgres Flex offer is
// restricted in both eastus and eastus2. centralus has historically been
// the most permissive US region for new PAYG subs. If this fails too,
// fall back to westus2 or westus3.
param location = 'centralus'

// Postgres — Burstable B1ms (DEGRADED FROM TARGET).
// The HHA subscription is freshly-provisioned PAYG and rejects Postgres
// GeneralPurpose SKUs with LocationIsOfferRestricted. Burstable is
// universally allowed. Upgrade path once restriction lifts (post first
// invoice or via Azure support ticket):
//   az postgres flexible-server update -g rg-hha-dashboard-prod \
//     -n psql-hha-prod --tier GeneralPurpose --sku-name Standard_D2ds_v5
//   az postgres flexible-server update --high-availability ZoneRedundant
// Burstable doesn't support HA or geo-redundant backups so both off below.
param postgres_sku_name = 'Standard_B1ms'
param postgres_sku_tier = 'Burstable'
param postgres_backup_retention_days = 7
param postgres_geo_redundant_backup = 'Disabled'
param postgres_ha_mode = 'Disabled'

// App Service — B1 Basic for 20-user prod. Right-sized: ~$13/mo vs $155
// for P1v3. Shared CPU is fine for 20 exec users on a read-heavy dashboard.
// Upgrade path when traffic grows or VNet re-enables:
//   az appservice plan update -g rg-hha-dashboard-prod -n asp-hha-prod \
//     --sku P1v3
// Note: B1 doesn't support VNet integration. With enable_vnet=false anyway
// (Postgres on Burstable + public-with-firewall), there's no functional loss.
param plan_sku_name = 'B1'
param plan_sku_tier = 'Basic'
param worker_count = 1

// VNet — DISABLED on the restricted PAYG subscription.
//   - Burstable Postgres + public access with firewall allowlist
//   - Key Vault: public access + RBAC (no private endpoint)
//   - Tradeoff: lose VNet defense-in-depth, gain working deploy.
//   - HIPAA-defensible: TLS in transit, RBAC, audit log, IP allowlist.
//   - Upgrade path: flip enable_vnet=true once subscription unlocks GP tier.
param enable_vnet = false
param enable_keyvault = true
param azure_tenant_id_for_kv = '76596b76-3c41-40ee-a8a3-bf6930301838'

// Storage — LRS (locally redundant) for ~$5/mo solo prod. Backups stay
// in 1 region; HIPAA doesn't require cross-region. Soft-delete 90 days
// for accidental-delete recovery. Upgrade to RAGRS if cross-region read
// access becomes a requirement (~$5/mo more):
//   az storage account update -n sthhaprod... --sku Standard_RAGRS
param enable_storage = true
param storage_sku = 'Standard_LRS'
param storage_soft_delete_retention_days = 90

// Monitor — ON in prod. Required for HIPAA audit chain.
param enable_monitor = true
param monitor_retention_days = 90

// Email — ON in prod. ACS + Email Communications Service with an Azure
// Managed Domain. Custom domain attachment is a follow-up.
param enable_email = true

// Container Apps Jobs — DISABLED on restricted subscription.
// Phase 1 is census-only — no Ventra/Paycom ingestion, no nightly cron jobs.
// Re-enable once ACR unlocks (depends on subscription quota).
param enable_container_jobs = false

// ACR — DISABLED. Subscription rejects both Basic and Standard SKUs on
// the freshly-provisioned PAYG sub (SkuNotSupported). Cron job images
// can ship via ghcr.io as a fallback, or wait for the subscription to
// unlock. Phase 1 (census-only) doesn't need ACR.
param enable_acr = false
param acr_sku = 'Basic'

// RBAC — ON in prod. Wires AcrPull (cron jobs → ACR), Storage Blob Data
// Contributor (pg_backup → backups/), and ACS Contributor (alert_digest +
// cred_scan + api → ACS Email). All use system-assigned MIs — no static
// credentials anywhere in the runtime.
param enable_rbac = true

// Entra IDs — populated from `scripts/azure_create_missing.sh` discovery
// run on 2026-04-28. The 7 groups + 2 app registrations live in the
// HHA Medicine M365 tenant (76596b76-...).
param azure_tenant_id = '76596b76-3c41-40ee-a8a3-bf6930301838'
param azure_api_client_id = 'cabdd848-2221-4b21-9d2d-86572d791ee0'
param entra_groups = {
  admin: '12251714-b09d-4947-a82c-16057a36ef04'
  exec: 'a8d33d7f-a734-41a0-9d5b-3c450346a749'
  comp_viewer: '8198f75c-fc30-4b29-a309-957677906627'
  owner_ops: '752e1ab9-e361-4bdf-ba6c-d66f09094f84'
  owner_finance: '840d3f12-9ce8-4450-845e-294049073ccd'
  owner_clinical: '64fad693-3087-4532-9a2d-850f06bd1599'
  owner_hr: '13a06f26-6d65-4466-9c5a-f39a5698e33e'
}

param tags = {
  project: 'hha-dashboard'
  environment: 'prod'
  managed_by: 'bicep'
  classification: 'phi-tier-b'
  cost_center: 'operations'
}
