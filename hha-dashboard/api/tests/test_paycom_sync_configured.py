"""Extra paycom_sync tests covering the **configured** branch of
``run()`` in ``jobs/paycom_sync/main.py``.

The existing ``tests/test_paycom_sync_stub.py`` covers the no-op branch
(``settings.paycom_configured = False``). This file fills the gap: when
Paycom credentials ARE present, ``run()`` must:

1. Set the audit-context UPN to ``paycom-sync@hhamedicine.com``.
2. Iterate every entry in ``ROUTES``, opening a fresh ``SessionLocal()``
   per extractor (so a failure in one doesn't roll back the others).
3. Commit each session before the next extractor runs.
4. Aggregate ``rows_written`` + prefix each warning with the extractor
   name, then log a summary.
5. Return exit code ``0`` on success.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from jobs.paycom_sync.extractors import ExtractionResult
from jobs.paycom_sync.main import run


class _FakeSessionFactory:
    """Stand-in for ``app.deps.SessionLocal`` that yields a MagicMock
    session each time it's used as an async context manager.

    Records every yielded session so tests can assert on commit calls.
    """

    def __init__(self) -> None:
        self.opened: list[MagicMock] = []

    def __call__(self) -> _FakeSessionFactory:
        # SessionLocal() returns a context-manager-able object.
        return self

    async def __aenter__(self) -> MagicMock:
        db = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        self.opened.append(db)
        return db

    async def __aexit__(self, *_args) -> None:
        return None


async def test_run_configured_iterates_every_extractor_and_commits(
    monkeypatch,
) -> None:
    """Every ROUTES entry runs exactly once, each in its own session, each
    committed."""
    factory = _FakeSessionFactory()
    monkeypatch.setattr("jobs.paycom_sync.main.SessionLocal", factory)

    captured_upn: list[str] = []
    monkeypatch.setattr(
        "jobs.paycom_sync.main.set_current_upn",
        lambda upn: captured_upn.append(upn),
    )

    headcount = AsyncMock(return_value=ExtractionResult(rows_written=5, warnings=[]))
    rvu = AsyncMock(return_value=ExtractionResult(rows_written=8, warnings=[]))
    monkeypatch.setattr(
        "jobs.paycom_sync.main.ROUTES",
        {"headcount_daily": headcount, "rvu_paycheck": rvu},
    )

    fake_settings = MagicMock()
    fake_settings.paycom_configured = True
    monkeypatch.setattr("jobs.paycom_sync.main.settings", fake_settings)

    exit_code = await run()

    assert exit_code == 0
    # Both extractors fired once, each receiving its own (fresh) session.
    headcount.assert_awaited_once()
    rvu.assert_awaited_once()
    assert len(factory.opened) == 2
    # Each session committed exactly once
    for db in factory.opened:
        db.commit.assert_awaited_once()


async def test_run_sets_audit_upn_to_service_account(monkeypatch) -> None:
    """The service UPN must propagate so audit triggers attribute writes
    to ``paycom-sync@hhamedicine.com`` rather than the generic
    ``__system__`` sentinel."""
    factory = _FakeSessionFactory()
    monkeypatch.setattr("jobs.paycom_sync.main.SessionLocal", factory)

    captured: list[str] = []
    monkeypatch.setattr(
        "jobs.paycom_sync.main.set_current_upn",
        lambda upn: captured.append(upn),
    )

    monkeypatch.setattr(
        "jobs.paycom_sync.main.ROUTES",
        {
            "headcount_daily": AsyncMock(
                return_value=ExtractionResult(rows_written=0, warnings=[])
            ),
        },
    )
    fake_settings = MagicMock()
    fake_settings.paycom_configured = True
    monkeypatch.setattr("jobs.paycom_sync.main.settings", fake_settings)

    await run()

    assert captured == ["paycom-sync@hhamedicine.com"]


async def test_run_aggregates_warnings_with_extractor_name_prefix(
    monkeypatch,
) -> None:
    """Each warning is rewritten as ``"<extractor_name>: <warning>"``."""
    factory = _FakeSessionFactory()
    monkeypatch.setattr("jobs.paycom_sync.main.SessionLocal", factory)
    monkeypatch.setattr("jobs.paycom_sync.main.set_current_upn", lambda _: None)

    monkeypatch.setattr(
        "jobs.paycom_sync.main.ROUTES",
        {
            "headcount_daily": AsyncMock(
                return_value=ExtractionResult(
                    rows_written=2, warnings=["site X missing in roster"]
                )
            ),
            "rvu_paycheck": AsyncMock(
                return_value=ExtractionResult(
                    rows_written=3,
                    warnings=["NPI 1234 not in physicians", "RVU=0 for site 7"],
                )
            ),
        },
    )

    fake_settings = MagicMock()
    fake_settings.paycom_configured = True
    monkeypatch.setattr("jobs.paycom_sync.main.settings", fake_settings)

    # Capture log.warning calls — that's where the prefixed warnings land.
    warnings_logged: list[str] = []
    fake_log = MagicMock()
    fake_log.warning.side_effect = lambda msg: warnings_logged.append(msg)
    fake_log.info = lambda *_a, **_kw: None
    monkeypatch.setattr("jobs.paycom_sync.main.log", fake_log)

    exit_code = await run()

    assert exit_code == 0
    assert "headcount_daily: site X missing in roster" in warnings_logged
    assert "rvu_paycheck: NPI 1234 not in physicians" in warnings_logged
    assert "rvu_paycheck: RVU=0 for site 7" in warnings_logged


async def test_run_with_empty_routes_still_exits_zero(monkeypatch) -> None:
    """Empty registry → no-op success (no extractors to run, but
    paycom_configured was true so we didn't take the no-op branch). The
    function should still return 0 cleanly without raising."""
    factory = _FakeSessionFactory()
    monkeypatch.setattr("jobs.paycom_sync.main.SessionLocal", factory)
    monkeypatch.setattr("jobs.paycom_sync.main.set_current_upn", lambda _: None)
    monkeypatch.setattr("jobs.paycom_sync.main.ROUTES", {})

    fake_settings = MagicMock()
    fake_settings.paycom_configured = True
    monkeypatch.setattr("jobs.paycom_sync.main.settings", fake_settings)

    exit_code = await run()

    assert exit_code == 0
    assert len(factory.opened) == 0
