"""Row-level (Standard Spec) Ventra ingest — queue-driven entrypoint.

KEDA's azure-queue scaler on ``q-ventra-stdspec-manifests`` (Bicep H4)
spins up one replica per Event Grid manifest event. This entrypoint
receives ONE message, processes end-to-end, then exits.

Flow (mirrors the pre-aggregated path with row-level + PHI-safety
deltas):

  1. Bootstrap PHI-safe structlog + telemetry + audit.upn
  2. Receive ONE message from q-ventra-stdspec-manifests
  3. Parse Event Grid envelope -> drop_date + manifest_blob_path
  4. Open DB session, start ops.ingest_run row (vendor='ventra-stdspec')
  5. Validators in order:
       V1-V4   load_manifest (parse + presence + sha + row_count)
       V5+V15L1 streaming parse_invoice + parse_guarantor (PHI stripped
                at the parser layer; expected PHI columns confirmed in
                the raw header for sanity)
       V15L2   aggregator.process_invoice_row runs assert_no_phi_columns
                on every row's model_dump
       V9      validate_ar_buckets (uniqueness + sign discipline)
       V12+V8  validate_fl_only (masters.sites lookup)
       V12-x   assert_facility_set_consistency (invoice vs guarantor sets)
       V13     check_dedup -> DedupDecision
       V15L4   assert_v15_pre_write on the aggregate dataclasses
  6. If skip_entirely: emit dedup_skip, complete run, delete msg, exit 0
  7. Otherwise: ingest_drop (single-tx upsert), complete run, notify_success
  8. Delete queue message -> exit 0

Failure routing (Python MRO catches PHILeakError BEFORE ADRViolation
BEFORE ValidationError):

  PHILeakError    -> quarantine + emit phi_leak_detected + notify_incident
                     (incident_class=v15_phi_leak). Delete msg; exit 0.
                     DO NOT auto-retry — operator must investigate +
                     potentially revert deploy.

  ADRViolation    -> quarantine + emit adr005_violation + notify_incident
                     (incident_class=adr_005). Delete msg; exit 0.
                     Same as the pre-agg path's V12 routing.

  ValidationError -> quarantine + emit validation_failed + notify_quarantine.
                     Delete msg; exit 0.

  Other Exception -> run.complete(status='failed') + notify_failure +
                     re-raise. DO NOT delete msg; KEDA retries up to
                     replicaRetryLimit=3 (H5 Bicep) before DLQ.
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

from .aggregator import Aggregator
from .exceptions import (
    ADRViolation,
    PHILeakError,
    ValidationError,
)
from .ingest import IngestRun, ingest_drop
from .logging import configure_logging_for_stdspec
from .manifest import file_stem, load_manifest
from .notify import (
    notify_dedup_skip,
    notify_failure,
    notify_incident,
    notify_quarantine,
    notify_success,
)
from .observability import (
    EVENT_VENTRA_STDSPEC_ADR005_VIOLATION,
    EVENT_VENTRA_STDSPEC_DEDUP_SKIP,
    EVENT_VENTRA_STDSPEC_FILE_QUARANTINED,
    EVENT_VENTRA_STDSPEC_INGEST_COMPLETE,
    EVENT_VENTRA_STDSPEC_INGEST_FAILED,
    EVENT_VENTRA_STDSPEC_MANIFEST_RECEIVED,
    EVENT_VENTRA_STDSPEC_PHI_LEAK_DETECTED,
    EVENT_VENTRA_STDSPEC_ROWS_WRITTEN,
    EVENT_VENTRA_STDSPEC_VALIDATION_FAILED,
    EVENT_VENTRA_STDSPEC_VALIDATION_PASSED,
    bind_run,
    clear_run,
    emit_event,
)
from .parsers import ROUTES as PARSER_ROUTES
from .quarantine import quarantine_drop
from .validators import (
    ManifestEntry as DedupManifestEntry,
)
from .validators import (
    assert_v15_pre_write,
    check_dedup,
    validate_ar_buckets,
    validate_fl_only,
)

logger = structlog.get_logger("jobs.ventra_ingest_stdspec.main")

SERVICE_UPN = "ventra-ingest-stdspec@system"

# Visibility timeout 1080s — gives 3 min headroom over the replica_timeout
# (900s in H5 Bicep). Longer than pre-agg (720s) because row-level
# parsing + aggregation takes more wall-clock.
VISIBILITY_TIMEOUT_SECONDS = 1080


# ============================================================================
# Event Grid envelope parsing
# ============================================================================


def parse_event_grid_payload(message_content: str) -> tuple[date, str]:
    """Parse an Event Grid event delivered via Storage Queue.

    Subject format for the stdspec subscription (H4):
        /blobServices/default/containers/vendor-inbound/blobs/ventra/stdspec/YYYY-MM-DD/_MANIFEST.csv

    Returns (drop_date, manifest_blob_path) where manifest_blob_path is
    relative to vendor-inbound: ``ventra/stdspec/YYYY-MM-DD/_MANIFEST.csv``.

    Raises ``ValueError`` on a malformed payload — caller treats that as
    a poison message and deletes it.
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
    blob_path = subject[idx + len(marker):]  # ventra/stdspec/YYYY-MM-DD/_MANIFEST.csv

    parts = blob_path.split("/")
    # Expect at least: ventra / stdspec / YYYY-MM-DD / _MANIFEST.csv
    if len(parts) < 4 or parts[0] != "ventra" or parts[1] != "stdspec":
        raise ValueError(f"unexpected blob path: {blob_path!r}")
    drop_date = date.fromisoformat(parts[2])

    return drop_date, blob_path


