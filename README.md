# HHA Dashboard (private)

Azure-only, HIPAA-first operations dashboard for HHA Medicine executive leadership.
Single Next.js + FastAPI + Postgres stack. Solo build with Claude Code.

## What's in this repo

```
.
├── hha-dashboard/                  # the actual codebase (Next.js + FastAPI + Postgres)
│   ├── CLAUDE.md                   # contract every Claude Code session reads
│   ├── README.md                   # stack, quick-start, scope
│   ├── QUICKSTART.md               # local dev commands
│   ├── docker-compose.yml          # Postgres + Mailpit + Adminer + Azurite
│   ├── api/                        # FastAPI backend (models, routers, services, alembic, tests)
│   ├── web/                        # Next.js 15 frontend (App Router, Tailwind, shadcn)
│   ├── jobs/                       # Container Apps Jobs (upload_ingest cron)
│   ├── scripts/                    # seed_sites.py, restore-drill, etc.
│   └── docs/                       # ADRs + Architecture.md
│
├── DASHBOARD_PLAN.md               # v5 master build plan (Azure-only, HIPAA-first)
├── UPLOAD_PIPELINE_PLAN.md         # ACTIVE ingestion pipeline (Upload → Blob → Cron)
├── SHAREPOINT_PLAN.md              # DEFERRED SharePoint companion (optional future phase)
├── SHAREPOINT_DEEP_DIVE.md         # DEFERRED deep dive
├── VENTRA_REPLY_DRAFT.md           # email draft to Ventra BI/Data contact (FL scope)
│
├── index.html                      # project hub — landing page for all docs
├── docs.html                       # generic markdown viewer (?file=path.md)
├── architecture.html               # specialized architecture viewer
├── UI_MOCKUP_v5.html               # interactive 6-tab dashboard mockup
└── hha_team_dashboard.html         # original v1 prototype (kept for reference)
```

## Quick start

See [hha-dashboard/QUICKSTART.md](hha-dashboard/QUICKSTART.md) for the full setup (docker compose + uv + npm).

Short version:

```bash
# Clone (private repo)
git clone https://github.com/DandaAkhilReddy/hhadashboard.git hha-project
cd hha-project/hha-dashboard

# Local services
docker compose up -d

# Backend
cd api && uv sync && uv run alembic upgrade head
uv run python ../scripts/seed_sites.py
uv run uvicorn app.main:app --reload

# Frontend (new terminal)
cd web && npm install && npm run dev
```

Open http://localhost:3000. Dev-stub auth: `Authorization: Dev admin` header. Real MSAL lands in Session 6.

## Browse the docs

```bash
# From this repo root:
python -m http.server 8765
# Then open http://localhost:8765/
```

Lands on `index.html` — cards for every planning doc + UI mockups + code artifacts.

## Contributor notes

- Read [hha-dashboard/CLAUDE.md](hha-dashboard/CLAUDE.md) before any change. It's the contract.
- Read [hha-dashboard/docs/adr/001-hipaa-data-classification.md](hha-dashboard/docs/adr/001-hipaa-data-classification.md) before touching data / ingestion.
- Commit aggressively per CLAUDE.md — small atomic commits, type(scope) format, every logical change.
- Never commit to `main` directly; always feature branch.
- Never add `Co-Authored-By` trailers.
- Never commit `.env` or real credentials. CI schema test blocks any column with `data_class: C` (PHI).

## License

Private. All rights reserved. HHA Medicine / Akhil Reddy.

## Built by

Danda Akhil Reddy — <akhilreddydanda3@gmail.com> — solo with [Claude Code](https://claude.com/claude-code).
