# HHA Dashboard — Data Requirements from Ventra

**Prepared by:** HHA Medicine IT
**Author:** Akhil Reddy, IT Director · areddy@hhamedicine.com
**Date:** 2026-05-04
**For:** Ventra Health — David Reck, Suma Bhat, Darshan Patel, Client Success
**Companion to:** the 30-minute review meeting on 2026-05-05

---

## 1. What we are building

HHA Medicine is building an internal executive dashboard covering operations, finance, clinical quality, workforce, and per-physician scorecards. Phase 1 (manual census entry by site leaders) is live in our Azure environment. Phase 2 — automated finance metrics and Doctor Scorecards — depends on a structured, recurring data feed from Ventra.

The dashboard's primary users are HHA exec leadership (CEO, CFO, CMO, COO) plus a small set of named department owners. Total user count is under twenty. There is no public access and no patient-facing surface.

---

## 2. Scope

The data feed covers **HHA's Florida hospitals only**. Texas operations are on a separate manual-entry track inside HHA and are not part of this feed. If any Texas records ever appear in a Ventra delivery, that is a flag for both sides to investigate.

The feed is **aggregate-only**. HHA does not need or want claim-level, patient-level, or encounter-level rows in our database. Anything below an aggregate grain — claim IDs, MRNs, member IDs, patient names, dates of birth, diagnosis codes per line, CPT codes per line — is out of scope.

If your standard delivery shape includes any of those fields, our ingestion pipeline strips them at the edge before any persistence. We are happy to walk you through the pattern. This shrinks the HIPAA surface area for both organizations.

---

## 3. The three data sets we need

We need three rolled-up tables. Grain and fields are below; column types are flexible.

### 3.1 Daily collections — `fact_collections_daily`

**Grain:** one row per (date, site, payer class).

| Field | Description |
| --- | --- |
| `date` | Calendar day, Central time, posting date for the payment. |
| `site_id` | Joinable to HHA's master facility list (NPI + facility name). |
| `payer_class` | One of `commercial`, `medicare`, `medicaid`, `selfpay`, `other`. Carrier-level detail is not needed. (Industry standard term; we previously called this `payer_bucket` — same concept.) |
| `gross_charges` | Sum of charges posted that day. |
| `payments_received` | Cash received that day. |
| `contractual_adjustments` | Contractual write-downs (e.g. CO-45 in 835 terms). |
| `write_offs` | Patient-side or bad-debt write-offs (PR-26, CO-96, etc.). Kept separate from contractual so reconciliation can isolate write-off exposure. |
| `payer_refunds` | Refunds or takebacks paid back to a payer (recoupments). |
| `patient_refunds` | Refunds issued to patients for credit balances. |
| `net_revenue` | Pre-computed by Ventra (preferred). If pre-computed, please send the exact formula in writing — otherwise reconciliation in §9 will not close. If not pre-computed, HHA derives at ingestion from the fields above. |

**Open questions for Ventra:**

- Can you deliver at this grain, or only at a coarser level (e.g. monthly with no payer split)? If coarser is the standard, what is the lift to add daily + payer split?
- Posting grain — do you post payments at the **account level** (then allocate to encounters in a second step) or at the **encounter level**? Affects how the per-physician encounter counts in §3.3 reconcile to total collections in §3.1.
- Holiday and weekend handling — does the daily extract run 7 days/week, or business days only? What is your alerting behavior on a missed drop?

### 3.2 AR snapshot — `fact_ar_snapshot`

**Grain:** one row per (snapshot_date, site, aging bucket).

| Field | Description |
| --- | --- |
| `snapshot_date` | End-of-period. Daily preferred; month-end is workable for v1. |
| `site_id` | Same join as above. |
| `aging_bucket` | Six buckets: `0-30`, `31-60`, `61-90`, `91-120`, `120+`, plus a separate `credit` bucket for credit balances (held as negative `outstanding_amount`). HHA's expectation is that credit balances do **not** get folded into `0-30` or distributed across other buckets. |
| `outstanding_amount` | Dollars in that bucket on that snapshot. Negative values only in the `credit` bucket. |

**Open questions for Ventra:**

- Daily AR snapshots — are these something you produce today for other clients, or month-end only?
- Days in A/R (rolling 90-day denominator) — can you compute and send, or do we derive from the daily collections plus AR snapshot?

### 3.3 Per-physician monthly — `fact_revenue_by_physician_mo`

**Grain:** one row per (month, physician).

**Core fields (RCM-side data, expected from Ventra):**

| Field | Description |
| --- | --- |
| `month` | First day of the month, Central time. |
| `physician_npi` | Authoritative join to HHA's physician master. |
| `encounters_count` | Distinct encounters billed in the month under this provider's attribution. |
| `total_rvu` | Sum of work RVUs for the month. |
| `revenue_attributed` | Net revenue attributed to this provider's encounters in the month. |

**Provisional fields (EMR-side, only if Ventra captures them from Athena):**

| Field | Description |
| --- | --- |
| `chart_turnaround_median_hours` | Median hours from `note_started_at` to `note_signed_at`, aggregated server-side. |
| `pct_notes_signed_within_24h` | Percent of month's notes signed within 24 hours of encounter close. |

These two are EMR-side metrics, not RCM-side. We understand Ventra's primary integration with Athena is for billing events, not documentation events. If you do not capture EMR documentation timestamps, we will mark these tiles "coming soon" on the dashboard and pursue a separate Athena integration on the HHA side. No worries either way.

**Open questions for Ventra:**

- Are the documentation timestamps available in your data, or only billing events?
- What is your provider attribution rule — rendering provider, supervising provider, or another method?
- Are there providers who are not currently attributed correctly (for example, locums billed under a supervising MD)?

---

