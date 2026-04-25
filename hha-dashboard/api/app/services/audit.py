"""SQLAlchemy audit event listener.

Every INSERT / UPDATE / DELETE on an auditable table writes a row to
audit.audit_log capturing who (UPN), when, what (table + pk), and the diff.

Uses `before_flush` to compute diffs + `after_flush` to emit audit rows
inside the same transaction. If the parent transaction rolls back, the
audit rows roll back with it — they cannot orphan.

Current-user UPN flows through a contextvars.ContextVar:
  - FastAPI middleware sets it per-request from CurrentUser.upn
  - Cron jobs set it once at startup (e.g. 'upload-ingest@hhamedicine.com')
  - Fallback is '__system__' so tests and one-off scripts work without setup

Per ADR-001:
- Only tables in AUDITED_TABLES get diffs
- Diffs contain only column values that already live in Postgres
  (so by construction, no Tier C / PHI data can leak)
"""

from __future__ import annotations

import contextvars
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from ..models.audit import AuditLog

log = logging.getLogger(__name__)

# Tables that get audited. Keep in sync with ADR-001 and CLAUDE.md.
# Format: (schema, table_name)
AUDITED_TABLES: frozenset[tuple[str, str]] = frozenset(
    {
        ("masters", "physicians"),
        ("masters", "comp_agreements"),
        ("masters", "contracts"),
        ("masters", "credentials"),
        ("masters", "site_coverage"),
        ("entries", "daily_entries"),
        ("entries", "monthly_finance_manual"),
    }
)

# Columns we never include in diffs (noisy, not business-meaningful).
IGNORED_COLUMNS: frozenset[str] = frozenset({"created_at", "updated_at"})

# Request/job-scoped current-user UPN. Set by middleware or job startup.
current_upn: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_upn", default="__system__"
)


def _is_audited(obj: Any) -> bool:
    table = obj.__table__ if hasattr(obj, "__table__") else None
    if table is None:
        return False
    return (table.schema or "public", table.name) in AUDITED_TABLES


def _row_pk(obj: Any) -> str:
    """Stringified primary key — handles single + composite."""
    mapper = inspect(obj).mapper
    pk_values = [getattr(obj, col.key) for col in mapper.primary_key]
    return ",".join(str(v) for v in pk_values)


def _row_to_dict(obj: Any) -> dict[str, Any]:
    """Snapshot all column values to a JSON-serializable dict."""
    out: dict[str, Any] = {}
    for col in obj.__table__.columns:
        if col.name in IGNORED_COLUMNS:
            continue
        value = getattr(obj, col.name, None)
        if isinstance(value, datetime):
            value = value.isoformat()
        elif hasattr(value, "isoformat"):  # date
            value = value.isoformat()
        elif hasattr(value, "value"):  # Enum
            value = value.value
        out[col.name] = value
    return out


def _compute_update_diff(obj: Any) -> dict[str, dict[str, Any]]:
    """Diff of changed columns: {col: {old, new}}."""
    insp = inspect(obj)
    changes: dict[str, dict[str, Any]] = {}
    for attr in insp.attrs:
        if attr.key in IGNORED_COLUMNS:
            continue
        hist = attr.load_history()
        if not hist.has_changes():
            continue
        # Only record columns that correspond to actual table columns
        if attr.key not in obj.__table__.columns:
            continue
        old = hist.deleted[0] if hist.deleted else None
        new = hist.added[0] if hist.added else None
        if isinstance(old, datetime):
            old = old.isoformat()
        elif hasattr(old, "isoformat"):
            old = old.isoformat()
        if isinstance(new, datetime):
            new = new.isoformat()
        elif hasattr(new, "isoformat"):
            new = new.isoformat()
        changes[attr.key] = {"old": old, "new": new}
    return changes


def _build_audit_row(obj: Any, action: str, diff: dict[str, Any]) -> AuditLog:
    return AuditLog(
        table_schema=obj.__table__.schema or "public",
        table_name=obj.__table__.name,
        row_pk=_row_pk(obj),
        action=action,
        diff=diff,
        changed_by_upn=current_upn.get(),
        changed_at=datetime.now(timezone.utc),
    )


def _before_flush(session: Session, flush_context: Any, instances: Any) -> None:
    """Collect audit rows for all pending changes and queue them for insert."""
    pending_audit: list[AuditLog] = []

    for obj in session.new:
        if not _is_audited(obj):
            continue
        pending_audit.append(
            _build_audit_row(obj, "INSERT", {"new": _row_to_dict(obj)})
        )

    for obj in session.dirty:
        if not _is_audited(obj):
            continue
        # Only record real UPDATEs (not spurious identity-map touches)
        if not session.is_modified(obj, include_collections=False):
            continue
        diff = _compute_update_diff(obj)
        if not diff:
            continue
        pending_audit.append(_build_audit_row(obj, "UPDATE", diff))

    for obj in session.deleted:
        if not _is_audited(obj):
            continue
        pending_audit.append(
            _build_audit_row(obj, "DELETE", {"old": _row_to_dict(obj)})
        )

    # Add all audit rows to the session — they'll flush in the same transaction
    for row in pending_audit:
        session.add(row)


def install_audit_listener() -> None:
    """Register the event listener. Idempotent — safe to call multiple times."""
    if getattr(install_audit_listener, "_installed", False):
        return
    event.listen(Session, "before_flush", _before_flush)
    install_audit_listener._installed = True  # type: ignore[attr-defined]
    log.info("audit.listener_installed tables=%d", len(AUDITED_TABLES))


def set_current_upn(upn: str) -> contextvars.Token[str]:
    """Set the UPN for the current context. Returns a token for reset().

    FastAPI middleware pattern:
        token = set_current_upn(user.upn)
        try:
            response = await call_next(request)
        finally:
            current_upn.reset(token)
    """
    return current_upn.set(upn)
