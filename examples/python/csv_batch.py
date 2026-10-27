from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any
from apify_run import (
    TIKTOK_ACTOR_SLUG,
    RunStartError,
    require_supported_python,
    start_actor_run_once,
    validate_tiktok_video_url,
)

require_supported_python()

from apify_client import ApifyClientAsync
from dotenv import load_dotenv


DEFAULT_CONCURRENCY = 2
CONCURRENCY_LIMIT = 16
DEFAULT_MAX_WAIT = 900.0
REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "sample-output" / "generated"
OUTPUT_FILE = OUTPUT_DIR / "python-csv-batch-results.jsonl"
TERMINAL_RUN_STATUSES = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}
FINAL_RECORD_STATUSES = {
    "completed_with_transcript",
    "transcript_empty",
    "transcript_failed",
    "actor_failed",
    "dataset_empty",
    "dataset_id_missing",
    "input_error",
    "duplicate_id",
}
RECONCILIATION_STATUSES = {"start_attempted", "run_creation_unknown", "needs_reconciliation"}


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Error: {name} is required. Set it in .env or your environment.")
    return value


def validate_video_url(value: str) -> str | None:
    return validate_tiktok_video_url(value)


def safe_error(exc: Exception, token: str) -> str:
    error_text = str(exc)
    return error_text.replace(token, "[REDACTED]") if isinstance(token, str) and token else error_text


def redact_token(text: str, token: str) -> str:
    return text.replace(token, "[REDACTED]") if isinstance(token, str) and token else text


