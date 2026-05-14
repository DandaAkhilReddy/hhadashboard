# Testing — patterns, judge criteria, and the multi-agent coverage push

> Locked 2026-05-14 alongside the Phase 3 coverage uplift (PR #55,
> branch `feat/coverage-96`). Future test additions should follow the
> conventions here.

## Layout

```
hha-dashboard/
├── api/                      # FastAPI backend
│   ├── pyproject.toml        # pytest + coverage config
│   └── tests/                # all backend tests (api + jobs/*)
└── web/                      # Next.js frontend
    ├── vitest.config.ts      # vitest + v8 coverage + plugin-react
    ├── __tests__/
    │   ├── setup.ts          # conditional MSW + RTL cleanup
    │   ├── msw/              # typed MSW handlers + server
    │   ├── components/       # one .test.tsx per component (or grouped)
    │   └── pages/            # one .test.tsx per page
    └── e2e/                  # Playwright specs (chromium-only)
```

Backend tests live in `api/tests/` even when they exercise code in
`jobs/` (matches the existing convention; Postgres-using tests need
the api conftest fixtures).

## Test runners

| Surface | Runner | Local command | Coverage command |
|---|---|---|---|
| Backend Python | pytest 8.x + pytest-cov + pytest-randomly | `cd api && uv run pytest` | `uv run pytest --cov --cov-branch --cov-report=term-missing` |
| Frontend unit | vitest 4.x + happy-dom + RTL + MSW | `cd web && npm run test` | `npm run test:coverage` |
| Frontend E2E | Playwright (chromium) | `cd web && npm run e2e` | — |

CI (`.github/workflows/ci.yml`) runs all three on every PR + push to main.

## Coverage gate

Stair-stepped through Phase 3:

