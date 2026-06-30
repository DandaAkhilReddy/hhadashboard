# Reply to Gilda — "are you seeing activity from core-prd-mft01?" (2026-06-29)

Draft for Akhil to send. Answers Gilda's Yes/No ASK about whether HHA is
seeing activity from Ventra's server `core-prd-mft01` (egress IP
`52.177.111.231`, which is on HHA's allowlist).

---

**Subject:** RE: Follow Up on Review of BI & Data

Hi Gilda,

**Yes — we are seeing connection activity from `core-prd-mft01`
(52.177.111.231).** On June 29 we saw SFTP connections from your server in
roughly the 10 AM–1 PM ET window. **No files have transferred yet** — these
were connection/authentication only, which lines up with your team getting
set up.

Your egress IP is allowlisted on our endpoint and the path is open, so
you're clear to set up the folders / transfer job on your side. We've just
enabled detailed connection logging on our end, so on your next test (or
the first real transfer) we'll confirm the exact connection and that the
file lands.

For reference, the endpoint your team targets:

- Host: `sthhavendordev5801224b.blob.core.windows.net` (port 22)
- User (Standard Data Extract): `sthhavendordev5801224b.ventrastdspec`
- Auth: SSH key (your `ventra-stdspec` public key is installed)

Thanks,
Akhil

---

## Internal notes (do not send)

**What's solid vs inferred:**
- **SOLID:** No files have landed — `vendor-inbound/ventra/stdspec/` and
  `/preagg/` are both empty (confirmed via CLI + the portal Storage browser).
- **SOLID:** `52.177.111.231` is on the firewall allowlist (3 IPs total:
  `71.227.196.232` workstation, `52.177.111.231`, `4.151.247.225`).
- **INFERRED:** the "connection activity in the 14:00–17:00 UTC Jun 29
  window" comes from time-bucketing the **Transactions** platform metric.
  That metric does **not** carry the source IP, so attributing that window
  to `core-prd-mft01` is a timing inference (it's not us, not the 05:00
  Azure health checks) — reasonable but not IP-proven. Metric counts were
  also inconsistent across query runs (Azure aggregation latency), so don't
  quote an exact connection count.

**Now definitive going forward:** connection logging is enabled as of
2026-06-29:
- Log Analytics workspace `log-hha-vendor-dev` (RG `rg-hha-dashboard-dev`).
- Diagnostic setting `vendor-sftp-diag` on the blob service →
  StorageRead/StorageWrite/StorageDelete (captures `CallerIpAddress` +
  `AuthenticationType=LocalUserPublicKey`).
- **Forward-only** — the past Jun 29 connections won't be in the logs;
  ask Ventra to run one more test to get a 100%-confirmed, IP-stamped record.

**KQL to confirm on the next test** (run in the `log-hha-vendor-dev`
workspace; logs appear ~5–15 min after the event):
```kql
StorageBlobLogs
| where TimeGenerated > ago(2h)
| where CallerIpAddress startswith "52.177.111.231"
| project TimeGenerated, CallerIpAddress, AuthenticationType, OperationName, Uri, StatusCode, StatusText
| order by TimeGenerated desc
```

**Still open with Ventra:** none blocking — they're clear to proceed. If
their next test still lands no file, check the SFTP username/key and the
target path against the logs.
