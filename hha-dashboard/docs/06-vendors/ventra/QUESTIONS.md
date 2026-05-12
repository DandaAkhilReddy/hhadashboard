# Ventra meeting — questions for HHA dashboard data feed

> **TL;DR**
> Tech-to-tech call to lock in **how** Ventra delivers FL operations data so HHA can build Phase 2 dashboards. Three non-negotiables: (1) BAA in writing, (2) FL-only — never TX, (3) aggregates only — no PHI persisted.

**Top 5 must-asks**

1. BAA confirmed and Athenahealth coverage clear — see §1
2. Pick one of four delivery shapes: pre-aggregated CSV / claim-level CSV / API / EDI 835 — see §3
3. Field grain agreed for `fact_collections_daily`, `fact_ar_snapshot`, `fact_revenue_by_physician_mo` — see §4
4. Sample / sandbox feed date committed — see §6.3, §8.1
5. Reconciliation acceptance criterion ($1K threshold or alternative) — see §5.5

## Decision tracker (fill in during the meeting)

- [ ] BAA confirmed in writing — *Ventra to send*
- [ ] Athena BAA chain clarified
- [ ] Delivery shape: ☐ (a) pre-agg CSV ☐ (b) claim CSV ☐ (c) API ☐ (d) EDI
- [ ] Cadence: ___________ (daily / weekly / monthly), finalized by ____ CT
- [ ] Auth: ☐ SFTP + SSH key + IP allowlist ☐ OAuth ☐ mTLS
- [ ] Field list signed off (3 fact tables)
- [ ] Sample-feed date: ____________
- [ ] First-prod-delivery date: ____________
- [ ] All-FL date: ____________
- [ ] Single Ventra technical POC: ____________ (email: ____________)
- [ ] Schema-change notification window: ___ days
- [ ] Reconciliation threshold: $ ____ per site per month
- [ ] Sandbox environment: ☐ yes ☐ no
- [ ] Audit-log access on request: ☐ yes ☐ no

---

**Meeting:** Tue 2026-05-05 · 11:00 AM CST · "HHA / Ventra — Review Reporting Needs"
**Duration:** 30 minutes (drives the agenda below — anything not landed becomes follow-up email)
**Format:** tech-to-tech
**Ventra attendees:** David Reck (CTO & Chief Data Officer), Suma Bhat (VP Data & Analytics), Darshan Patel, Client Success
**HHA attendee:** Akhil Reddy (IT Director / Solution Architect, +optional HHA leaders)

> **Goal:** confirm how Ventra will deliver **Florida-only** operations data so HHA can build the Phase 2 dashboards (Finance FL + Doctor Scorecards). Leave with one of the four shapes in §3 chosen, BAA + scope confirmed, sample-feed date committed.

---

## 30-minute agenda

| Time | Block | Goal | Reference |
|---|---|---|---|
| 0:00 – 0:03 | Opener + frame | Set the three non-negotiables (FL-only, no PHI, BAA-in-place) | §0 |
| 0:03 – 0:08 | BAA + scope | Confirm BAA + Athena chain + Florida facility list | §1 + §2 |
| 0:08 – 0:15 | **Delivery shape decision** | **Pick (a) / (b) / (c) / (d).** This is the meeting's main outcome | §3 |
| 0:15 – 0:22 | Field grain | Walk the 3 fact tables. Ventra confirms what they can / can't deliver | §4 |
| 0:22 – 0:27 | Operations | POC, sandbox, sample date, reconciliation threshold | §5.5, §6.1, §6.3, §8.1 |
| 0:27 – 0:30 | Wrap | Run through the Decision tracker, agree action-item owners | §10 |

> If a block runs long, skip the next block's "nice-to-have" questions (marked *NTH* below) and move on. Cuts go into the follow-up email.

---

## Strategic questions (sprinkle in — they reveal more than tactical ones)

Architect-level prompts for breathing-room moments or when an answer is vague:

1. **"From your experience with similar dashboard projects, what's the #1 thing that goes wrong on the integration side?"** — invites a war story; surfaces hidden risk.
2. **"Do you have a reference architecture or standard pattern for clients building exec dashboards from your data?"** — if yes, adopt it; if no, we set the pattern.
3. **"What's on your data-platform roadmap for the next 6–12 months that would affect this feed?"** — protects against a schema break right after we ship.
4. **"How do other clients reconcile your numbers against their internal accounting?"** — proven workflows beat improvising ours.
5. **"When something goes wrong with the feed, who owns it on your side, and how is HHA notified?"** — defines the operational contract.
6. **"What do you need from us to make this successful?"** — turns the conversation collaborative; often surfaces a setup task we'd otherwise miss.

