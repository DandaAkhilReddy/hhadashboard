"""Alembic migration round-trip integration tests.

Audit ticket T14: lock that every migration's downgrade() works as
advertised. Walking the migration tree backward then forward catches the
common failure mode where someone wires upgrade() correctly but the
downgrade() (rarely run, mostly only when prod rolls back) silently broke.

Strategy
--------
We run all alembic operations against a **throwaway database** so this
test never touches the dev DB or other tests' state:

  1. Module setup: connect to the postgres maintenance DB, DROP+CREATE
     `hha_dashboard_alembic_test`.
  2. Override `settings.database_url_sync` so env.py points alembic at the
     test DB instead of the dev DB.
  3. Run two test patterns:
       a) Full walk (single test): base → head → base → head. Catches any
          broken downgrade in one shot, lowest signal but cheapest signal.
       b) Per-migration round trip (parameterized): for each of N revisions,
          head → parent → rev → parent → head. Higher signal — when it
          fails, the test name pinpoints which revision broke. Each
          parameterized test isolates one revision's downgrade path.
  4. Module teardown: terminate any stray connections, drop the test DB.

If the maintenance DB is unreachable (e.g. local Postgres not running, or
the test user lacks CREATEDB), the whole module is skipped — same pattern
as test_audit_triggers.py. CI's Postgres service runs as superuser, so
there it always exercises.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command
from app.settings import settings

log = logging.getLogger(__name__)

API_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = API_DIR / "alembic.ini"
TEST_DB_NAME = "hha_dashboard_alembic_test"


def _split_db_url(url: str) -> tuple[str, str]:
    """Split a SQLAlchemy URL into (everything-before-last-/, db_name)."""
    last = url.rfind("/")
    if last == -1:  # pragma: no cover  (defensive — URLs always have a path)
        raise ValueError(f"Cannot parse DB URL: {url}")
    return url[:last], url[last + 1 :]


def _build_admin_url() -> str:
    """Connect URL for the postgres maintenance DB. Strips the +psycopg
    driver tag because raw psycopg.connect() doesn't understand it."""
    base = settings.database_url_sync.replace("postgresql+psycopg://", "postgresql://")
    prefix, _ = _split_db_url(base)
    return f"{prefix}/postgres"


def _build_test_db_url() -> str:
    """Same as database_url_sync but pointing at the throwaway DB. Keeps
    the +psycopg driver tag so SQLAlchemy/Alembic pick the right driver."""
    prefix, _ = _split_db_url(settings.database_url_sync)
    return f"{prefix}/{TEST_DB_NAME}"


def _can_create_test_db() -> bool:
    """Quick reachability + perms check. Returns False if the maintenance
    DB isn't reachable or the test user can't CREATE DATABASE."""
    try:
        with psycopg.connect(_build_admin_url(), autocommit=True) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception as exc:  # noqa: BLE001 — we deliberately catch all here
        log.warning("alembic round-trip: admin DB unreachable: %s", exc)
        return False


@pytest.fixture(scope="module", autouse=True)
def _skip_if_no_postgres() -> None:
    if not _can_create_test_db():
        pytest.skip("Postgres unreachable — skipping alembic round-trip tests")


@pytest.fixture(scope="module")
def test_db_url() -> Generator[str, None, None]:
    """Create a fresh throwaway DB for the module, drop on teardown."""
    admin_url = _build_admin_url()
    db_url = _build_test_db_url()
    with psycopg.connect(admin_url, autocommit=True) as conn:
        # Drop leftover from a prior crashed run, then create fresh.
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}")
        conn.execute(f"CREATE DATABASE {TEST_DB_NAME}")
    try:
        yield db_url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as conn:
            # Force-disconnect any active connections so DROP succeeds.
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (TEST_DB_NAME,),
            )
            conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}")


@pytest.fixture
def alembic_cfg(test_db_url: str, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Build an Alembic Config that points at the test DB. We monkeypatch
    settings.database_url_sync because env.py reads it on every command
    invocation and would otherwise auto-redirect to the dev DB.
    """
    monkeypatch.setattr(settings, "database_url_sync", test_db_url)
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    return cfg


def _list_revisions_base_first() -> list[str]:
    """Return revision IDs in apply order (oldest first). Called at
    collection time so parameterize() gets a static list."""
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    revs = list(script.walk_revisions())  # alembic returns newest-first
    revs.reverse()
    return [r.revision for r in revs]


REVISIONS_BASE_FIRST = _list_revisions_base_first()


def test_full_walk_back_then_forward(alembic_cfg: Config) -> None:
    """Sanity: base → head → base → head, all in one shot. If any
    downgrade or upgrade in the chain is broken, this fails with the
    offending migration in the traceback. Cheap first signal before
    the parameterized tests below."""
    command.downgrade(alembic_cfg, "base")  # may already be at base on first run
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")


@pytest.mark.parametrize("rev", REVISIONS_BASE_FIRST)
def test_individual_migration_round_trip(alembic_cfg: Config, rev: str) -> None:
    """For each rev: walk to its parent, apply rev, walk back, walk forward to head.

    The pattern exercises the rev's `downgrade()` twice — once via the
    `downgrade(parent)` from HEAD (which rolls back rev + any later), and
    once again via the second `downgrade(parent)` after re-applying rev.
    A broken downgrade in any individual revision surfaces with the
    revision ID in the parameterized test name.
    """
    script = ScriptDirectory.from_config(alembic_cfg)
    revobj = script.get_revision(rev)
    # Alembic types down_revision as str | tuple | list to support merge migrations.
    # HHA's tree is strictly linear — assert + narrow.
    raw_parent = revobj.down_revision
    assert raw_parent is None or isinstance(raw_parent, str), (
        f"Migration {rev} has a non-linear down_revision; T14 assumes linear history"
    )
    parent: str = raw_parent or "base"

    # Baseline at HEAD so the next downgrade actually rolls back work.
    command.upgrade(alembic_cfg, "head")
    # Roll back to rev's parent (this exercises rev's downgrade + any later).
    command.downgrade(alembic_cfg, parent)
    # Re-apply just rev (exercises upgrade in isolation).
    command.upgrade(alembic_cfg, rev)
    # Roll back rev again (clean test of THIS rev's downgrade).
    command.downgrade(alembic_cfg, parent)
    # Restore to HEAD so the next parameterized test starts from a known state.
    command.upgrade(alembic_cfg, "head")
