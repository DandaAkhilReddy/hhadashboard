# scripts/

> **Audience:** Whoever needs to operate on the docs themselves.

Tooling, not content. Currently one script.

## Contents

- [export-to-pdf.sh](export-to-pdf.sh) — Converts every markdown doc in this folder to PDF using `pandoc` + `mermaid-filter`. Produces a `pdf-export/` directory that mirrors the markdown folder structure (`01-leadership/*.pdf`, etc.). Upload the PDFs to SharePoint for leadership review.

## When to add a script here

When you need automation around the docs themselves — not the dashboard, not the app.

Examples (none built yet, but candidates):

- `link-check.sh` — run `markdown-link-check` across all `.md` files in CI
- `openapi-to-md.py` — regenerate `03-engineering/API_ENDPOINT_CATALOG.md` from a live `/openapi.json`
- `glossary-lint.py` — flag docs that use acronyms not in `07-reference/GLOSSARY.md`

Scripts for the application itself (DB seeding, deploy helpers) live at the repo root in `hha-dashboard/scripts/`, not here.

## Usage

See the header of each script for invocation. All scripts must be idempotent and safe to re-run.

---

*Back to [docs/README.md](../README.md) for the full doc map.*