def _build_queue_client(account_name: str, queue_name: str) -> QueueClient:
    """Build a Storage Queue client. Connection string in dev, MI in prod."""
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    if conn_str:
        return QueueClient.from_connection_string(conn_str, queue_name)
    account_url = f"https://{account_name}.queue.core.windows.net"
    return QueueClient(
        account_url=account_url,
        queue_name=queue_name,
        credential=DefaultAzureCredential(),
    )


def _parse_recipients(env_value: str) -> list[str]:
    """Split a comma-separated env value into a clean recipient list."""
    return [r.strip() for r in env_value.split(",") if r.strip()]


# ============================================================================
# Per-message processing
# ============================================================================


async def process_one_message(
    message_content: str,
    recipients: list[str],
) -> None:
    """Process a single Event Grid manifest event end-to-end.

    Raises ANY exception not in {PHILeakError, ADRViolation, ValidationError}
    so the caller can decide whether to delete the queue message
    (handled paths) or leave it for KEDA retry (unhandled paths).
    """
    correlation_id = uuid.uuid4()
    started = time.monotonic()
    drop_date, manifest_path = parse_event_grid_payload(message_content)
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
            EVENT_VENTRA_STDSPEC_MANIFEST_RECEIVED,
            manifest_path=manifest_path,
        )

        try:
            # ---------- Phase 1: V1-V4 manifest + checksums ----------
            manifest, file_bytes = await load_manifest(drop_date, manifest_path)

            # ---------- Phase 2: V13 dedup BEFORE parsing ----------
            # Cheaper to short-circuit on a re-delivery before we slurp + parse.
            dedup_entries = [
                DedupManifestEntry(file_name=e.file_name, sha256=e.sha256)
                for e in manifest.entries
            ]
            decision = await check_dedup(db, drop_date, dedup_entries)

            if decision.skip_entirely:
                emit_event(
                    EVENT_VENTRA_STDSPEC_DEDUP_SKIP,
                    files=decision.already_processed,
                )
                await run.complete(
                    db,
                    status="succeeded",
                    files_count=len(manifest.entries),
                    rows_in=manifest.total_rows,
                    rows_out=0,
                )
                await notify_dedup_skip(
                    drop_date=drop_date,
                    already_processed=decision.already_processed,
                    run_id=run.run_id,
                    correlation_id=correlation_id,
                    recipients=recipients,
                )
                return

            # ---------- Phase 3: streaming parse + aggregate (5 files) ----------
            # PHI is stripped at the parser layer (allowlist) before any row
            # reaches the aggregator. Files stream independently; the
            # aggregator joins them in memory by the transient InvoiceNo.
            aggregator = Aggregator(drop_date=drop_date)
            row_processors = {
                "invoice": aggregator.process_invoice_row,
                "chargelines": aggregator.process_chargeline_row,
                "physician": aggregator.process_physician_row,
                "facility": aggregator.process_facility_row,
                "transactionsalt": aggregator.process_transaction_row,
            }
            for entry in manifest.entries:
                stem = file_stem(entry.file_name)
                parser = PARSER_ROUTES.get(stem)
                processor = row_processors.get(stem)
                if parser is None or processor is None:
                    # Defensive — manifest.py's V1 should have rejected this.
                    raise ValidationError(
                        rule="V1",
                        safe_message=f"no parser registered for {entry.file_name}",
                        internal_details={"file_name": entry.file_name, "stem": stem},
                    )
                data = file_bytes[entry.file_name]
                for row in parser(data):
                    processor(row)

            # ---------- Phase 4: V12 + V8 — resolve facilities via mapping ----------
            # Returns {ventra_facility_no: hha_site_id}; raises ADRViolation
            # (non-FL) or V8 (unmapped) before the aggregator's join runs.
            facility_map = await validate_fl_only(db, aggregator.ventra_facilities)

            # ---------- Phase 5: emit aggregates + V9 + V15 layer 4 ----------
            collections, ar_rows, physician_rows = aggregator.emit(facility_map)

            validate_ar_buckets(ar_rows)
            assert_v15_pre_write([*collections, *ar_rows, *physician_rows])

            emit_event(
                EVENT_VENTRA_STDSPEC_VALIDATION_PASSED,
                rules_evaluated=15,
                invoice_rows_consumed=aggregator.invoice_rows_consumed,
                chargeline_rows_consumed=aggregator.chargeline_rows_consumed,
                transaction_rows_consumed=aggregator.transaction_rows_consumed,
            )

            # ---------- Phase 6: single-tx upsert ----------
            result = await ingest_drop(
                db,
                collections_rows=collections,
                ar_rows=ar_rows,
                physician_rows=physician_rows,
                manifest_entries=dedup_entries,
                drop_date=drop_date,
                run_id=run.run_id,
            )
            duration = time.monotonic() - started

            for table, count in result.rows_by_table.items():
                emit_event(EVENT_VENTRA_STDSPEC_ROWS_WRITTEN, table=table, count=count)

            await run.complete(
                db,
                status="succeeded",
                files_count=len(manifest.entries),
                rows_in=manifest.total_rows,
                rows_out=result.rows_written,
            )
            emit_event(
                EVENT_VENTRA_STDSPEC_INGEST_COMPLETE,
                rows_out=result.rows_written,
                rows_by_table=dict(result.rows_by_table),
                duration_seconds=round(duration, 2),
                invoice_rows_consumed=aggregator.invoice_rows_consumed,
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

        # Order matters: PHILeakError + ADRViolation are caught BEFORE
        # the generic ValidationError. Python MRO routes the subclass
        # first.
        except PHILeakError as e:
            await quarantine_drop(drop_date, e, run.run_id, correlation_id)
            emit_event(
                EVENT_VENTRA_STDSPEC_PHI_LEAK_DETECTED,
                layer=e.layer,
                safe_message=e.safe_message,
            )
            emit_event(
                EVENT_VENTRA_STDSPEC_FILE_QUARANTINED,
                incident_class="v15_phi_leak",
                drop_date=drop_date.isoformat(),
            )
            await run.complete(
                db,
                status="quarantined",
                error_message=e.safe_message,
                error_details=e.internal_details,
            )
            await notify_incident(
                drop_date=drop_date,
                incident_class="v15_phi_leak",
                safe_message=e.safe_message,
                internal_details=e.internal_details,
                run_id=run.run_id,
                correlation_id=correlation_id,
                recipients=recipients,
            )

        except ADRViolation as e:
            await quarantine_drop(drop_date, e, run.run_id, correlation_id)
            emit_event(
                EVENT_VENTRA_STDSPEC_ADR005_VIOLATION,
                safe_message=e.safe_message,
                internal_details=e.internal_details,
            )
            emit_event(
                EVENT_VENTRA_STDSPEC_FILE_QUARANTINED,
                incident_class="adr_005",
                drop_date=drop_date.isoformat(),
            )
            await run.complete(
                db,
                status="quarantined",
                error_message=e.safe_message,
                error_details=e.internal_details,
            )
            await notify_incident(
                drop_date=drop_date,
                incident_class="adr_005",
                safe_message=e.safe_message,
                internal_details=e.internal_details,
                run_id=run.run_id,
                correlation_id=correlation_id,
                recipients=recipients,
            )

        except ValidationError as e:
            await quarantine_drop(drop_date, e, run.run_id, correlation_id)
            emit_event(
                EVENT_VENTRA_STDSPEC_FILE_QUARANTINED,
                rule=e.rule,
                drop_date=drop_date.isoformat(),
            )
            emit_event(
                EVENT_VENTRA_STDSPEC_VALIDATION_FAILED,
                rule=e.rule,
                safe_message=e.safe_message,
            )
            await run.complete(
                db,
                status="quarantined",
                error_message=e.safe_message,
                error_details=e.internal_details,
            )
            await notify_quarantine(
                drop_date=drop_date,
                rule=e.rule,
                safe_message=e.safe_message,
                internal_details=e.internal_details,
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
                EVENT_VENTRA_STDSPEC_INGEST_FAILED,
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


# ============================================================================
# main() entrypoint
# ============================================================================


async def main() -> int:
    """Container Apps Job entrypoint.

    Exit codes:
      0 -- message processed (any terminal outcome) OR queue was empty
      1 -- config error before any work started
      2 -- unhandled exception; KEDA retries by leaving the message visible
    """
    configure_logging_for_stdspec()

    storage_account = os.environ.get("STORAGE_ACCOUNT", "")
    queue_name = os.environ.get(
        "MANIFEST_QUEUE_NAME", "q-ventra-stdspec-manifests"
    )
    alert_to_ops = os.environ.get("ALERT_EMAIL_TO_OPS", "")

    if not storage_account:
        logger.error(
            "ventra_stdspec.config_error",
            reason="STORAGE_ACCOUNT env var is required",
        )
        return 1

    recipients = _parse_recipients(alert_to_ops)

    async with _build_queue_client(storage_account, queue_name) as queue:
        try:
            async for message in queue.receive_messages(
                messages_per_page=1,
                visibility_timeout=VISIBILITY_TIMEOUT_SECONDS,
            ):
                try:
                    try:
                        await process_one_message(message.content, recipients)
                    except ValueError as e:
                        # Bad event payload — poison message. Log + delete.
                        logger.exception(
                            "ventra_stdspec.bad_event_payload", error=str(e)
                        )
                    await queue.delete_message(message)
                    return 0
                except Exception:
                    # Unhandled — do NOT delete. KEDA retries.
                    logger.exception("ventra_stdspec.unhandled_exception")
                    return 2
                finally:
                    clear_run()
            logger.info("ventra_stdspec.queue_empty")
            return 0
        finally:
            clear_run()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
