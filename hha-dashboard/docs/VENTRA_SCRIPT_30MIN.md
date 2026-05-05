# Ventra meeting — what to say (30-minute script)

> Print this, or keep it on a second monitor.
> Read **SAY** lines verbatim if you want; paraphrase if it feels stiff.
> Each block has a target end-time. If you're past it, skip the lines marked **\[skip if short\]** and move on.
> Take notes in the **WRITE DOWN** boxes — the recap email at the end pulls from these.

---

## 0:00 – 0:03 · Opening (3 min)

**SAY:**

> "Good morning everyone, thanks for taking the time today. I'm Akhil Reddy — IT Director and the architect on HHA's new internal operations dashboard.
>
> Quick frame for the next 30 minutes — three things I'd like us to land. First, confirm we're aligned on the Florida-only scope and the BAA status. Second, agree on how Ventra will deliver data to us — we have four shapes we can work with. Third, walk through the three rolled-up tables we need so we can sign off the field list together.
>
> I sent over a one-pager — `VENTRA_DATA_REQUIREMENTS.md` — yesterday. Did you get a chance to read it?"

**LISTEN FOR:**

- "Yes, we read it" → great, you can move faster through the field-list section.
- "Didn't see it" → "No problem, I'll walk you through. I'll forward it again right after this call."

---

## 0:03 – 0:08 · BAA + Florida scope (5 min)

**SAY:**

> "First question — is the HHA ↔ Ventra Business Associate Agreement signed and current? We need it confirmed in writing before any data flows."

**IF / THEN:**

- "Yes, current" → "Great — can you email a copy or a written confirmation to areddy@hhamedicine.com today?"
- "Not sure / will check" → "Can someone on your legal team confirm by end of week? This is gating Phase 2 on our side."
- "No / lapsed" → **red flag.** "What's the path to executing one? Who's the legal owner on your side?"

**SAY:**

> "Related — does the BAA cover Athenahealth as a downstream component? Since you're doing the Athena integration on our behalf, we need to know if our coverage flows through your BAA, or if HHA needs a direct BAA with Athena."

**IF / THEN:**

- "Covered downstream" → "Can you point me to the language? I'll document it for our compliance file."
- "Need separate Athena BAA" → "Can you facilitate that, or do we contact Athena directly?"

**SAY:**

> "And just to confirm scope — Ventra services HHA's Florida hospitals only, never Texas? Texas is on a separate manual track inside HHA."

**IF / THEN:**

- "Florida only, confirmed" → "Perfect. Could you send me the list of HHA-Florida facilities you have under contract — NPI plus facility name? We have eleven hospitals in our master and want to map them to yours."
- "Some Texas coverage" → "That contradicts our scope assumption. Let's flag this and follow up offline — I don't want to derail the meeting on it."

**WRITE DOWN:**

- BAA status: __________
- Athena chain: __________
- Florida-only confirmed: ☐ yes ☐ no

---

## 0:08 – 0:15 · Delivery shape — the big decision (7 min)

**SAY:**

> "OK, the biggest question of the meeting. We've designed our ingestion pipeline to handle four delivery shapes. We're not asking you to build a custom shape — we'll adapt to whatever's standard for you.
>
> Quick run-through of the four:
>
> - **Option A:** pre-aggregated CSV via SFTP — we drop it straight into our dashboards. Cleanest for both sides.
> - **Option B:** claim-level CSV via SFTP — we aggregate at our ingestion edge.
> - **Option C:** REST API with claim-level data — same idea as B, streamed.
> - **Option D:** raw 835 EDI files — same again, with an EDI parser on our side.
>
> Which of these is your standard delivery for clients of HHA's size?"

**IF / THEN:**

- **"Option A — pre-aggregated CSV monthly"** → "Can it be daily? Daily is what an exec dashboard needs. What's the lift to add daily?"
- **"Option B — claim-level CSV is our default"** → "We'd rather not handle claim-level. Two paths: can you pre-aggregate before delivery? Or, can you confirm in writing we can discard `claim_id`, `mrn`, `member_id`, and the patient identifiers on receipt without violating BAA?"
- **"Option C — we have an API"** → "OAuth or static API key? Rate limits? Pagination cursor? Sandbox available?"
- **"Option D — 835 EDI"** → "We'd prefer aggregated CSV over EDI — it's less code on our side. Is option A on the table, or is EDI your standard?"