---

## Per-block question bank (with anticipated answers + follow-ups)

### Block 1 (0:03 – 0:08) — BAA + scope

**Q1: Is the HHA ↔ Ventra BAA signed and current?**

- Yes → "Great — can you email a copy / written confirmation to areddy@hhamedicine.com today?" Move on.
- No / unsure → **red flag.** Ask: "What's the path to getting it signed? Who's the legal owner on your side?" Phase 2 is gated on this.

**Q2: Does the BAA cover Athenahealth (the underlying PM) as a downstream component, or do we need a separate BAA with Athena?**

- Covered downstream → ask for the language reference; document for compliance file.
- Need separate Athena BAA → "Can you facilitate the Athena BAA, or do we contact Athena directly?"

**Q3: Confirm Ventra services HHA's Florida hospitals only — never Texas?**

- Confirmed → "Send the full list of HHA-FL facilities under contract — NPI + facility name + service line."
- Some TX coverage → escalate; contradicts our scope (TX is manual-only).

### Block 2 (0:08 – 0:15) — Delivery shape (the big decision)

**Q4: Which of these four shapes is your standard delivery for clients of HHA's size?**

| Likely Ventra answer | HHA follow-up |
|---|---|
| (a) Pre-aggregated CSV via SFTP — "monthly is standard, daily is custom" | "Daily preferred for an exec dashboard. What's the cost / lead time for daily?" |
| (b) Claim-level CSV — "this is our default" | "We don't want claim-level. Can you aggregate before delivery? If not, confirm we can discard claim_id, MRN, etc. on receipt without breaching BAA." |
| (c) REST API with claim-level | "OAuth or static API key? Rate limits? Pagination scheme? Sandbox available?" |
| (d) 835 / 837 EDI | "We'd prefer (a) over EDI — EDI parsing is more code on our side. Is (a) on the table?" |

**Q5: Cadence — daily / weekly / monthly? At what time of day (CT) is the data finalized?** _NTH if running long_

- Monthly → "Is daily on the roadmap? Daily is what an exec dashboard needs."
- Daily → "Posted by what time CT? We need it by 7 am for the morning digest."

**Q6: Auth — SFTP + SSH key + IP allowlist? OAuth? mTLS?** *NTH*

- Static API key → push for OAuth; static keys rotated only via service request are brittle.

### Block 3 (0:15 – 0:22) — Field grain

> Before this block, mention you've shared `VENTRA_DATA_REQUIREMENTS.md` so they're walking the same tables. If they didn't read it, take 60 sec to summarise the 3 fact tables verbally.

**Q7: For `fact_collections_daily` — can you deliver at the grain (date, site, payer_bucket)?**

- Yes → confirm field list (gross_charges, payments_received, adjustments, refunds, net_revenue).
- Coarser only (monthly, no payer split) → "What's the lift to add daily and payer split? Config or new ETL?"
- "We have raw — you aggregate" → expected if shape (b)/(c)/(d). Confirm raw fields.

**Q8: For `fact_ar_snapshot` — daily snapshot or month-end only?**

- Month-end only → workable for v1. "Is daily AR snapshot something you've built for other clients?"
- Daily → "What time is the snapshot taken? End-of-business CT?"

**Q9: For `fact_revenue_by_physician_mo` — can you provide encounters, RVU, attributed revenue, and aggregated note timestamps (chart turnaround) per physician per month?**

- Yes → "What's your attribution rule — rendering provider, supervising provider, other?"
- Partial (encounters yes, doc timestamps no) → flag what we can't get; scorecards will show "coming soon" for those tiles.
- "We don't track docs / turnaround" → fall back: ask if Athena exposes it directly; revisit.

### Block 4 (0:22 – 0:27) — Operations

**Q10: Single technical POC for the data feed — name + email + on-hours?**

- Always ask for a named human. "Client success team" is not a POC.

**Q11: Sandbox / test environment with synthetic data — yes / no, when?**

- Yes → "Can you send 2–3 sample files this week so we can build the parser in parallel?"
- No → "Can you send a redacted sample of a real client's file?"

