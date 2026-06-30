"""Row-level (Standard Spec) Ventra ingest — queue-driven entrypoint.

KEDA's azure-queue scaler on ``q-ventra-stdspec-manifests`` (Bicep H4)
spins up one replica per Event Grid zip-drop event. This entrypoint
receives ONE message, processes end-to-end, then exits.

Flow (mirrors the pre-aggregated path with row-level + PHI-safety
deltas):

  1. Bootstrap PHI-safe structlog + telemetry + audit.upn
  2. Receive ONE message from q-ventra-stdspec-manifests
  3. Parse Event Grid envelope -> drop_date + zip_blob_path
  4. Open DB session, start ops.ingest_run row (vendor='ventra-stdspec')
  5. Validators in order:
       V1-V3   load_zip_drop (download zip + unzip in memory; per-member
                CRC32 = integrity; all 5 files present). Ventra delivers a
                single zip per drop (no _MANIFEST.csv) per their 2026-06-22
                reply.
       V5+V15L1 streaming parsers for the 5 files (PHI stripped at the
                parser layer via the allowlist before any row is built)
       V15L2   aggregator.process_*_row runs assert_no_phi_columns on
                every row's model_dump
       V9      validate_ar_buckets (uniqueness + sign discipline)
       V12+V8  validate_fl_only (dims.facility_codes -> masters.sites)
       V13     check_dedup -> DedupDecision (keyed on the zip sha256)
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
from .manifest import drop_date_from_zip_name, file_stem, load_zip_drop
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

    Subject format for the stdspec subscription (Phase 4Z) — a single zip
    per drop, no manifest:
        /blobServices/default/containers/vendor-inbound/blobs/ventra/stdspec/HHA_Extact_20260610.zip
    An optional dated subfolder before the zip is tolerated, e.g.
        .../ventra/stdspec/2026-06-10/HHA_Extact_20260610.zip

    Returns (drop_date, zip_blob_path) where zip_blob_path is relative to
    vendor-inbound (``ventra/stdspec/HHA_Extact_20260610.zip``) and
    drop_date is parsed from the zip filename.

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
    blob_path = subject[idx + len(marker):]  # ventra/stdspec/.../HHA_Extact_YYYYMMDD.zip

    parts = blob_path.split("/")
    # Expect at least: ventra / stdspec / <...>.zip
    if len(parts) < 3 or parts[0] != "ventra" or parts[1] != "stdspec":
        raise ValueError(f"unexpected blob path: {blob_path!r}")
    if not blob_path.lower().endswith(".zip"):
        raise ValueError(f"stdspec trigger expected a .zip, got: {blob_path!r}")

    try:
        drop_date = drop_date_from_zip_name(blob_path)
    except ValidationError as e:
        # A zip with no parseable date can't be routed — poison message.
        raise ValueError(
            f"cannot derive drop date from zip name: {blob_path!r}"
        ) from e

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
    """Process a single Event Grid zip-drop event end-to-end.

    Raises ANY exception not in {PHILeakError, ADRViolation, ValidationError}
    so the caller can decide whether to delete the queue message
    (handled paths) or leave it for KEDA retry (unhandled paths).
    """
    correlation_id = uuid.uuid4()
    started = time.monotonic()
    drop_date, zip_blob_path = parse_event_grid_payload(message_content)
    bind_run(run_id=None, correlation_id=correlation_id, drop_date=drop_date)

    set_current_upn(SERVICE_UPN)
    async with SessionLocal() as db:
        run = await IngestRun.start(
            db,
            drop_date=drop_date,
            manifest_path=zip_blob_path,
            correlation_id=correlation_id,
        )
        bind_run(run_id=run.run_id, correlation_id=correlation_id, drop_date=drop_date)
        emit_event(
            EVENT_VENTRA_STDSPEC_MANIFEST_RECEIVED,
            zip_path=zip_blob_path,
        )

        try:
            # ---------- Phase 1: V1-V3 — download + unzip the drop ----------
            # Single zip per drop (no manifest); zipfile validates per-member
            # CRC32 on read, and unzip_drop enforces presence of all 5 files.
            drop = await load_zip_drop(zip_blob_path)
            file_bytes = drop.file_bytes

            # ---------- Phase 2: V13 dedup BEFORE parsing ----------
            # Cheaper to short-circuit on a re-delivery before we unzip + parse.
            # The zip itself is the dedup unit: one ledger row per drop keyed
            # on the zip's sha256.
            dedup_entries = [
                DedupManifestEntry(
                    file_name=drop.zip_file_name, sha256=drop.zip_sha256
                )
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
                    files_count=len(drop.file_bytes),
                    rows_in=drop.total_rows,
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
            for file_name, data in file_bytes.items():
                stem = file_stem(file_name)
                parser = PARSER_ROUTES.get(stem)
                processor = row_processors.get(stem)
                if parser is None or processor is None:
                    # Defensive — unzip_drop's V1 should have rejected this.
                    raise ValidationError(
                        rule="V1",
                        safe_message=f"no parser registered for {file_name}",
                        internal_details={"file_name": file_name, "stem": stem},
                    )
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
                files_count=len(drop.file_bytes),
                rows_in=drop.total_rows,
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