def url_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_latest_records(path: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return latest
    with path.open(encoding="utf-8") as result_file:
        for line_number, line in enumerate(result_file, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                record_key = record.get("record_key")
                if record_key:
                    latest[str(record_key)] = record
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Invalid JSONL record at line {line_number}: {exc}") from exc
    return latest


def append_record(file_handle: Any, record: dict[str, Any], token: str) -> None:
    serialized = redact_token(json.dumps(record, ensure_ascii=False), token)
    file_handle.write(serialized + "\n")
    file_handle.flush()


def inspect_csv(input_path: Path) -> tuple[bool, Counter[str], int]:
    """Pre-scan IDs so duplicate IDs are rejected before any Runs are started."""
    id_counts: Counter[str] = Counter()
    row_count = 0
    with input_path.open(newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames or "videoUrl" not in reader.fieldnames:
            raise SystemExit("Input CSV must contain a 'videoUrl' column.")
        has_id_column = "id" in reader.fieldnames
        for row in reader:
            row_count += 1
            if has_id_column:
                identifier = (row.get("id") or "").strip()
                if identifier:
                    id_counts[identifier] += 1
    return has_id_column, id_counts, row_count


async def resolve_existing_run(
    client: ApifyClientAsync,
    run_id: str,
    current: dict[str, Any],
    output_handle: Any,
    token: str,
    max_wait: float,
) -> None:
    try:
        run_client = client.run(run_id)
        run = await run_client.get()
        if run is None:
            current.update(status="run_lookup_error", error="Run ID was not found.")
            append_record(output_handle, current, token)
            return
        if str(run.status) not in TERMINAL_RUN_STATUSES:
            run = await asyncio.wait_for(run_client.wait_for_finish(), timeout=max_wait)
    except asyncio.TimeoutError:
        current.update(
            status="run_pending",
            error=f"Wait limit of {max_wait:g} seconds reached; Run may still be running.",
        )
        append_record(output_handle, current, token)
        return
    except Exception as exc:
        current.update(status="poll_error", error=safe_error(exc, token))
        append_record(output_handle, current, token)
        return

    if run is None:
        current.update(status="run_pending", error="Run wait returned no Run object; resume by this Run ID.")
        append_record(output_handle, current, token)
        return

    status = str(run.status)
    current["run_status"] = status
    if status not in TERMINAL_RUN_STATUSES:
        current.update(status="run_pending", error=f"Run is not terminal (status: {status}).")
        append_record(output_handle, current, token)
        return
    if status != "SUCCEEDED":
        current.update(status="actor_failed", error=f"Actor Run finished with status {status}.")
        append_record(output_handle, current, token)
        return

    dataset_id = run.default_dataset_id
    current["dataset_id"] = dataset_id
    if not dataset_id:
        current.update(status="dataset_id_missing", error="Completed Run has no default Dataset ID.")
        append_record(output_handle, current, token)
        return
    try:
        items = [item async for item in client.dataset(dataset_id).iterate_items()]
    except Exception as exc:
        current.update(status="dataset_error", error=safe_error(exc, token))
        append_record(output_handle, current, token)
        return

    current["items"] = items
    if not items:
        current.update(status="dataset_empty", error="Run completed with an empty Dataset.")
    else:
        transcript = next((item.get("text") for item in items if item.get("text") is not None), None)
        err_msg = next((item.get("errMsg") for item in items if item.get("errMsg") is not None), None)
        if not isinstance(transcript, str) or not transcript.strip() or err_msg:
            reasons = []
            if not isinstance(transcript, str) or not transcript.strip():
                reasons.append("transcript text is empty or missing")
            if err_msg:
                reasons.append(f"Actor errMsg is non-empty: {err_msg}")
            current.update(
                status="transcript_failed" if err_msg else "transcript_empty",
                error="Run completed, but " + "; ".join(reasons) + ".",
            )
        else:
            current.update(status="completed_with_transcript", error=None)
    append_record(output_handle, current, token)


async def process_row(
    client: ApifyClientAsync,
    row: dict[str, Any],
    prior: dict[str, Any] | None,
    output_handle: Any,
    token: str,
    max_wait: float,
) -> None:
    record_key = row["record_key"]
    if prior and prior.get("videoUrl") != row["videoUrl"]:
        if prior.get("status") in FINAL_RECORD_STATUSES:
            prior = None
        else:
            current = {
                **row,
                "attempted_videoUrl": prior.get("videoUrl"),
                "requested_videoUrl": row["videoUrl"],
                "run_id": prior.get("run_id"),
                "run_status": prior.get("run_status"),
            }
            current.update(
                status="needs_reconciliation",
                error="CSV input changed while its prior Run record is unresolved; reconcile before POST.",
            )
            append_record(output_handle, current, token)
            return
    if prior and prior.get("status") in FINAL_RECORD_STATUSES:
        return
    if prior and (prior.get("status") in RECONCILIATION_STATUSES or not prior.get("run_id")):
        current = {**row, "run_id": None, "run_status": None}
        if prior.get("status") != "needs_reconciliation":
            current.update(
                status="needs_reconciliation",
                error="Found a prior Run-creation record without a Run ID; reconcile before any new POST.",
            )
            append_record(output_handle, current, token)
        print(f"Input {record_key}: needs reconciliation; no Run was started again.")
        return

    current: dict[str, Any] = {
        **row,
        "run_id": prior.get("run_id") if prior else None,
        "run_status": prior.get("run_status") if prior else None,
        "status": "resuming_run" if prior and prior.get("run_id") else "start_attempted",
        "error": None,
        "retry_count": 0,
    }
    if not current["run_id"]:
        # Write-ahead intent is durable before the sole POST attempt. After a crash,
        # a missing Run ID blocks automatic restart and requires manual reconciliation.
        append_record(output_handle, current, token)
        try:
            started = start_actor_run_once(token, row["videoUrl"])
        except RunStartError as exc:
            current.update(
                status="run_creation_unknown",
                error="Run creation result is unknown; the Run may already have been created. "
                "Check Apify Console before retrying or starting another Run. Details: " + safe_error(exc, token),
            )
            append_record(output_handle, current, token)
            print(f"Input {record_key}: Run creation outcome unknown; reconcile manually.")
            return
        except Exception as exc:
            current.update(
                status="run_creation_unknown",
                error="Run creation result is unknown; the Run may already have been created. "
                "Check Apify Console before retrying or starting another Run. Details: " + safe_error(exc, token),
            )
            append_record(output_handle, current, token)
            print(f"Input {record_key}: Run creation outcome unknown; reconcile manually.")
            return
        current.update(run_id=started["id"], run_status=started.get("status"), status="run_started")
        append_record(output_handle, current, token)

    await resolve_existing_run(client, str(current["run_id"]), current, output_handle, token, max_wait)
    print(f"Input {record_key}: {current.get('status')} (run_id={current.get('run_id') or 'none'})")


def print_reconciliation_records(records: dict[str, dict[str, Any]], token: str) -> None:
    unresolved = [
        record for record in records.values()
        if record.get("status") in RECONCILIATION_STATUSES
        and (record.get("status") == "needs_reconciliation" or not record.get("run_id"))
    ]
    if not unresolved:
        print("No records require manual Run-creation reconciliation.")
        return
    print("Run-creation records requiring manual reconciliation:")
    for record in unresolved:
        serialized = json.dumps({
            "row_number": record.get("row_number"),
            "record_key": record.get("record_key"),
            "id": record.get("id"),
            "run_id": record.get("run_id"),
            "videoUrl": record.get("videoUrl"),
            "attempted_videoUrl": record.get("attempted_videoUrl"),
            "requested_videoUrl": record.get("requested_videoUrl"),
            "status": record.get("status"),
            "error": record.get("error"),
        }, ensure_ascii=False)
        print(redact_token(serialized, token))


def print_summary(records: list[dict[str, Any]]) -> None:
    statuses = Counter(str(record.get("status", "unknown")) for record in records)
    actor_succeeded = sum(1 for record in records if record.get("run_status") == "SUCCEEDED")
    print("Batch summary:")
    print(f"  Actor Run SUCCEEDED: {actor_succeeded}")
    print(f"  Completed with transcript text: {statuses['completed_with_transcript']}")
    print(f"  Empty or missing transcript: {statuses['transcript_empty']}")
    print(f"  Transcript errors (errMsg): {statuses['transcript_failed']}")
    print(f"  Actor Run failed: {statuses['actor_failed']}")
    print(f"  Dataset empty: {statuses['dataset_empty']}")
    print(f"  Dataset ID missing: {statuses['dataset_id_missing']}")
    print(f"  Dataset read errors: {statuses['dataset_error']}")
    print(f"  Run status/read errors: {statuses['poll_error'] + statuses['run_lookup_error']}")
    print(f"  Run creation unknown / reconciliation required: {sum(statuses[s] for s in RECONCILIATION_STATUSES)}")
    print(f"  Still running / wait pending: {statuses['run_pending']}")
    print(f"  Invalid input rows: {statuses['input_error'] + statuses['duplicate_id']}")
    print(f"  Processing errors: {statuses['processing_error']}")
    for status, count in sorted(statuses.items()):
        if status not in {
            "completed_with_transcript", "transcript_empty", "transcript_failed", "actor_failed",
            "dataset_empty", "dataset_id_missing", "dataset_error", "poll_error", "run_lookup_error",
            "run_creation_unknown", "start_attempted", "needs_reconciliation", "run_pending",
            "input_error", "duplicate_id", "processing_error",
        }:
            print(f"  Other record status {status}: {count}")


async def process_csv(input_path: Path, concurrency: int, max_wait: float, token: str) -> None:
    if not isinstance(concurrency, int) or isinstance(concurrency, bool) or not 1 <= concurrency <= CONCURRENCY_LIMIT:
        raise SystemExit(f"Input error: concurrency must be an integer between 1 and {CONCURRENCY_LIMIT}.")
    has_id_column, id_counts, row_count = inspect_csv(input_path)
    if row_count == 0:
        raise SystemExit("Input CSV is empty: it contains a header but no video rows were processed.")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    latest = read_latest_records(OUTPUT_FILE)
    client = ApifyClientAsync(token=token)
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=concurrency * 2)
    active_record_keys: set[str] = set()
    url_occurrences: Counter[str] = Counter()
    id_occurrences: Counter[str] = Counter()

    with OUTPUT_FILE.open("a", encoding="utf-8") as output_handle:
        async def worker() -> None:
            while True:
                row = await queue.get()
                try:
                    if row is None:
                        return
                    await process_row(
                        client,
                        row,
                        latest.get(row["record_key"]),
                        output_handle,
                        token,
                        max_wait,
                    )
                except Exception as exc:
                    invalid_record = {
                        **(row if row else {}),
                        "status": "processing_error",
                        "error": safe_error(exc, token),
                        "retry_count": 0,
                    }
                    append_record(output_handle, invalid_record, token)
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
        try:
            with input_path.open(newline="", encoding="utf-8-sig") as csv_file:
                reader = csv.DictReader(csv_file)
                for row_number, source in enumerate(reader, start=2):
                    video_url = source.get("videoUrl") or ""
                    identifier = (source.get("id") or "").strip() if has_id_column else ""
                    url_occurrences[video_url] += 1
                    url_occurrence = url_occurrences[video_url]
                    id_occurrences[identifier] += 1

                    if has_id_column and identifier:
                        if id_counts[identifier] > 1:
                            record_key = f"invalid-id:{url_fingerprint(identifier)}:{id_occurrences[identifier]}"
                            error = f"Duplicate id value at CSV row {row_number}; no Run was started."
                            status = "duplicate_id"
                        else:
                            record_key = f"id:{url_fingerprint(identifier)}"
                            error = validate_video_url(video_url)
                            status = "input_error"
                    else:
                        # Without an id column, identical URLs get occurrence-number keys;
                        # reordering those identical rows changes which record has each occurrence.
                        record_key = f"url:{url_fingerprint(video_url)}:{url_occurrence}"
                        error = "The optional id column contains an empty id; no Run was started." if has_id_column else validate_video_url(video_url)
                        status = "input_error"

                    row_data = {
                        "record_key": record_key,
                        "row_number": row_number,
                        "id": identifier or None,
                        "videoUrl": video_url,
                    }
                    active_record_keys.add(record_key)
                    if error:
                        append_record(output_handle, {
                            **row_data,
                            "run_id": None,
                            "run_status": None,
                            "status": status,
                            "error": error,
                            "retry_count": 0,
                        }, token)
                        continue
                    await queue.put(row_data)

            for _ in workers:
                await queue.put(None)
            await queue.join()
        finally:
            for task in workers:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    latest = read_latest_records(OUTPUT_FILE)
    batch_records = [latest[key] for key in active_record_keys if key in latest]
    print(f"Results JSONL: {OUTPUT_FILE}")
    print(f"Actor: {TIKTOK_ACTOR_SLUG}")
    print(f"Concurrency: {concurrency}; per-Run wait limit: {max_wait:g} seconds")
    print_summary(batch_records)
    unsuccessful = [
        record for record in batch_records
        if record.get("status") != "completed_with_transcript"
    ]
    if unsuccessful:
        raise SystemExit(
            f"Batch incomplete: {len(unsuccessful)} row(s) failed or need follow-up; "
            "inspect the JSONL results and reconcile unresolved Run creation before retrying."
        )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start one Run per CSV row. Without an id column, URL duplicates use occurrence order as their stable key."
    )
    parser.add_argument("csv_file", nargs="?", type=Path, help="Input CSV with a videoUrl column and optional unique id column.")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help=f"Concurrent Runs (1-{CONCURRENCY_LIMIT}; default: {DEFAULT_CONCURRENCY}).")
    parser.add_argument("--max-wait", type=float, default=DEFAULT_MAX_WAIT, help=f"Maximum wait per Run in seconds (default: {DEFAULT_MAX_WAIT:g}).")
    parser.add_argument("--reconcile", action="store_true", help="Read-only: list records that need manual Run-creation reconciliation.")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    if args.reconcile:
        print_reconciliation_records(read_latest_records(OUTPUT_FILE), os.getenv("APIFY_TOKEN", ""))
        return
    if args.csv_file is None or not args.csv_file.is_file():
        raise SystemExit("Input error: provide an existing CSV file with a videoUrl column.")
    if not 1 <= args.concurrency <= CONCURRENCY_LIMIT:
        raise SystemExit(f"Input error: --concurrency must be between 1 and {CONCURRENCY_LIMIT}.")
    if not math.isfinite(args.max_wait) or args.max_wait <= 0:
        raise SystemExit("Input error: --max-wait must be a finite number greater than zero.")
    token = require_env("APIFY_TOKEN")
    await process_csv(args.csv_file, args.concurrency, args.max_wait, token)


if __name__ == "__main__":
    asyncio.run(main())
