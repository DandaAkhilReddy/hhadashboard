"""Metadata-level tests for the Ventra fact-table models.

These pin invariants that ``test_ventra_integration.py`` exercises only
indirectly (via live Postgres). The intent here is to fail the build the
moment a schema-evolution refactor strips a named CHECK or removes a
server_default — before a migration lands in CI's Postgres image.

Specifically, three classes of regressions get caught at unit-test speed:

1. The ``source_system = 'VENTRA_FL_ATHENA'`` and ``state = 'FL'`` CHECK
   constraints (ADR-005 + ADR-006 invariants). If either disappears, the
   ingest writer can silently persist rows from a non-FL source.

2. The ``server_default`` on source_system + state columns. Without these,
   ``jobs/ventra_ingest/ingest.py`` (which intentionally omits the columns
   from its INSERT values) would write NULLs and fail the NOT NULL.

3. ADR-001: every column carries ``info={"data_class": "A"}``. Already
   enforced by ``test_schema_classification.py`` for the whole DB, but
   pinning at the per-table level surfaces failures with a clearer
   error message.
"""

from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models.entries_ventra import (
    FactArSnapshot,
    FactCollectionsDaily,
    FactRevenueByPhysicianMo,
)

# SQLAlchemy applies the project naming_convention defined in
# app/models/base.py:
#   ck -> ck_%(table_name)s_%(constraint_name)s
# so the literal CHECK names in entries_ventra.py get prefixed. We pin the
# fully-rendered names so a rename in either the convention OR the per-
# constraint name is caught.
_FACT_TABLES_WITH_LOCKS = [
    pytest.param(
        FactCollectionsDaily,
        "ck_fact_collections_daily_collections_source_system_locked",
        "ck_fact_collections_daily_collections_state_fl_only",
        id="fact_collections_daily",
    ),
    pytest.param(
        FactArSnapshot,
        "ck_fact_ar_snapshot_ar_source_system_locked",
        "ck_fact_ar_snapshot_ar_state_fl_only",
        id="fact_ar_snapshot",
    ),
    pytest.param(
        FactRevenueByPhysicianMo,
        "ck_fact_revenue_by_physician_mo_physician_mo_source_system_locked",
        "ck_fact_revenue_by_physician_mo_physician_mo_state_fl_only",
        id="fact_revenue_by_physician_mo",
    ),
]


def _check_names(model: type) -> set[str]:
    """Names of every CheckConstraint on a model's __table__."""
    return {
        c.name
        for c in model.__table__.constraints
        if isinstance(c, CheckConstraint) and c.name is not None
    }


def _unique_names(model: type) -> set[str]:
    """Names of every UniqueConstraint on a model's __table__."""
    return {
        c.name
        for c in model.__table__.constraints
        if isinstance(c, UniqueConstraint) and c.name is not None
    }


@pytest.mark.parametrize(
    ("model", "source_check_name", "state_check_name"),
    _FACT_TABLES_WITH_LOCKS,
)
def test_source_system_check_present(
    model: type, source_check_name: str, state_check_name: str
) -> None:
    """``source_system = 'VENTRA_FL_ATHENA'`` CHECK exists and carries its
    documented name. Dropping this would let the ingest writer accept any
    source_system value — including a TX or non-Ventra one."""
    _ = state_check_name
    names = _check_names(model)

    assert source_check_name in names, (
        f"{model.__name__} is missing the source_system lock — saw {sorted(names)}"
    )


@pytest.mark.parametrize(
    ("model", "source_check_name", "state_check_name"),
    _FACT_TABLES_WITH_LOCKS,
)
def test_state_fl_only_check_present(
    model: type, source_check_name: str, state_check_name: str
) -> None:
    """``state = 'FL'`` CHECK exists. ADR-005 invariant."""
    _ = source_check_name
    names = _check_names(model)

    assert state_check_name in names, (
        f"{model.__name__} is missing the state='FL' lock — saw {sorted(names)}"
    )


