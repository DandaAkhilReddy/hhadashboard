# 99 — Archive

> **Audience:** Anyone investigating historical state or forensic evidence.

This folder holds **point-in-time** docs that aren't current truth but are useful for history. They are **NOT deleted** because:

1. They may be referenced from external systems (SharePoint, OneDrive, emails)
2. They document _why_ a decision was made even after the decision is superseded
3. Forensic audits depend on knowing the verified state at a moment in time

If a doc here is referenced from a current doc, the current doc should note it's an archived snapshot.

## Contents

- [PROJECT_STATE_AUDIT.md](PROJECT_STATE_AUDIT.md) — Verified forensic audit of the codebase as of 2026-04-26. Useful when investigating "what was actually built" vs "what was documented."
- [LOCAL_VERIFICATION_REPORT.md](LOCAL_VERIFICATION_REPORT.md) — Verification snapshot from local-dev validation
- [NEXT_BUILD_PLAN.md](NEXT_BUILD_PLAN.md) — Forward-looking plan written at a point in time; superseded by [../01-leadership/ROADMAP.md](../01-leadership/ROADMAP.md)
- [TOMORROW_PLAN.md](TOMORROW_PLAN.md) — Short-term planning note; superseded
- [session-recaps/](session-recaps/) — Per-session PR/work summaries (mid-2026)

## When to NOT use this folder

- Never write current-state docs here. They go in their tier (01–07).
- Never use these as the canonical answer to "what does the system do today." Use the live tier docs.

## Promotion / demotion

If a doc here becomes current truth again (rare), `git mv` it back to the appropriate tier. If a current doc becomes historical, `git mv` it here and update its content header to note "Archived from `/path/` on YYYY-MM-DD."

---

*Back to [docs/README.md](../README.md) for the full doc map.*
