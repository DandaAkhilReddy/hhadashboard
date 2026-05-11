# Cost and capacity

> **For leadership.** Plain English on what we're spending, what we get for it, and what happens when we grow. Last updated 2026-05-11.

## TL;DR

| | Today (Phase 1 live) | Phase 2 + 3 (mid-2026) | Heavy upgrade (2027+) |
|---|---|---|---|
| Monthly Azure | **~$35** | ~$60–80 | ~$200–465 |
| Annual Azure | **~$420** | ~$720–960 | ~$2,400–5,600 |
| Cost per user (15 users) | $2.33/user/mo | $4–5/user/mo | $13–31/user/mo |

For context: this is the cost of one part-time consultant for a few hours a month. The platform is genuinely cheap because:

1. Cost-tuned SKUs (Burstable Postgres tier, Basic App Service)
2. Small user base (≤20 users)
3. Microsoft tenant covers some services (Entra ID, ACS email tier-1, Application Insights free tier)

## What's running today

| Resource | Purpose | SKU / Tier | Monthly |
|---|---|---|---|
| Postgres Flexible Server (`psql-hha-prod`) | Application + audit database | Burstable B1ms (1 vCPU, 2 GB RAM) | ~$18 |
| App Service Plan (Linux) | Hosts api + web | B1 Basic | ~$13 |
| Storage Account (`sthhaprod`) | Backups (immutable), uploads, future Ventra drops | Standard LRS | ~$2 |
| Key Vault (`kv-hha-prod2`) | Secrets, connection strings | Standard | ~$0.05 |
| Application Insights | Logs, traces, alerts | First 5 GB/mo free | $0 |
| Log Analytics workspace | Diagnostic logs from App Service | First 5 GB/mo free | $0 |
| Entra ID | Authentication | Covered by HHA's M365 tenant | $0 |
| Azure Communication Services (Email) | Daily digest, alerts | First 100K email/mo free | $0 |
| Outbound bandwidth | Web traffic | First 100 GB/mo free | $0 |
| **Total monthly** | | | **~$33–37** |

Variance comes from actual storage usage (backups accumulate) and Postgres burst credits.

## What's intentionally OFF (and why)

To stay at ~$35/mo, we've turned off some features that we'd normally have on in a "best practices" deploy. These are documented in `infra/env/prod.bicepparam`:

| Feature | Why disabled today | Cost if enabled |
|---|---|---|
| **VNet integration** | Subscription doesn't support GP-tier Postgres needed for private endpoint at our SKU | +$30/mo |
| **Azure Container Registry (ACR)** | We're not running container apps yet | +$15/mo (Standard tier) |
| **Container Apps Jobs** | Pending Phase 2 build (Ventra ingestion) | +$15–30/mo depending on run frequency |
| **Postgres zone-redundancy** | Burstable tier doesn't support it | +$18/mo (requires GP tier) |
| **Key Vault purge protection** | Off during early-deploy iteration so we can re-create vault if needed; will re-enable | $0 |

When Phase 2 lands, we'll turn on **Container Apps Jobs** and **ACR**, taking us from ~$35/mo to ~$60–80/mo.

## Cost by phase

### Today — Phase 1 in prod (~$35/mo)

The numbers above.

### Phase 2 — Ventra automated finance (~$60–80/mo)

Adds:

- Container Apps Jobs (for the daily Ventra ingestion job): ~$15/mo
- Azure Container Registry (Standard tier to host the job image): ~$15/mo
- Additional Postgres usage (more rows, slightly more compute): ~$5/mo
- Storage growth (Ventra raw CSV drops + Blob lifecycle): ~$3/mo

**Total: ~$60–80/mo (8x of phase 1).**

### Phase 3 — polish + alerting (~$65–85/mo, no significant uplift)

Adds:

- Custom domain + managed TLS cert: $0 (free with App Service)
- Increased ACS Email volume (weekly digest + alerts): negligible — under 100K/mo free tier

### Heavy upgrade scenario (~$200–465/mo)

If user count grows past 50 or the workload becomes more demanding, we'd move to:

| Resource | Upgrade | New monthly |
|---|---|---|
| Postgres | Burstable B1ms → GP_Standard_D2ds_v5 (zone-redundant) | ~$240 |
| App Service Plan | B1 → P1v3 (better performance, swap slots) | ~$80 |
| ACR | Basic → Standard | ~$5 |
| Add VNet integration + private endpoints | (one-time setup, ongoing) | +$30/mo |
| Power BI Premium (if exec dashboards expand) | Per-capacity license | +$5,000/mo (only if BI tooling added) |

We'd only move to this tier if we cross **specific scaling triggers** — not just "because more is better."

## Scaling triggers (when to upgrade)

| Trigger | Action |
|---|---|
| User count > 50 concurrent | Postgres burst credits will exhaust; upgrade to GP-tier |
| Daily ingest > 100K rows | Container Apps Jobs scaling; possibly GP-tier Postgres |
| API p95 latency > 2s | Add read replica or upgrade App Service Plan |
| App Service pegs CPU > 80% sustained | Upgrade App Service Plan |
| Postgres connections > 80% of pool | Add pgBouncer or upgrade tier |
| Audit log > 1M rows | Time-partition the table (engineering task, not cost) |
| HIPAA auditor requires private endpoints | Enable VNet, move Postgres to GP-tier |

The dashboard publishes these metrics; nothing requires guesswork.

## What we'd pay if we ran this elsewhere

For comparison (not a recommendation):

| Stack | Equivalent monthly |
|---|---|
| **Current — Azure all-PaaS** | $35 |
| AWS equivalent (RDS Postgres + Elastic Beanstalk + S3) | $40–60 |
| GCP equivalent (Cloud SQL + Cloud Run + GCS) | $35–50 |
| Snowflake-backed analytics tier (Business Critical for HIPAA) | $120–200 |
| Microsoft SQL Database (alternative to Postgres) | $30–50 |

Azure is the right home because:

1. HHA's Microsoft 365 tenant already has the Business Associate Agreement (BAA) covering Azure
2. Entra ID for sign-in is native (no separate identity vendor)
3. Microsoft's HIPAA story is well-documented and auditor-friendly

## What this NOT including

- **Engineering time** — Akhil's salary covers build + ops. No additional billing.
- **Ventra fees** — Ventra charges HHA a percentage of collections; that's a separate vendor contract unrelated to the dashboard.
- **External tools** — no Datadog, Sentry, Snowflake, or anything else. All observability is via Azure-native Application Insights.
- **One-time costs** — domain registration (~$15/year for `pulse.hhamedicine.com`) if not already owned.

## Cost review cadence

| Cadence | Who | What |
|---|---|---|
| **Daily** | Azure Cost Alerts | Threshold alerts at $50, $100, $200 monthly |
| **Monthly** | Akhil + CFO designate | Actual vs forecast, anomalies > 20% |
| **Quarterly** | Sponsor review | Year-to-date, projection for remaining quarters, scaling-trigger review |
| **Annually** | Sponsor + CFO | Renewal of Azure commitment (if any), Phase 4 budget approval |

## Action items for leadership

- ✅ Cost alerts are set; nothing to do today.
- 🟡 Approve Phase 2 cost uplift (~$30/mo additional) when Ventra build kicks off.
- 🟡 Approve any movement to GP-tier Postgres (~$200/mo additional) if/when a scaling trigger fires.

---

**Next read for leadership:** [COMPLIANCE_POSTURE.md](COMPLIANCE_POSTURE.md)
**Next read for engineering:** [ARCHITECTURE.md](ARCHITECTURE.md) § 12 (cost details)