**SAY:**

> "Cadence-wise, daily is what we need — posted by 7 a.m. Central time so the morning exec digest is current. Is that doable?"

**IF / THEN:**

- "Yes, daily by 7 a.m." → write it down.
- "Daily, but later in the morning" → "What's your earliest? We can adjust the digest time slightly."
- "Monthly only" → "Is daily on the roadmap? If not soon, we can run monthly for v1 and target daily after."

**SAY:** \[skip if short\]

> "On auth — for SFTP, are you on SSH-key plus IP allowlist? For API, OAuth client credentials or static key?"

**WRITE DOWN:**

- Delivery shape: ☐ A ☐ B ☐ C ☐ D
- Cadence: __________
- Auth: __________

---

## 0:15 – 0:22 · Field grain — the three tables (7 min)

**SAY:**

> "Three rolled-up tables we need. You've got the spec in the doc I sent. Let me walk through each at high level, and you tell me what's feasible."

### Table 1 of 3 — daily collections

**SAY:**

> "Number one — daily collections. Grain is one row per day, per site, per payer class. Fields: gross charges, payments received, contractual adjustments, write-offs, payer refunds, patient refunds, net revenue. Can you deliver at that grain, or only coarser?"

**IF / THEN:**

- "Yes, that grain" → "Great. One question — net revenue, do you pre-compute it or do we derive? If you pre-compute, can you send the formula in writing? Otherwise our reconciliation won't close."
- "Coarser only" → "What's the lift to add daily and payer split? Config change or new ETL?"

**SAY:**

> "One more on collections — do you post payments at the **account level** or the **encounter level**? It affects how our per-physician encounter counts reconcile to total collections."

### Table 2 of 3 — AR snapshot

**SAY:**

> "Number two — AR snapshot. Grain is one row per snapshot date, per site, per aging bucket. Standard five buckets — 0 to 30, 31 to 60, 61 to 90, 91 to 120, and 120-plus — plus a separate `credit` bucket for credit balances held as a negative number. We don't want credit balances folded into 0–30. Daily snapshot preferred, month-end is workable for v1."

**IF / THEN:**

- "Daily snapshot" → "What time does the snapshot run? End-of-business Central?"
- "Month-end only" → "Workable. Is daily on the roadmap?"

### Table 3 of 3 — per-physician monthly

**SAY:**

> "Number three — per-physician monthly. The core fields are encounters count, total RVU, and attributed revenue. Two more fields would be great if you have them — chart-turnaround median hours, and percent of notes signed within 24 hours — but I know those come from EMR documentation events, not billing events. If you don't capture them, we'll mark those tiles 'coming soon' on the dashboard and pursue Athena directly. No worries either way."

**IF / THEN:**

- "Yes, we have the documentation timestamps" → "Excellent. What's your provider-attribution rule — rendering provider, supervising provider, or another method?"
- "No, only billing events" → "No problem, we'll handle that separately. What's your attribution rule for the billing-side fields?"

**WRITE DOWN:**

- Collections grain feasible: ☐ yes ☐ no ☐ partial
- Posting grain: ☐ account-level ☐ encounter-level
- AR snapshot cadence: __________
- Physician fields available: __________
- Attribution rule: __________

---

## 0:22 – 0:27 · Operations (5 min)

**SAY:**

> "Five quick operational items. One — who is the single technical point of contact for this feed on your side? Name and email."

**IF / THEN:**

- A specific person → write it down.
- "Client success team" → "Can you name a specific human? Group inboxes drop tickets — I'd rather have one person to call when something breaks."

**SAY:**

> "Two — sandbox or test environment with synthetic data. Do you have one we can build the ingestion job against without touching real PHI?"

**IF / THEN:**

- "Yes, sandbox available" → "Can you send 2 to 3 sample files this week? We'll start coding the parser in parallel."
- "No sandbox, but a redacted real client file" → that works; ask for the file.
- "No / not available" → flag for follow-up; we'll work around it.

**SAY:**

> "Three — what date can you commit to for the first sample feed to a HHA test endpoint? I want a specific calendar date, not a few-weeks estimate. And what date for the first prod facility?"

