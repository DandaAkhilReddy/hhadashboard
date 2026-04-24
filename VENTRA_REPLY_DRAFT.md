# Reply to Gilda Romero (Ventra) — RE: HHA Review of BI & Data

**To:** Gilda.Romero@VentraHealth.com
**Cc:** (keep existing +4 from her thread)
**Subject:** RE: HHA — Review of BI & Data

> Note: Ventra handles HHA's **Florida** book only. Texas RCM is on a separate track and is not part of this conversation.

---

Hi Gilda,

Thanks for the quick turnaround and for pulling in the analyst and Client Success teams.

## Quick context on what HHA is building

We're standing up an internal operations dashboard for exec leadership (CEO, CFO, COO, CMO) covering four focus areas:

1. **Operations** — daily census, coverage, open shifts, contract status by site
2. **Finance** — HHA top-line only (collections in, AR aging, NCR, days in AR)
3. **Clinical quality** — documentation timeliness (H&P / DC), LOS, credential lifecycle
4. **People** — headcount, turnover, coverage gaps

Denials, appeals, and the claim-level workflow all stay with Ventra — we're not duplicating any of that. We just need top-line visibility into what's landing and how the AR is moving for our Florida book.

## Data elements we'd like to explore (Florida book)

- **Collections** — daily and MTD totals for the HHA Florida book
- **AR aging** — 5-bucket (0-30 / 31-60 / 61-90 / 91-120 / >120)
- **Net Collection Rate** and **Days in A/R** — monthly
- **Per-physician monthly revenue rollup** — aggregate dollars only, no claim detail
- **Per-physician chart-timeliness aggregates** (H&P within 24h %, DC within 48h %, avg close time) — from Athena chart timestamps

For context: our Texas book sits outside Ventra's scope, so this engagement is specifically on the Florida side.

## Delivery preference

Strong preference for **pre-aggregated summaries** (daily or monthly CSV via SFTP, or a scheduled Athena report) over raw claim-level API. Our dashboard minimizes PHI footprint by design — rollups are cleanest. If a claim-level feed is the only option, we can aggregate at our ingestion edge, but summary-level is ideal.

## Two quick items for the analyst

1. **BAA scope** — want to confirm our current MSA / BAA covers this reporting scope, or whether a scope addendum is needed.
2. **Athena access path** — since HHA's Athenahealth instance (Florida) sits under Ventra's tenant, any direct Athena API / SFTP access to HHA's Florida data needs to route through your approval. What options do you typically provide clients?

## Meeting

Happy to do a single 60-minute scoping session, or split into a 30-min high-level + 30-min technical follow-up — whichever works best on your side. My availability next week:

- Tue 4/28 — 10 AM – 12 PM ET, or 2 – 4 PM ET
- Wed 4/29 — 11 AM – 1 PM ET
- Thu 4/30 — 10 AM – 12 PM ET

## Ideal outcome of the first call

1. Confirm BAA covers the above reporting scope (or define the addendum)
2. Agreement on the list of data elements
3. Delivery format + cadence
4. Named owner on each side + rough timeline

From HHA I'll attend. Happy to include Sandy Collins and/or Maribel Reyes for the finance-data portion — let me know if you'd like the circle any wider.

Best,
Akhil Reddy
HHA Medicine

---

## Notes before sending (delete these before pasting into Outlook)

- **Verify your availability** for Tue/Wed/Thu next week — the slots above are placeholders.
- **Decide on co-attendees**: draft defers to Gilda. Change to "I'll bring Sandy and Maribel" if you'd rather bring them in from the first call.
- **CC list**: reply-all to keep Gilda's +4 looped in.
- **Scope is Florida-only** for this thread. Texas is a separate RCM conversation with whoever handles TX billing — don't mention Texas details to Ventra beyond the brief aside.
- **What's deliberately NOT in this reply**: our internal stack (Next.js / FastAPI / Azure / Entra). Irrelevant to Ventra and invites scope drift. Business asks only.
