# Ventra follow-up email — Option A (pre-aggregated CSVs)

**Status:** READY TO SEND — body finalized 2026-05-11; paste into Outlook and update timestamp in the after-sending checklist once sent

**Recipient strategy:** broad visibility — full Ventra team + HHA exec sponsors. Pulled from Akhil's Outlook contacts; exact addresses to be captured at send time in the after-sending checklist.

**To (Ventra primary, Gilda's reply thread):**
- Gilda Romero — `gilda.romero@ventrahealth.com`
- Stephanie [last name + email TBC from Gilda's 2026-05-08 reply]

**Cc (Ventra extended — May 5 meeting attendees):**
- David Reck
- Suma Bhat
- Darshan Patel
- Plus anyone else from Ventra Client Success who was on the May 5 call

**Cc (HHA stakeholders):**
- HHA CEO (sponsor)
- HHA CFO (co-sponsor — finance dashboard is the use case)
- Crystal (operations — relays to Ventra on day-to-day matters)
- Sandy (manual finance entry counterpart)

**Bcc:**
- Akhil's personal email (thread backup if HHA email lapses; operational safety per the plan)

**From:** Akhil Reddy, IT Director, HHA Medicine — `areddy@hhamedicine.com`
**Subject:** Re: Standard Data Extract — proposal for the data shape that fits HHA's architecture
**Drafted:** 2026-05-11
**Context:** Reply to Gilda's 2026-05-08 message attaching the *Standard Data Extract — Files Specifications* spec. Asks Ventra to deliver three pre-aggregated CSVs (collections, AR snapshot, per-physician monthly) instead of the claim-level extract — keeps PHI off the wire and out of HHA's database, and aligns with the ADR-001 HIPAA firewall.
**Related docs:**
- [VENTRA_DATA_REQUIREMENTS.md](DATA_REQUIREMENTS.md) — the requirements doc sent before the 2026-05-05 meeting
- [VENTRA_QUESTIONS.md](QUESTIONS.md) — internal question bank
- [VENTRA_SCRIPT_30MIN.md](MEETING_SCRIPT_30MIN.md) — internal speaking script from the meeting

---

## Email body (copy into Outlook)

```text
Subject: Re: Standard Data Extract — proposal for the data shape that fits HHA's architecture

Hi Gilda, Stephanie,

Thank you for sending over the Standard Data Extract spec — the field
documentation and join logic are well laid out, and that gave my team a clear
picture of the underlying data model.

After walking through it with our architecture team, I'd like to propose a
different delivery shape that I think will be cleaner for both organizations.
HHA's data architecture is built so that patient identifiers never land in our
database — we work with pre-aggregated roll-ups only. This is a non-negotiable
constraint on our side, driven by our internal HIPAA posture and ratified by
our compliance team.

Rather than have HHA strip patient identifiers from a claim-level extract on
receipt — which means we'd briefly handle full PHI inside our ingestion
pipeline — I'd like to ask Ventra to produce three pre-aggregated daily CSVs
delivered via SFTP. Your team already computes these aggregations for your
own client-facing reporting; exposing them as a daily feed should be less work
on your side than re-deriving them on ours, and it keeps the BAA surface much
tighter for both organizations.

The three files, with field specifications, are below.

============================================================================
FILE 1 — collections_YYYY-MM-DD.csv  (daily collections)
============================================================================

Grain: one row per (calendar day, facility, payer class).
Calendar day = payment posting date, Central time.

  Column                    Type             Description
  date                      DATE             Calendar day, Central time
  facility_no               INT              Joins to your Facility file
  payer_class               STRING           commercial | medicare | medicaid
                                             | selfpay | other
  gross_charges             DECIMAL(18,2)    Sum of charges posted
  payments_received         DECIMAL(18,2)    Cash received that day
  contractual_adjustments   DECIMAL(18,2)    Contractual write-downs only
  write_offs                DECIMAL(18,2)    Patient + bad-debt write-offs
                                             (kept separate from contractual)
  payer_refunds             DECIMAL(18,2)    Refunds back to payers
                                             (takebacks / recoupments)
  patient_refunds           DECIMAL(18,2)    Refunds to patients
  net_revenue               DECIMAL(18,2)    Pre-computed by Ventra
                                             (please document the formula —
                                             see operational item 4 below)
  source_system             STRING           Your CB / MGS / VSQL / DUVA value

============================================================================
FILE 2 — ar_snapshot_YYYY-MM-DD.csv  (AR aging snapshot)
============================================================================

Grain: one row per (snapshot date, facility, aging bucket).
Daily snapshot preferred. Month-end is acceptable for v1 if daily is not on
your near-term roadmap.

  Column               Type             Description
  snapshot_date        DATE             End-of-business, Central time
  facility_no          INT              Joins to your Facility file
  aging_bucket         STRING           0-30 | 31-60 | 61-90 | 91-120 | 120+
                                        | credit
  outstanding_amount   DECIMAL(18,2)    $ in that bucket on that snapshot.
                                        Negative values only in the
                                        'credit' bucket.
  source_system        STRING           Your CB / MGS / VSQL / DUVA value

============================================================================
FILE 3 — physician_monthly_YYYY-MM.csv  (per-physician monthly)
============================================================================

Grain: one row per (month, physician NPI).
Written once at month close. If the month is later restated, please re-emit
the full month and we will UPSERT.

  Column                Type             Description
  month                 DATE             First day of month, Central time
  physician_npi         STRING(10)       NPI
  facility_no           INT              Primary attribution facility for
                                         that month
  encounters_count      INT              Distinct encounters billed under
                                         this provider that month
  total_rvu             DECIMAL(9,2)     Sum of RVUs
  total_work_rvu        DECIMAL(9,2)     Sum of Work RVUs
  revenue_attributed    DECIMAL(18,2)    Net revenue attributed to this
                                         provider's encounters
  source_system         STRING           Your CB / MGS / VSQL / DUVA value

(Plus a separate, one-time written note on your attribution rule —
"rendering provider" or "supervising provider" — so we know how to read the
row. Static documentation, not a per-row column.)

============================================================================
FOUR OPERATIONAL ITEMS (please apply to all three files)
============================================================================

1. Folder per day. Write to /YYYY-MM-DD/collections.csv,
   /YYYY-MM-DD/ar_snapshot.csv, /YYYY-MM-DD/physician_monthly.csv.
   New folder daily. No overwrites of prior-day files.

2. Manifest file last. Write a one-line _MANIFEST.csv as the LAST file each
   day, after all three (or one, on physician-monthly days) data files have
   landed. Our ingest job triggers only on the manifest, so we never pick up
   a half-complete drop.

3. Florida only. Please filter to HHA's Florida facility list at source
   before pushing. Texas operations run on a separate manual track inside
   HHA, and any TX rows reaching us would be flagged as an incident.

4. Net-revenue formula in writing. One paragraph documenting how net_revenue
   in File 1 is computed: which adjustment categories are deducted, whether
   the basis is payment posting date or date of service, how late-posted
   payments are handled. Without that, our monthly reconciliation against
   your client reports cannot close cleanly.

============================================================================
WHY THIS WORKS FOR BOTH SIDES
============================================================================

For Ventra: this surfaces aggregation logic you already maintain for your
own client reporting — no new logic, just a new delivery channel for it.
Your existing Standard Data Extract stays unchanged for your other clients.

For HHA: zero PHI on the wire, zero PHI in our database, single source of
truth for the aggregation logic (yours), and a much smaller ingestion
pipeline for our team to maintain. Monthly reconciliation becomes a direct
match against your client reports because the numbers came from the same
place.

============================================================================
NEXT STEP
============================================================================

What's feasible on your side, and on what timeline? I'd like to schedule a
30-minute working session when you're back from PTO to walk through the
three specs with your engineering lead, agree the field list line by line,
and lock a sample-feed date.

If a phased delivery is easier — for example, Files 1 and 2 in the first
release and File 3 a month later — that works well on our side too. We
build the dashboard tiles in waves.

Happy to send a calendar invite for the week of May 18 or May 25,
whichever fits your team's return — no rush from our side.

Thank you again for the time on the 5th, and for the spec.

Best regards,

Akhil Reddy
IT Director
HHA Medicine
areddy@hhamedicine.com
```

---

## After sending — checklist

- [ ] Sent on `__________` (fill in and commit when sent)
- [ ] Calendar invite for follow-up session sent to: __________
- [ ] Ventra confirmation logged in `VENTRA_QUESTIONS.md` decision tracker
- [ ] Any field-list changes from the call land in `VENTRA_DATA_REQUIREMENTS.md` § 3 (with commit reference)

## Anticipated responses + how to handle

| Ventra likely says | Read | Counter |
| --- | --- | --- |
| "Custom feed, separate SOW / additional cost" | They want to charge | If reasonable ($5–15K one-time), accept — saves weeks of solo dev |
| "Files 1 and 2 yes, File 3 needs roadmap" | Partial yes | Take it; build collections + AR tiles in v1, mark scorecard tiles "coming soon" |
| "We don't write manifest files" | Standard cron dump | Counter with fixed-time-window heuristic (e.g. "all files always land 02:00–02:30 CT") |
| "Can't filter FL-only at source" | Their job runs across all clients | Acceptable; we filter on receipt by joining to Facility file's ClientNo |
| "Send the formula? Sure, here it is: …" | Easy yes | Capture verbatim in `VENTRA_DATA_REQUIREMENTS.md` § 3.1 net_revenue row |