**Q12: First sample-feed date and first prod-delivery date — what can you commit to?**

- Push for a calendar date, not "a few weeks." Write it in the tracker.

**Q13: Reconciliation acceptance threshold — for any month, your Finance report and our dashboard agree within $1,000 per site. Does that match your expected accuracy?**

- "Sure" → write it down; confirm via follow-up email.
- "More like $5K" → negotiate; ask why the variance is that high (rounding? timing? source-of-truth ambiguity?).

### Block 5 (0:27 – 0:30) — Wrap

Walk the **Decision tracker** at the top of this doc, line by line. For each line: ☐ landed in meeting, ☐ follow-up email needed, ☐ blocker.

Confirm:

- Who sends what to whom by when (Ventra → HHA: BAA copy, facility list, sample files)
- Next checkpoint date (target: +2 weeks for sample-feed verification)
- Email subject line for the recap: `HHA × Ventra dashboard data feed — action items from 2026-05-05`

---

## Appendix — deeper question bank (parking lot / follow-up email)

The sections below are the full question set. The 30-minute agenda above pulls the highest-leverage subset. Anything cut from the live meeting goes into the follow-up email — keep these sections handy on a second monitor or print them out.

---

## 0. Two-minute opener (frame the meeting)

> "We're building an internal exec dashboard for HHA — operations, finance, clinical quality, people, and per-physician scorecards. Phase 1 is live with manual entry. For Phase 2 we need automated data from Ventra for our **Florida** book only. Texas stays on manual entry. We don't need claim-level data — just pre-aggregated daily/monthly rollups by site, payer, and provider. Today I want to align on **how** the data comes to us, **what fields**, and the **SLA** for freshness and corrections."

State up front:

- **No PHI lands in our database.** Aggregates only. Anything claim-level is read once, summed in memory, and discarded.
- **FL-only.** Texas is manual.
- **HIPAA-conscious.** BAA must be in place before any data flows.

---

## 1. BAA, scope, and contractual gates

> ⚠ **ASK FIRST.** If §1 doesn't get clean answers, defer everything else.

| # | Question | Why it matters |
|---|---|---|
| 1.1 | Is the **HHA ↔ Ventra BAA** signed and current? Can you send a copy or a written confirmation? | Phase 2 cannot start without this. |
| 1.2 | Does the BAA explicitly cover **Athenahealth (the underlying PM)** as a downstream component, or does HHA need a separate BAA with Athena? | Per ADR-001 inventory, Athena access is via Ventra tenant. We need to know the chain. |
| 1.3 | Are you a **HIPAA Business Associate** of HHA, or also a sub-business-associate to anyone else in the chain? | Audit trail requirement. |
| 1.4 | Where is HHA's data stored on your side (region, encryption at rest)? | We document this for HHA's compliance file. |
| 1.5 | Data retention on your side — how long do you hold HHA's raw RCM data, and what's the deletion process if HHA terminates? | Right-to-delete language in BAA. |
| 1.6 | Is there a **standard data-sharing addendum** (DUA / DPA) between you and clients, or do we negotiate this fresh? | Sets the legal frame for the rest. |

**Notes:**

---

## 2. Scope confirmation — the FL-only invariant

| # | Question | Why it matters |
|---|---|---|
| 2.1 | Confirm: Ventra services **HHA's Florida hospitals only**, never Texas. | ADR-005 hard rule — `source_system = VENTRA_FL_ATHENA` only. If TX data ever appears in your feed, that's an incident on our side. |
| 2.2 | What is the **full list of HHA-FL facilities** Ventra has under contract today? Please send NPI + facility name + service-line. | We have 11 hospitals total in our master list; some are TX. We need to map yours to ours. |
| 2.3 | Do you have a **Ventra-internal site/facility ID** distinct from NPI? If so, we need both — we'll join on NPI but want your ID for support tickets. | Operational. |
| 2.4 | Are there any sites where you only manage **part** of the RCM workflow (e.g. AR follow-up but not posting)? | Affects which metrics you're authoritative on vs. another vendor. |
| 2.5 | Does the feed cover **all payers**, or are self-pay / non-contracted carriers excluded? | Net-collection-rate denominator depends on this. |

**Notes:**

---

## 3. Data delivery shape

> 🎯 **Biggest technical decision of the meeting.** Goal: leave with one of (a)/(b)/(c)/(d) chosen.

