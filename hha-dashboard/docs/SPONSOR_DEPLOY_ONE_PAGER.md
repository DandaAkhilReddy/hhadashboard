# HHA Operations Dashboard — Phase 1 is live

> One-page status for the sponsor. Last updated: <DATE>

## What you can do today

- [ ] Open <CUSTOM_DOMAIN> in any browser
- [ ] Sign in with your Microsoft account (Entra)
- [ ] See today's census across all 11 hospitals (FL + TX)
- [ ] See subsidy + facility info for every site

The portal at <CUSTOM_DOMAIN>/census/login is for one ops person — they enter daily census numbers there, the dashboard reflects them in real time.

## What's NOT live yet — and why

| Feature | Status | Why |
|---|---|---|
| Finance KPIs (Sandy) | empty | data feed pending — vendor unblock |
| Clinical quality (Aneja/Reddy) | empty | next phase, manual entry pattern proven |
| HR / staffing (Andrea) | empty | Paycom API access still in progress (4–6 weeks) |
| Florida revenue from Ventra | empty | Ventra BAA + data shape still in legal review |

This is by design — Phase 1 was census only. We will light up each panel as the source data lands, one at a time. Nothing reads "fake" numbers anywhere; every empty cell is honestly empty.

## What this costs us

- Dev environment (engineering use): ~$<DEV_COST>/mo
- Prod environment (real users): ~$<PROD_COST>/mo
- Combined: ~$<TOTAL_COST>/mo

Cost scales with the number of hospitals and records per day. Phase 1 volume is small (roughly 100 rows/day across all sites). Expect a 1.5–2x bump once Finance and Ventra ingestion light up — still well under a material line item.

## Security posture (one paragraph for the lawyer)

Hosted on Microsoft Azure under a BAA-covered subscription. No patient data is stored anywhere — only facility-level census counts. Every write to the database is audited (who, when, what changed). Nightly off-site backup with a 30-day immutable lock — even an administrator cannot delete the last 30 days of backups. TLS-managed certificates, no self-signed. Production access is restricted to executive leadership (CEO/CFO/COO/CMO) plus named department owners — total user count: 5–10, all authenticated through your existing Microsoft accounts.

## If something breaks

1. Try the dashboard in an Incognito window first (resolves cache issues in about 80% of cases).
2. If the dashboard is still down, contact: <SPONSOR_NOTIFY_EMAIL>.
3. Critical issue (data loss or unauthorized access): notify the HHA Privacy Officer immediately under the standing HIPAA incident-response policy.
4. Detailed runbook for the on-call operator lives at: `docs/RUNBOOK.md` in the GitHub repo — listed here for completeness, not for sponsor action.

## What's next

| When | What |
|---|---|
| This quarter | Finance panel live (manual entry from Sandy / Maribel) |
| When Paycom unblocks (4–6 wks) | HR + staffing automation |
| When Ventra BAA is signed | FL revenue auto-pulled, no manual entry needed |
| Ongoing | Census stays simple — one form, eleven hospitals, one number per facility per day |

— Akhil