## 4. Delivery options HHA can support

We have built our ingestion job to handle any of the following shapes. Please pick the one that fits Ventra's standard delivery process best — we will adapt to your shape, not the other way around.

| Option | Shape | HHA's processing |
| --- | --- | --- |
| (a) | Pre-aggregated CSV via SFTP | Drop directly into our fact tables. Cleanest for both sides. |
| (b) | Claim-level CSV via SFTP | We aggregate at the ingestion edge. Claim-level fields are read once, summed in memory, discarded. |
| (c) | REST API with claim-level data | Same edge-aggregation, but streamed with cursor-based pagination. |
| (d) | Raw 835 EDI remittance files (inbound from payers via Ventra) | Same edge-aggregation, with an EDI parser added on our side. |

For options (b), (c), and (d), HHA's ingestion job persists only aggregates to the database. Raw files land in an Azure Blob container with a 30-day lifecycle policy and are then deleted.

Note on EDI: option (d) refers to 835 remittance advice forwarded from payers via Ventra. We are not asking for 837 claims (those are outbound to payers and we have no use for them downstream).

---

## 5. Cadence and freshness

- **Preferred cadence:** daily, posted by 7 a.m. Central time so the morning exec digest is current.
- **Acceptable v1:** weekly, with a path to daily on a roadmap.
- **Re-statements / corrections:** when a claim posts, voids, then re-posts later, please confirm whether deltas are emitted, full periods are re-emitted, or rows are flagged with a `corrected_record` indicator. Any of those works; we just need to know which.

---

## 6. Compliance and security expectations

| Item | Expectation |
| --- | --- |
| Business Associate Agreement | Confirm whether the HHA ↔ Ventra BAA is currently in place. If yes, please share a written copy or confirmation. If not, we'd like to agree on a path to execute one before the first feed. Also clarify whether Athenahealth is covered downstream under the Ventra BAA or whether a separate HHA ↔ Athena BAA is needed. |
| Authentication (SFTP) | SSH key auth + IP allowlist on inbound. |
| Authentication (API) | OAuth 2.0 client credentials preferred over static API keys. mTLS welcome. |
| Encryption | At rest on your side; in transit via TLS 1.2+. |
| Audit log | Read access to HHA data logged on your side and accessible to HHA on request. |
| Data retention | Documented retention period and deletion procedure on contract termination. |

---

## 7. Timeline target

| Milestone | Target | Owner |
| --- | --- | --- |
| Delivery shape agreed | 2026-05-05 (this meeting) | Both |
| BAA copy + Athena coverage confirmed in writing | within 1 week of meeting | Ventra |
| List of HHA-FL facilities **Ventra has under contract** (NPI + facility name) shared with HHA, so HHA can reconcile against its master | within 1 week of meeting | Ventra |
| HHA's full facility master (NPI + facility name + service line) shared with Ventra for ID mapping | within 1 week of meeting | HHA |
| Sample / sandbox feed delivered | within 2–4 weeks of meeting | Ventra |
| First production delivery (single facility) | within 6–8 weeks | Ventra |
| All FL facilities flowing | within 10–12 weeks | Ventra |

---

## 8. What HHA will do on our side

- Stand up a sandbox SFTP endpoint (or API client) to receive the first sample delivery.
- Provide the HHA facility master (NPI + facility name + service line) for ID mapping.
- Confirm the field list for each of the three fact tables before the production feed starts.
- Run a monthly reconciliation between our dashboard totals and Ventra's Finance reports.
- Open a single Microsoft Teams or email channel for data-feed support tickets.

**HHA technical point of contact (feed owner):** Akhil Reddy, IT Director — areddy@hhamedicine.com.
**HHA escalation:** any issue not resolved within 2 business days at the feed-owner level escalates to HHA executive sponsorship.

---

## 9. Reconciliation

HHA's acceptance criterion: for any chosen month, the Finance dashboard agrees with Ventra's Finance report **within $1,000 per site, or 0.5% of monthly collections per site, whichever is greater**, on collections, AR balance, and net revenue.

To make reconciliation possible, we need to agree on a single month-boundary definition:

- **Month boundary:** the last calendar day of the month, in Central time.
- **Key date:** payment posting date (not service date and not deposit date).

If either of those is different in your standard reporting, please flag it — diverging timezone or key-date conventions are a common source of 1–2-day slippage in monthly totals, which alone can push reconciliation outside the threshold.

If the threshold itself is not realistic, propose an alternative based on Ventra's expected accuracy.

---

## 10. What we are asking from this 30-minute meeting

1. Confirm the BAA chain (HHA ↔ Ventra ↔ Athena).
2. Pick one of the four delivery options in §4.
3. Name a single Ventra technical point of contact for the feed.
4. Commit a date for the first sample delivery.
5. Agree (or counter) the reconciliation threshold in §9.

Anything not landed in the meeting becomes a follow-up email — not a blocker for starting implementation on items that did land.

---

## 11. Out of scope

So Ventra's team can size the work accurately, here is what HHA is not building and does not need:

- Denial analytics, claim-level browsers, 835 line items, appeals workflow — Ventra owns RCM end-to-end.
- Charge lag, timely filing rate, clean claim rate, denial overturn, prior-auth approval, coding accuracy.
- Patient satisfaction (HCAHPS), portal adoption, payment plans, self-pay collections workflow.
- Cost-side P&L, per-site margin, investor view.
- Real-time refresh (daily is fine).
- Texas data — TX is on a separate HHA-internal manual track.

---

## 12. Contact

**Akhil Reddy** — IT Director, HHA Medicine
Email: areddy@hhamedicine.com

Thank you for the time on the 5th. Looking forward to a productive conversation.

---

*Document version: v1 · 2026-05-04*