> Push for specific dates. Write them down.

**SAY:**

> "Four — reconciliation. Our acceptance threshold is, for any given month, your finance report and our dashboard agree within $1,000 per site, or 0.5 percent of monthly collections per site, whichever is greater. Does that match your expected accuracy?"

**IF / THEN:**

- "Sure, that's reasonable" → write it down, confirm in the recap email.
- "We're more like one to two percent" → negotiate; ask what drives the variance — rounding, timing, source-of-truth ambiguity?

**SAY:** \[skip if short\]

> "Five — month boundary. We're using the last calendar day in Central Time, with payment posting date as the key date. Is that how you report?"

**WRITE DOWN:**

- POC name + email: __________
- Sandbox: ☐ yes ☐ no
- Sample-feed date: __________
- First-prod-delivery date: __________
- Reconciliation threshold: $______ / ____%
- Month boundary aligned: ☐ yes ☐ no

---

## 0:27 – 0:30 · Wrap (3 min)

**SAY:**

> "Great, that's the substance. Let me run through what we landed:
>
> - BAA status: [recap]
> - Delivery shape: [recap]
> - Cadence: [recap]
> - POC: [name]
> - Sample-feed date: [date]
> - Reconciliation threshold: [number]
>
> I'll send a recap email by end of day with action items — who sends what to whom, and by when. Subject line will be 'HHA × Ventra dashboard data feed — action items from May 5'.
>
> Let's also schedule a checkpoint in two weeks to verify the sample feed has landed. Does May 19 work for everyone's calendars?
>
> One last question — what do you need from us to make this successful? Anything blocking on your side I can help unblock?"

> Whatever they mention here is gold. Note it down — that's often the most useful 60 seconds of the meeting.

**SAY (closing):**

> "Thanks everyone. Looking forward to building this together."

---

## Tone notes (read before the meeting)

- Confident and collaborative, not adversarial. HHA is the customer, but they're the experts on their data.
- If they push back on anything specific, agree to follow up offline rather than negotiating in the meeting. "Let me come back to you on that by Friday" is a fine answer.
- If you don't know the answer to something, say so. Don't bluff. Bluffing breaks trust faster than admitting a gap.
- Speak slower than you think you need to. Most vendor calls run hot when one side is rushing.
- Take notes during *their* answers, not yours. Pause after each question for two beats — let them think.
- If David or Suma start talking about Ventra's roadmap or capabilities, let them. Don't interrupt to get back on script — those tangents often reveal what they actually care about.

---

## If you're running long (skip in this order)

1. Block 2 — auth question (Q on SSH/OAuth) → write it in the recap email.
2. Block 3 — posting grain follow-up → in the recap email.
3. Block 4 — month-boundary alignment question → in the recap email.
4. Block 5 — "what do you need from us" question → only skip as a last resort; this is high-value.

If you need to fast-forward, say: *"In the interest of time, let's park this and I'll send it in the recap email. Moving on to ___."*

---

## Recap email template (send by EOD)

```text
Subject: HHA × Ventra dashboard data feed — action items from 2026-05-05

Hi David, Suma, Darshan,

Thanks for the time today. Quick recap of what we agreed and what's next.

Decisions landed:
- Delivery shape: [A / B / C / D]
- Cadence: [daily / weekly / monthly]
- BAA status: [confirmed / pending action]
- Reconciliation threshold: $X per site or Y% of monthly collections, whichever is greater

Action items:

VENTRA:
- [ ] Send written BAA confirmation (and Athena coverage clarification) by ____
- [ ] Send list of HHA-FL facilities under contract (NPI + facility name) by ____
- [ ] Send 2–3 sample feed files to areddy@hhamedicine.com by ____
- [ ] Confirm net_revenue formula in writing by ____

HHA:
- [ ] Stand up sandbox SFTP endpoint by ____
- [ ] Share HHA facility master (NPI + name + service line) by ____

Next checkpoint: 2026-05-19, 30 min, same format.

Open items deferred to follow-up:
- [list anything skipped during the meeting]

Thanks,
Akhil Reddy
IT Director, HHA Medicine
areddy@hhamedicine.com
```

---

*Owner: Akhil Reddy · Created 2026-05-05 for the same-day meeting · v1*