@pytest.mark.parametrize(
    ("model", "source_check_name", "state_check_name"),
    _FACT_TABLES_WITH_LOCKS,
)
def test_source_system_check_locks_to_ventra_fl_athena(
    model: type, source_check_name: str, state_check_name: str
) -> None:
    """Pins the literal RHS of the CHECK constraint, not just its name.
    A rename like ``source_system = 'VENTRA_FL_NEW'`` would slip past
    the name-only test."""
    _ = state_check_name
    matching = [
        c
        for c in model.__table__.constraints
        if isinstance(c, CheckConstraint) and c.name == source_check_name
    ]
    assert len(matching) == 1
    sqltext = str(matching[0].sqltext)

    assert "source_system" in sqltext
    assert "VENTRA_FL_ATHENA" in sqltext


@pytest.mark.parametrize(
    ("model", "source_check_name", "state_check_name"),
    _FACT_TABLES_WITH_LOCKS,
)
def test_state_check_locks_to_fl(
    model: type, source_check_name: str, state_check_name: str
) -> None:
    _ = source_check_name
    matching = [
        c
        for c in model.__table__.constraints
        if isinstance(c, CheckConstraint) and c.name == state_check_name
    ]
    assert len(matching) == 1
    sqltext = str(matching[0].sqltext)

    assert "state" in sqltext
    assert "'FL'" in sqltext


@pytest.mark.parametrize(
    ("model", "natural_key_name"),
    [
        pytest.param(
            FactCollectionsDaily,
            "uq_collections_daily_natural",
            id="fact_collections_daily",
        ),
        pytest.param(
            FactArSnapshot,
            "uq_ar_snapshot_natural",
            id="fact_ar_snapshot",
        ),
        pytest.param(
            FactRevenueByPhysicianMo,
            "uq_revenue_physician_mo_natural",
            id="fact_revenue_by_physician_mo",
        ),
    ],
)
def test_natural_key_unique_constraint_present(
    model: type, natural_key_name: str
) -> None:
    """The idempotent-upsert key. ``jobs/ventra_ingest/ingest.py`` calls
    ``on_conflict_do_update(index_elements=...)`` against the natural-key
    columns; without the UNIQUE constraint, Postgres rejects the
    ON CONFLICT clause and re-runs against the same drop double-write."""
    assert natural_key_name in _unique_names(model)


@pytest.mark.parametrize(
    "model",
    [FactCollectionsDaily, FactArSnapshot, FactRevenueByPhysicianMo],
    ids=lambda m: m.__name__,
)
def test_source_system_column_has_server_default(model: type) -> None:
    """The writer in jobs/ventra_ingest/ingest.py never passes source_system
    in its INSERT values — the DB DEFAULT supplies VENTRA_FL_ATHENA. Strip
    the server_default and the writer starts producing NULL violations."""
    col = model.__table__.columns["source_system"]

    assert col.server_default is not None, (
        f"{model.__name__}.source_system lost its server_default"
    )
    rendered = str(col.server_default.arg)
    assert "VENTRA_FL_ATHENA" in rendered


@pytest.mark.parametrize(
    "model",
    [FactCollectionsDaily, FactArSnapshot, FactRevenueByPhysicianMo],
    ids=lambda m: m.__name__,
)
def test_state_column_has_server_default(model: type) -> None:
    col = model.__table__.columns["state"]

    assert col.server_default is not None, (
        f"{model.__name__}.state lost its server_default"
    )
    rendered = str(col.server_default.arg)
    assert "FL" in rendered


@pytest.mark.parametrize(
    "model",
    [FactCollectionsDaily, FactArSnapshot, FactRevenueByPhysicianMo],
    ids=lambda m: m.__name__,
)
def test_every_column_carries_data_class_a(model: type) -> None:
    """ADR-001: every fact-table column is Tier-A pre-aggregated. A new
    column added without info={'data_class': ...} is a CI fail upstream,
    but also fails here with a clearer per-table message."""
    missing: list[str] = []
    wrong: list[tuple[str, str | None]] = []

    for col in model.__table__.columns:
        dc = col.info.get("data_class")
        if dc is None:
            missing.append(col.name)
        elif dc != "A":
            wrong.append((col.name, dc))

    assert not missing, f"{model.__name__} columns missing data_class: {missing}"
    assert not wrong, (
        f"{model.__name__} columns have non-A data_class: {wrong}"
    )