We've designed for **four possible delivery shapes** — pick one. Each has different work on our side. The cleanest for HHA is option (a); option (d) is the most work.

### Decision options

| # | Shape | What you give us | What we do |
|---|---|---|---|
| **(a)** | **Pre-aggregated monthly CSV** via SFTP | Already aggregated by (month, state, payer-bucket, site) | Drop straight into `fact_collections_daily` and `fact_ar_snapshot` |
| **(b)** | **Daily CSV with claim-level rows** via SFTP | Per-claim rows (we strip identifiers, aggregate, persist only rollups) | Edge-aggregate in a Python job, raw files Blob-shredded after 30 days |
| **(c)** | **REST API with claim-level data** | OAuth-secured API, paginated | Same as (b) but streamed |
| **(d)** | **Raw 835 / 837 EDI files** | EDI 835 remits, optionally 837 claims | Add `pyx12` parser, same edge-aggregation rule |

### Questions to resolve which option

| # | Question |
|---|---|
| 3.1 | **Which of (a)/(b)/(c)/(d) is your standard delivery for clients of HHA's size?** Do you also support a custom shape if (a) is preferred? |
| 3.2 | If pre-aggregated (option a): can you commit to an **agreed schema** (column list + types + aggregation grain) that we both freeze in writing, with notice-of-change windows? |
| 3.3 | If claim-level (b/c/d): can you guarantee the feed never includes any of the forbidden fields below — or, if it does, that we are contractually permitted to discard them?<br>**Forbidden:** `patient_first_name`, `patient_last_name`, `patient_dob`, `mrn`, `member_id`, `subscriber_*`, `guarantor_*`, `claim_id` (we never persist either way) |
| 3.4 | Cadence — daily / weekly / monthly? At what time of day (CT) is data finalized? |
| 3.5 | Authentication — for SFTP, do you do mutual SSH-key auth + IP allowlist? For API, OAuth 2.0 client credentials, or static API key? |
| 3.6 | Are deliveries **incremental** (only new since last cursor) or **full snapshot**? If full snapshot, what's the rolling window (e.g. last 90 days)? |
| 3.7 | **Re-statements / corrections** — if a claim posts, then voids, then reposts a week later, how does that show in the feed? Do you mark records as `corrected_record=true`, send a delta, or re-emit the whole period? |
| 3.8 | **File format guarantees** — UTF-8? Header row? Field delimiter? Date format ISO-8601 or American? Numbers locale-formatted (`1,234.56`) or raw (`1234.56`)? |
| 3.9 | **Sample data** — can you send us 2–3 representative files (de-identified or test data) **this week** so we can build the parser before Phase 2 starts? |
| 3.10 | **Schema version** — is your delivery schema versioned? When you add fields or change types, what's the notification process? |

**Notes:**

---

## 4. Required data fields (mapped to our dashboard tiles)

We've already designed our schemas. The following table maps what we need from Ventra to where it lands. Anything not listed here we do **not** need (so don't send it — less surface area = less risk).

### 4.1 Finance board — `fact_collections_daily`

Aggregation grain: **(date, state, payer_bucket, site_id, source_system)**

| Field | Notes |
|---|---|
| `date` | Calendar day (CT). |
| `site_id` | Joinable to HHA's master sites list (NPI + facility). |
| `payer_bucket` | One of: `commercial`, `medicare`, `medicaid`, `selfpay`, `other`. We don't need carrier names. |
| `gross_charges` | Sum of charges posted. |
| `payments_received` | Cash actually received. |
| `adjustments` | Contractual + write-offs. |
| `refunds` | Refunds issued. |
| `net_revenue` | Computed by you, or we compute? Confirm formula. |

**Open questions:**

- Can you provide that exact grain, or only at a coarser level (e.g. monthly, or no payer split)?
- Is `payer_bucket` something you can map for us, or do we get raw payer codes and bucket on our side?

### 4.2 Finance board — `fact_ar_snapshot`

Aggregation grain: **(snapshot_date, state, site_id, aging_bucket)**

