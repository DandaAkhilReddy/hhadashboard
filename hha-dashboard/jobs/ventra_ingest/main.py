"""Ventra ingest Container Apps Job — queue-driven entrypoint.

KEDA's azure-queue scaler (per infra/modules/containerjobs.bicep, C7)
spins up one replica per manifest message on q-ventra-manifests. This
entrypoint receives ONE message, processes it end-to-end, then exits.

Flow (per Phase 1A.A4 of the plan):

  1. Bootstrap telemetry + structlog + audit.upn
  2. Receive ONE message from q-ventra-manifests
  3. Parse the Event Grid envelope → drop_date + manifest_blob_path
  4. Open DB session, start ops.ingest_run row
  5. Validators in order:
     V1-V4   load_manifest (parse + presence + sha + row_count)
     V5-V11  per-file parsers (collections / ar_snapshot / physician_monthly)
     V6      validate_drop_consistency
     V9      validate_ar_buckets_sum (cross-row uniqueness)
     V12+V8  validate_fl_only (masters.sites lookup)
     V13     check_dedup → DedupDecision
  6. If skip_entirely: log dedup_skip, complete run as succeeded, delete msg
  7. Otherwise: ingest_drop (single-tx upsert), complete run as succeeded
  8. emit ventra.ingest_complete + notify_success
  9. delete queue message → exit 0

Failure routing (Python MRO catches ADRViolation BEFORE ValidationError):

  ADRViolation     → quarantine_drop + emit ventra.adr005_violation + notify_incident
                     run.complete(status='quarantined'); delete msg; exit 0
  ValidationError  → quarantine_drop + emit ventra.validation_failed + notify_quarantine
                     run.complete(status='quarantined'); delete msg; exit 0
  Anything else    → run.complete(status='failed') + emit ventra.ingest_failed
                     + notify_failure; DO NOT delete msg; re-raise so the
                     replica exits non-zero and Container Apps retries
                     per replicaRetryLimit=3 (C7 Bicep). After exhaustion
                     the EG subscription dead-letters to vendor-deadletter.

Queue-message lifecycle is what controls retry semantics — not exit
codes. Delete on every terminal outcome (success / quarantine / incident /
bad-event poison message). Don't delete on unhandled exception.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
import traceback
import uuid
from datetime import date

import structlog
from azure.identity.aio import DefaultAzureCredential
from azure.storage.queue.aio import QueueClient

from app.deps import SessionLocal
from app.services.audit import set_current_upn

from .exceptions import ADRViolation, ValidationError
from .ingest import IngestRun, ingest_drop
from .manifest import load_manifest
from .notify import (
    notify_failure,
    notify_incident,
    notify_quarantine,
    notify_success,
    parse_recipients,
)
from .observability import (
    EVENT_VENTRA_ADR005_VIOLATION,
    EVENT_VENTRA_DEDUP_SKIP,
    EVENT_VENTRA_FILE_QUARANTINED,
    EVENT_VENTRA_INGEST_COMPLETE,
    EVENT_VENTRA_INGEST_FAILED,
    EVENT_VENTRA_MANIFEST_RECEIVED,
    EVENT_VENTRA_ROWS_WRITTEN,
    EVENT_VENTRA_VALIDATION_FAILED,
    EVENT_VENTRA_VALIDATION_PASSED,
    bind_run,
    clear_run,
    emit_event,
    init_telemetry,
)
from .parsers import parse_file
from .quarantine import quarantine_drop
from .validators import (
    check_dedup,
    validate_ar_buckets_sum,
    validate_drop_consistency,
    validate_fl_only,
)

logger = structlog.get_logger("jobs.ventra_ingest.main")

SERVICE_UPN = "ventra-ingest@system"

# Visibility timeout 720s — gives 2 min headroom over the replica_timeout
# (600s in C7 Bicep). If the replica is killed mid-process the message
# becomes visible again and the next KEDA poll re-triggers a fresh replica.
VISIBILITY_TIMEOUT_SECONDS = 720


def _parse_event_grid_payload(message_content: str) -> tuple[date, str]:
    """Parse an Event Grid event delivered via Storage Queue.

    The content is JSON; some deliveries land base64-encoded depending on
    how Event Grid was configured. Try plain first, fall back to base64.

    Event Grid subject format:
        /blobServices/default/containers/vendor-inbound/blobs/ventra/YYYY-MM-DD/_MANIFEST.csv

    Returns (drop_date, manifest_blob_path) where manifest_blob_path is
    relative to the vendor-inbound container (matches the interface load_manifest
    expects: ``ventra/YYYY-MM-DD/_MANIFEST.csv``).
    """
    try:
        event = json.loads(message_content)
    except json.JSONDecodeError:
        decoded = base64.b64decode(message_content).decode("utf-8")
        event = json.loads(decoded)

    subject = event.get("subject")
    if not isinstance(subject, str):
        raise ValueError(f"Event Grid payload missing subject: {event!r}")

    marker = "/blobs/"
    idx = subject.find(marker)
    if idx == -1:
        raise ValueError(f"unexpected subject format: {subject!r}")
    blob_path = subject[idx + len(marker):]    # ventra/YYYY-MM-DD/_MANIFEST.csv

    parts = blob_path.split("/")
    if len(parts) < 3 or parts[0] != "ventra":
        raise ValueError(f"unexpected blob path: {blob_path!r}")
    drop_date = date.fromisoformat(parts[1])

    return drop_date, blob_path


def _build_queue_client(account_name: str, queue_name: str) -> QueueClient:
    """Build a Storage Queue client. Same auth strategy as app.services.blob:
    connection string in dev (when set), DefaultAzureCredential in prod (MI)."""
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    if conn_str:
        return QueueClient.from_connection_string(conn_str, queue_name)
    account_url = f"https://{account_name}.queue.core.windows.net"
    return QueueClient(
        account_url=account_url,
        queue_name=queue_name,
        credential=DefaultAzureCredential(),
    )


async def process_one_message(
    message_content: str,
    recipients: list[str],
) -> None:
    """Process a single Event Grid manifest event end-to-end.

    Raises ANY exception not in {ValidationError, ADRViolation} so that
    the caller can decide whether to delete the queue message (handled
    paths) or leave it for KEDA retry (unhandled paths).

    A bad-event-payload (corrupt JSON, missing subject) raises ValueError
    immediately — the caller treats that as a poison message and deletes
    it to avoid infinite KEDA retries.
    """
    correlation_id = uuid.uuid4()
    started = time.monotonic()
    drop_date, manifest_path = _parse_event_grid_payload(message_content)
    bind_run(run_id=None, correlation_id=correlation_id, drop_date=drop_date)

    set_current_upn(SERVICE_UPN)
    async with SessionLocal() as db:
        run = await IngestRun.start(
            db,
            drop_date=drop_date,
            manifest_path=manifest_path,
            correlation_id=correlation_id,
        )
        bind_run(run_id=run.run_id, correlation_id=correlation_id, drop_date=drop_date)
        emit_event(
            EVENT_VENTRA_MANIFEST_RECEIVED,
            manifest_path=manifest_path,
        )

        try:
            # ---------- Phase 1: V1-V4 manifest + checksums ----------
            manifest, file_bytes = await load_manifest(drop_date, manifest_path)

            # ---------- Phase 2: V5-V11 per-file parsing ----------
            parsed: dict[str, list] = {}
            for entry in manifest.entries:
                parsed[entry.file_name] = parse_file(
                    entry.file_name, file_bytes[entry.file_name]
                )

            # ---------- Phase 3: cross-file V6 / V9 / V12 / V13 ----------
            validate_drop_consistency(parsed, drop_date)                # V6
            validate_ar_buckets_sum(parsed.get("ar_snapshot.csv"))      # V9
            await validate_fl_only(db, parsed)                           # V12 / V8
            decision = await check_dedup(db, manifest)                  # V13

            if decision.skip_entirely:
                emit_event(
                    EVENT_VENTRA_DEDUP_SKIP,
                    files=decision.already_processed,
                )
                await run.complete(
                    db,
                    status="succeeded",
                    files_count=len(manifest.entries),
                    rows_in=manifest.total_rows,
                    rows_out=0,
                )
                return

            emit_event(EVENT_VENTRA_VALIDATION_PASSED, rules_evaluated=14)

            # ---------- Phase 4: V14 (DB-enforced) — single-tx upsert ----------
            result = await ingest_drop(db, parsed, manifest, run.run_id)
            duration = time.monotonic() - started

            for table, count in result.rows_by_table.items():
                emit_event(EVENT_VENTRA_ROWS_WRITTEN, table=table, count=count)

            await run.complete(
                db,
                status="succeeded",
                files_count=len(manifest.entries),
                rows_in=manifest.total_rows,
                rows_out=result.rows_written,
            )
            emit_event(
                EVENT_VENTRA_INGEST_COMPLETE,
                rows_out=result.rows_written,
                rows_by_table=dict(result.rows_by_table),
                duration_seconds=round(duration, 2),
                vendor_source_systems=list(result.vendor_source_systems),
            )
            await notify_success(
                drop_date=drop_date,
                rows_written=result.rows_written,
                rows_by_table=result.rows_by_table,
                vendor_source_systems=result.vendor_source_systems,
                duration_seconds=duration,
                run_id=run.run_id,
                correlation_id=correlation_id,
                recipients=recipients,
            )

        # Order matters: ADRViolation is a ValidationError subclass; MRO
        # routes V12 to the incident path BEFORE the generic quarantine.
        except ADRViolation as e:
            await quarantine_drop(drop_date, e, run.run_id, correlation_id)
            emit_event(EVENT_VENTRA_FILE_QUARANTINED, rule=e.rule, drop_date=drop_date.isoformat())
            emit_event(EVENT_VENTRA_ADR005_VIOLATION, message=e.message, details=e.details)
            await run.complete(
                db,
                status="quarantined",
                error_message=e.message,
                error_details=e.details,
            )
            await notify_incident(
                drop_date=drop_date,
                message=e.message,
                details=e.details,
                run_id=run.run_id,
                correlation_id=correlation_id,
                recipients=recipients,
            )

        except ValidationError as e:
            await quarantine_drop(drop_date, e, run.run_id, correlation_id)
            emit_event(EVENT_VENTRA_FILE_QUARANTINED, rule=e.rule, drop_date=drop_date.isoformat())
            emit_event(EVENT_VENTRA_VALIDATION_FAILED, rule=e.rule, message=e.message)
            await run.complete(
                db,
                status="quarantined",
                error_message=e.message,
                error_details=e.details,
            )
            await notify_quarantine(
                drop_date=drop_date,
                rule=e.rule,
                message=e.message,
                details=e.details,
                run_id=run.run_id,
                correlation_id=correlation_id,
                recipients=recipients,
            )

        except Exception as e:
            await run.complete(
                db,
                status="failed",
                error_message=str(e),
                error_details={
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc(),
                },
            )
            emit_event(
                EVENT_VENTRA_INGEST_FAILED,
                error_type=type(e).__name__,
                error_message=str(e),
            )
            await notify_failure(
                drop_date=drop_date,
                error_type=type(e).__name__,
                error_message=str(e),
                run_id=run.run_id,
                correlation_id=correlation_id,
                recipients=recipients,
            )
            raise


async def main() -> int:
    """Container Apps Job entrypoint.

    Exit codes:
      0  — message processed (success, quarantine, incident, dedup_skip,
            poison-message) OR queue was empty
      1  — config error (missing required env var) before any work started
      2  — unhandled exception propagated up; KEDA / Container Apps will
            retry by leaving the queue message visible
    """
    init_telemetry()

    storage_account = os.environ.get("STORAGE_ACCOUNT", "")
    queue_name = os.environ.get("MANIFEST_QUEUE_NAME", "q-ventra-manifests")
    alert_to_ops = os.environ.get("ALERT_EMAIL_TO_OPS", "")

    if not storage_account:
        logger.error(
            "ventra.config_error",
            reason="STORAGE_ACCOUNT env var is required",
        )
        return 1

    recipients = parse_recipients(alert_to_ops)

    async with _build_queue_client(storage_account, queue_name) as queue:
        # KEDA delivers one message per replica (concurrency=1, queueLength=1
        # in C7 Bicep). receive_messages with messages_per_page=1 keeps the
        # receive symmetric.
        try:
            async for message in queue.receive_messages(
                messages_per_page=1,
                visibility_timeout=VISIBILITY_TIMEOUT_SECONDS,
            ):
                try:
                    try:
                        await process_one_message(message.content, recipients)
                    except ValueError as e:
                        # Bad event payload — poison message. Log, delete,
                        # do not retry (retry won't recover).
                        logger.exception("ventra.bad_event_payload", error=str(e))
                    await queue.delete_message(message)
                    return 0
                except Exception:
                    # Unhandled — do NOT delete; let KEDA retry. Container
                    # Apps marks the replica failed via the non-zero exit.
                    logger.exception("ventra.unhandled_exception")
                    return 2
                finally:
                    clear_run()
            # Queue was empty (KEDA scaled us up briefly during draining)
            logger.info("ventra.queue_empty")
            return 0
        finally:
            clear_run()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