@pytest.mark.parametrize(
    "model",
    [FactCollectionsDaily, FactArSnapshot, FactRevenueByPhysicianMo],
    ids=lambda m: m.__name__,
)
def test_table_is_in_entries_schema(model: type) -> None:
    """The dashboard's schema-classification CI test gates ``entries`` for
    Tier-A pre-aggregated tables. Moving to another schema would skip
    that classification check."""
    assert model.__table__.schema == "entries"


@pytest.mark.parametrize(
    "model",
    [FactCollectionsDaily, FactArSnapshot, FactRevenueByPhysicianMo],
    ids=lambda m: m.__name__,
)
def test_ingest_run_id_column_present_and_not_null(model: type) -> None:
    """jobs/ventra_ingest/ingest.py writes ingest_run_id on every INSERT
    for back-tracing. NULL would defeat the back-trace."""
    col = model.__table__.columns["ingest_run_id"]

    assert not col.nullable
    assert col.info.get("data_class") == "A"


def test_payer_class_enum_is_pinned() -> None:
    """V5 in jobs/ventra_ingest/parsers/collections.py uses Pydantic
    Literal['commercial','medicare','medicaid','selfpay','other']. The
    DB CHECK constraint must mirror that exact set."""
    name = "ck_fact_collections_daily_collections_payer_class_valid"
    matching = [
        c
        for c in FactCollectionsDaily.__table__.constraints
        if isinstance(c, CheckConstraint) and c.name == name
    ]
    assert len(matching) == 1
    sqltext = str(matching[0].sqltext)

    for payer in ("commercial", "medicare", "medicaid", "selfpay", "other"):
        assert payer in sqltext, f"payer_class CHECK missing '{payer}'"


def test_aging_bucket_enum_is_pinned() -> None:
    """V5 in jobs/ventra_ingest/parsers/ar_snapshot.py uses Literal of the
    6 aging buckets. DB CHECK must match."""
    name = "ck_fact_ar_snapshot_ar_aging_bucket_valid"
    matching = [
        c
        for c in FactArSnapshot.__table__.constraints
        if isinstance(c, CheckConstraint) and c.name == name
    ]
    assert len(matching) == 1
    sqltext = str(matching[0].sqltext)

    for bucket in ("0-30", "31-60", "61-90", "91-120", "120+", "credit"):
        assert bucket in sqltext, f"aging_bucket CHECK missing '{bucket}'"


def test_ar_credit_bucket_allowed_negative_check_present() -> None:
    """Only the 'credit' bucket may carry a negative outstanding_amount.
    Stripping this CHECK would let any bucket go negative and the AR
    rollup math breaks silently."""
    names = _check_names(FactArSnapshot)

    assert (
        "ck_fact_ar_snapshot_ar_outstanding_non_negative_except_credit" in names
    )


def test_npi_10_digit_check_present_on_physician_table() -> None:
    """Pydantic V11 (parsers/physician_monthly.py) pre-filters NPIs to
    10 digits; the DB CHECK is the belt-and-suspenders backstop."""
    names = _check_names(FactRevenueByPhysicianMo)

    assert (
        "ck_fact_revenue_by_physician_mo_physician_mo_npi_10_digit" in names
    )


def test_month_first_of_month_check_present() -> None:
    """V7 enforces month=first-of-month in the parser; DB CHECK enforces
    the same so an out-of-band INSERT can't break the assumption."""
    names = _check_names(FactRevenueByPhysicianMo)

    assert (
        "ck_fact_revenue_by_physician_mo_physician_mo_month_is_first_of_month"
        in names
    )
