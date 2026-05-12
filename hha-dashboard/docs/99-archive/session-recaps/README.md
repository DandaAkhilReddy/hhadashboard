# Session recaps

> **Audience:** Anyone reconstructing what was done on a specific date.

Per-session work summaries. Each one captures the PRs merged, decisions made, and follow-ups identified in a single working session. Useful for forensic trace-back ("when did we land X?") and onboarding-by-history.

These are point-in-time and **not** the source of truth for current state — they are history.

## Contents

| Date | File | What's in it |
|---|---|---|
| 2026-04-25 | [2026-04-25.md](2026-04-25.md) | Foundation sprint — PRs #9–#15: MSAL wiring, Doctor Scorecards stub, security bumps, Bicep scaffold |
| 2026-04-26 | [2026-04-26.md](2026-04-26.md) | Continuation |
| 2026-04-26 (session 12) | [2026-04-26-session-12.md](2026-04-26-session-12.md) | Further session artifact |

## Where the current state lives instead

- Prod deploy state → [../../../CLAUDE.md](../../../CLAUDE.md) § "Prod deploy state"
- Roadmap → [../../01-leadership/ROADMAP.md](../../01-leadership/ROADMAP.md)
- Architecture → [../../02-architecture/ARCHITECTURE.md](../../02-architecture/ARCHITECTURE.md)

## How to add a new session recap

This is **optional** and uncommon. We typically commit aggressively to git history; commit messages + PR descriptions are the primary record. A session recap makes sense only when:

- A working session crossed multiple PRs and decisions
- Future you (or a successor) would benefit from a narrative summary

File name: `YYYY-MM-DD.md` or `YYYY-MM-DD-session-N.md` if multiple per day.

---

*Back to [99-archive/README.md](../README.md) or [docs/README.md](../../README.md).*