| Field | Notes |
|---|---|
| `snapshot_date` | End-of-period (we'd prefer **end of each business day**; monthly minimum). |
| `site_id` | Same join as above. |
| `aging_bucket` | 5 buckets: `0-30`, `31-60`, `61-90`, `91-120`, `120+`. |
| `outstanding_amount` | $ in that bucket on that snapshot. |

**Open questions:**

- Do you produce AR snapshots **daily** or only **month-end**? Daily is the dashboard goal; month-end is workable for v1.
- How do you treat **credit balances** — pulled out into a separate bucket?
- **Days in A/R** (rolling 90d denominator) — can you compute and send, or do we compute from daily collections + AR snapshot?

### 4.3 Doctor Scorecards — `fact_revenue_by_physician_mo`

Aggregation grain: **(month, state, physician_npi)**

> Per ADR-002, scorecards are exec-only. Doctors never see their own rank or peers'.

| Field | Notes |
|---|---|
| `month` | First-of-month. |
| `physician_npi` | Authoritative join to our `physicians` master. |
| `encounters_count` | Distinct encounters billed in the month. |
| `total_rvu` | Work RVU sum, for productivity tile. |
| `revenue_attributed` | Net revenue attributed to this MD's encounters in the month. |
| `documentation_timestamps` | Per-encounter `note_started_at` / `note_signed_at` aggregated to: median chart-turnaround hours, % notes signed within 24h. |

**Open questions:**

- Can you compute documentation/turnaround on your side, or do we need raw encounter timestamps? **Strong preference: aggregate on your side** — fewer hops, no PHI risk.
- For **net revenue per encounter** attribution, do you use the rendering provider, supervising provider, or a different rule? We want the rule documented.
- Any provider currently **not** being attributed correctly (e.g. locums billed under a supervising MD)? We need to know exclusions.

### 4.4 What we don't need (please don't send)

To shrink the HIPAA footprint: do **not** send any of these.

- Patient name, DOB, MRN, address, phone, email
- Member/subscriber/guarantor identifiers
- Per-claim line-level data (CPT codes per line, modifier per line, unit count per line)
- Denial codes (we're not building denial analytics — that's your job per scope)
- 835 line items with patient identifiers
- Charge-lag / clean-claim-rate / timely-filing — Ventra owns these metrics
- HCAHPS, patient satisfaction, portal adoption — out of scope

**Notes:**

---

## 5. SLA, freshness, reconciliation

| # | Question |
|---|---|
| 5.1 | What is the **expected freshness** — when does data for "yesterday" land in the feed? (e.g. by 6am CT next-day) |
| 5.2 | What's the **uptime SLA** for the delivery channel (SFTP / API)? Maintenance windows? |
| 5.3 | If a delivery is missed, what's the **detection + alert** flow on your side? Will you proactively notify HHA, or do we monitor? |
| 5.4 | How do you reconcile your aggregates against Athena source-of-truth? Daily? Monthly? Can you publish the reconciliation results to HHA? |
| 5.5 | Acceptance criterion HHA wants to commit to: for a chosen month, **Ventra's Finance report and HHA's Finance dashboard agree within $1,000** on collections, AR, and net revenue per site. Does that match your expected accuracy? If not, what's realistic? |
| 5.6 | If HHA's totals diverge from yours by more than the threshold, what's the **diagnostic process** — do we open a ticket? Who looks at it on your side? |
| 5.7 | **Late-posting handling** — when a payment posts in May for a service in March, where does it count in the dashboard view? (Cash basis = May; service-date basis = March.) Confirm Ventra's choice; we'll mirror it. |

**Notes:**

---

## 6. Operations and support

| # | Question |
|---|---|
| 6.1 | Single technical point-of-contact on your side for the data feed (name, email, on-hours)? |
| 6.2 | Escalation path for outages / data corruption? |
| 6.3 | **Sandbox / test environment** — can you give us a non-prod feed with synthetic data so we can build and test the ingestion job without touching real PHI? Strong ask. |
| 6.4 | Change management — when you update the schema (add a column, change a payer bucket), what's the notification window? We'd like ≥30 days' notice. |
| 6.5 | Onboarding kickoff — once we agree the shape, what's a realistic timeline for the first delivery to land in our test environment? Two weeks? Four? |
| 6.6 | Documentation — is there a **data dictionary** PDF / portal we can reference? (We'd like one if not — happy to draft one based on this meeting and have you confirm.) |

**Notes:**

---

## 7. Security and audit

| # | Question |
|---|---|
| 7.1 | For SFTP: do you support **IP allowlisting** on inbound? What's your standard set of source IPs we'd allowlist on our side? |
| 7.2 | For API: do you support **mTLS** in addition to OAuth? We can run mTLS via Azure Key Vault-managed certs. |
| 7.3 | **Audit trail** — do you log every read of HHA's data on your side? How long is that log retained, and is it accessible to HHA on request? |
| 7.4 | **Encryption** — are files encrypted at rest with HHA-specific keys, or shared infrastructure keys? |
| 7.5 | Anyone else on Ventra's side who has read access to HHA's data set (e.g. your client-success team)? Need a list for our compliance file. |

**Notes:**

---

## 8. Phase 2 timeline alignment

> We're targeting Phase 2 build (Weeks 7–14 in our roadmap). We've given ourselves 4–6 weeks once data starts flowing.

| # | Question |
|---|---|
| 8.1 | What date can you commit to for the **first sample delivery** to a HHA-test SFTP / sandbox? |
| 8.2 | What date for the **first prod delivery** of a single facility's actual data (e.g. Westside)? |
| 8.3 | What date for **all FL facilities** in the feed? |
| 8.4 | Is there a per-client onboarding fee or per-feed cost we should plan for? |

**Notes:**

---

## 9. Doctor Scorecards — sensitive sub-discussion

> Scorecards are the most politically sensitive deliverable. We don't want a misclassified physician number to leak.

| # | Question |
|---|---|
| 9.1 | If a physician is **terminated mid-month**, how does their final-month attribution work in your aggregate? |
| 9.2 | If we get a **dispute** ("my encounter count is wrong"), what's the back-trace — can we get an investigative drilldown without persistent PHI? |
| 9.3 | Locums / contractors billed under a supervising MD — confirm attribution rule. We'll document this on the dashboard tile so users know. |
| 9.4 | Are there providers Ventra is **not authoritative on** (e.g. employed by an entity Ventra doesn't bill for)? They go to the manual-entry path. |

**Notes:**

---

## 10. Action items to close the meeting

Aim to leave the meeting with **written agreement** (or a follow-up email with signature) on:

- [ ] BAA confirmed in writing
- [ ] Delivery shape decision: (a) / (b) / (c) / (d)
- [ ] Final field list for `fact_collections_daily`, `fact_ar_snapshot`, `fact_revenue_by_physician_mo`
- [ ] Sample/test feed date committed
- [ ] First-prod-delivery date committed
- [ ] Single Ventra technical POC named
- [ ] Schema change notification window agreed (≥30 days)
- [ ] Reconciliation acceptance criterion agreed ($1K threshold or alternative)
- [ ] Sandbox environment available — yes/no
- [ ] Audit log access on request — yes/no

---

## 11. After the meeting (HHA side)

1. Convert decisions into ADR-006 (Ventra ingestion contract).
2. Update `DASHBOARD_PLAN.md` § Phase 2 with the chosen shape — collapse the four-row decision tree into one row.
3. File the BAA copy in HHA Legal's compliance folder.
4. Open a tracking issue: `feat/ventra-ingest` — sub-issues per fact table.
5. Stand up a sandbox SFTP/API endpoint on our side for Ventra to deliver the first sample to.
6. Schedule the next checkpoint (4 weeks out) to verify sample data.

---

## 12. Reference (prep-only — don't read aloud)

**Our HIPAA firewall** (per ADR-001):

```text
for each raw record from Ventra:
    validate against expected shape
    strip any forbidden field (patient_*, member_id, mrn, subscriber_*, guarantor_*)
    log strip events to audit
aggregate in memory:
    by (date, state)             → fact_collections_daily
    by (snapshot_date, state, bucket) → fact_ar_snapshot
    by (month, physician_id)     → fact_revenue_by_physician_mo
write ONLY aggregates to Postgres
shred raw file from Blob after 30 days (lifecycle policy)
```

**Forbidden columns** (CI-enforced — never persisted):

- `claim_id`
- `encounter_id`
- `dos_per_line`
- `cpt_per_line`
- `patient_*`
- `mrn`
- `member_id`
- `subscriber_*`
- `guarantor_*`

**Source-system invariant:** every row from Ventra is tagged `source_system = 'VENTRA_FL_ATHENA'`. TX rows (manual) are tagged `source_system = 'HHA_TX_MANUAL'`. The two never mix.

**Scope split** (ADR-005): FL = Ventra-automated, TX = manual-only. Ventra has zero TX data.

---

*Owner: Akhil Reddy · Created 2026-05-04 for the 2026-05-05 meeting · v2*