- **Phase 3 ship** (PR #55): gate at `--cov-fail-under=0` so the
  remaining DB-bound tests don't bounce in CI while local coverage is
  being lifted. Reports uploaded as 14-day artifacts.
- **Future stair-step** (raise as Stage 2 backend DB-mocking + Stage 4
  E2E expansion land): target `96` line / `85` branch in CI.

The local `pyproject.toml` keeps `fail_under = 0` so a single
`uv run pytest` for a specific file doesn't fail on the global
threshold. The CI workflow owns the gate via the `--cov-fail-under`
flag — that's the single source of truth.

## Test environment quirks

### Backend (Python)

- **Async event loop** — `asyncio_default_test_loop_scope = "session"`.
  asyncpg engines opened at module import (e.g. `app.deps.engine`) need
  a session-scoped loop so connections close on the loop they opened on.
- **Real Postgres** — the audit-trigger, V12/V13 validator, and
  fact-table integration tests hit a real database. Locally use
  `docker compose up -d`; CI provides the `postgres:16` service
  container. Tests that don't need DB use the `MagicMock(spec=...)` +
  `AsyncMock` pattern (see `tests/test_blob_service.py` for the canonical
  Azure SDK chain example).
- **pytest-randomly** — installed but disabled in CI default order
  (`-p no:randomly`). The J3 judge (Test Hygiene) opts in per batch via
  `pytest --randomly-seed=last` to assert order-independence.

### Frontend (TypeScript)

- **happy-dom** environment per-file via `// @vitest-environment happy-dom`
  annotation. Existing Node-only tests (auth/middleware/crypto/session/
  instrumentation) run unaffected by importing `setup.ts` conditionally.
- **RTL cleanup** — `cleanup()` runs in `afterEach` (wired in
  `__tests__/setup.ts`). Without it, multi-render tests hit
  "Found multiple elements" errors.
- **MSW** — `__tests__/msw/handlers.ts` types responses from
  `lib/api-types.ts`. Per-test overrides via `server.use(http.get(...))`.
  Server starts in `beforeAll`, resets in `afterEach`, closes in `afterAll`
  (all in `setup.ts`).
- **Recharts in tests** — happy-dom doesn't ship `ResizeObserver`. Stub
  it in `beforeAll` and mock `ResponsiveContainer` to a fixed-size div
  (see `__tests__/components/charts.test.tsx`).
- **`@vitejs/plugin-react` v6** required — vitest 4.x ships Vite 8, and
  plugin-react v4.x only supports Vite ≤ 7. v6 supports both.
- **Cross-file `vi.mock` state** — `vi.mock()` is scoped per file, but
  shared modules + module-level state (e.g. `Toast`'s subscribers Set)
  can leak between tests. Use unique fixture values + RTL cleanup; for
  fetch spies, reset via `vi.mocked(globalThis.fetch).mockReset()` in
  `beforeEach` before re-spying.

## The 5-judge gauntlet

Every test batch flows through five independent checks before commit.
J1 + J5 are mechanical (run inline); J2/J3/J4 are qualitative (use a
reviewer sub-agent for new patterns, inline review for follow-ups in
the same shape).

| Judge | Vetoes on |
|---|---|
| **J1 — Coverage Metrics** | line / branch / function % below the stair-step gate; per-file regression vs main; `# pragma: no cover` > 2% of new lines. |
| **J2 — Assertion Correctness** | `assert True` / `assert x is not None` traps; mock-asserts-self; snapshot tests with no content; tests that pass even if the SUT is deleted. |
| **J3 — Test Hygiene** | Order dependence; shared mutable state; missing `cleanup()` / `mockReset()`; `time.sleep` (use `freezegun` / `vi.useFakeTimers`); real network in unit tests (use MSW or `httpx.MockTransport`). |
| **J4 — Behavioral Completeness** | Every public function has a test; every error path has a `raises`/`toThrow`; every async boundary has a timeout test; every `if/elif/else` branch hit. |
| **J5 — Convention + ADR-001** | ruff / biome failures; `print()` instead of `structlog`; fixture data with names that look like real PHI; column names matching the ADR-001 forbidden denylist (`patient_*`, `mrn`, `claim_id`, `member_id`, `subscriber_*`, `guarantor_*`, `dos_per_line`, `cpt_per_line`); commit message not in `type(scope): description` format. |

### `# pragma: no cover` policy

Allowed only on these four cases, with a one-line justification comment:

1. `if TYPE_CHECKING:` blocks
2. `__repr__` methods
3. `raise NotImplementedError` abstract stubs
4. Defensive `except Exception:` around third-party SDK calls (Azure SDKs)

J1 reports total pragma count per commit. > 2% of new lines = veto.

## Batching strategy

| Tier | When | One commit covers |
|---|---|---|
| **A** | Default | One source module (router / service / component) — ~150-300 LOC of tests |
| **B** | Source file > 400 LOC | Split tests by concern across 2-3 commits (e.g. `main.py`: orchestration / startup / error handlers) |
| **C** | Infrastructure | Config + lockfile changes only — skip J2/J4 (nothing to assert) |

## Mock patterns

### Async DB session

```python
from unittest.mock import MagicMock, AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

session = MagicMock(spec=AsyncSession)
session.execute = AsyncMock(return_value=...)
session.commit = AsyncMock()
session.begin = MagicMock(__aenter__=AsyncMock(return_value=session), __aexit__=AsyncMock())
```

### Azure SDK chain (BlobServiceClient → ContainerClient → BlobClient)

See `api/tests/test_blob_service.py::_make_fake_client` for the canonical
factory. Each leaf method (`upload_blob`, `download_blob`, etc.) is an
`AsyncMock` so `await` in production code resolves cleanly. The
`service_client.close = AsyncMock()` is needed for the `finally: await
client.close()` cleanup paths to run.

### MSAL + Next.js navigation in frontend tests

```typescript
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  useSearchParams: () => ({ get: getMock }),
}));

vi.mock("@azure/msal-react", () => ({ useMsal: vi.fn() }));
vi.mock("@/lib/auth/msal-config", () => ({
  isMsalConfigured: vi.fn(),
  loginScopes: ["User.Read"],
}));
```

Mocks must precede page imports — vitest hoists `vi.mock` but the import
order still matters for clarity.

## What this push did NOT do

- **Did not refactor source.** Test-only changes. If a line of source
  was uncoverable, it stayed that way (with a documented `# pragma: no
  cover` if needed); the source change goes on a separate PR.
- **Did not add cross-browser E2E.** Playwright stays Chromium-only per
  audit ticket T9.
- **Did not aim for 100% line coverage.** Defensive code blocks
  (SQLAlchemy session error handlers, third-party SDK fall-throughs)
  use pragma rather than chase the last 1-2%.
- **Did not gate < 96 / 85.** The stair-step gate raise lives in a
  follow-up commit once Stage 2 + 4 land.

## Adding a test

1. Find the gap (`uv run pytest --cov ... --cov-report=term-missing` /
   `npm run test:coverage`).
2. Pick a Tier and create the test file (mirror source layout —
   `app/services/blob.py` → `tests/test_blob_service.py`).
3. Run inline J1 (coverage) and J5 (lint) checks locally.
4. If the file pattern is novel (first MSAL test, first chart test),
   spawn a `reviewer` sub-agent for J2/J3/J4. Otherwise inline review.
5. Commit with `test(<scope>): <description>` — one logical change.
6. Push, watch CI, and repeat.
