# Paycom Workforce Sync

Nightly cron that pulls workforce data (headcount, terminations, RVU
paychecks) from Paycom into the HHA dashboard's `facts` schema.

## Status: stub — waiting on API access

Paycom API enablement was requested with a 4–6 wk window. Until the
credential lands, this job is a stub:

- `main.py` checks `settings.paycom_configured` and exits 0 when False.
- `extractors/headcount_daily.py` and `extractors/rvu_paycheck.py` return
  `ExtractionResult(rows_written=0, warnings=["TODO: implement..."])`.

The cron is safe to schedule today — it logs a single info line and exits.

## When access lands

1. Drop the credential in Key Vault as `paycom-client-secret`,
   `paycom-client-id`, `paycom-api-base-url`.
2. Add the matching `@Microsoft.KeyVault(...)` references to the Container
   Apps Job env in `infra/modules/containerjobs.bicep` (or set as plain env
   for local dev).
3. Replace the body of `extract_headcount_daily` (and `extract_rvu_paycheck`)
   with the real Paycom API client + aggregation + upsert logic.
4. The cron entrypoint (`main.py`) needs no further change — once
   `paycom_configured` flips to True, the existing loop in `run()` runs the
   real extractors.

## Local dev

```bash
cd hha-dashboard/api
uv run python -m jobs.paycom_sync.main
```

With no Paycom env vars set, expect:

```
INFO jobs.paycom_sync :: Paycom API access not yet configured — exiting cleanly (no-op).
```

## Why a stub at all

Per F1 in the standing facts: *don't write speculative extractors*. If we
guessed the Paycom row shape today and Paycom's actual response doesn't
match, the speculative code is wasted. The stub gives us the cron skeleton
+ Bicep-deployable image + tests so the day access lands, the slot-in is
the function bodies only.
