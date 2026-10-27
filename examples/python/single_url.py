from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

from apify_run import (
    DEFAULT_VIDEO_URL,
    TIKTOK_ACTOR_SLUG,
    RunStartError,
    require_supported_python,
    start_actor_run_once,
    validate_tiktok_video_url,
)

require_supported_python()

from apify_client import ApifyClient
from apify_client.errors import ApifyApiError, NotFoundError
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "sample-output" / "generated"
OUTPUT_FILE = OUTPUT_DIR / "python-single-url-response.json"
DEFAULT_MAX_WAIT = 900
MAX_MAX_WAIT = 86_400
TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Error: {name} is required. Set it in .env or your environment.")
    return value


def preflight_output_directory(directory: Path) -> None:
    """Ensure the result directory is writable before starting a billable Run."""
    probe_path: str | None = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        descriptor, probe_path = tempfile.mkstemp(prefix=".tiktok-transcript-output-probe-", dir=directory)
        os.close(descriptor)
        os.unlink(probe_path)
        probe_path = None
    except OSError as exc:
        if probe_path is not None:
            try:
                os.unlink(probe_path)
            except OSError:
                pass
        raise SystemExit(f"Output directory preflight failed for {directory}: {exc}") from None


def first_value(items: list[dict[str, Any]], key: str) -> Any:
    for item in items:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None


def parse_max_wait(value: str) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("--max-wait must be a whole number of seconds") from exc
    if seconds < 1 or seconds > MAX_MAX_WAIT:
        raise argparse.ArgumentTypeError(f"--max-wait must be between 1 and {MAX_MAX_WAIT} seconds")
    return seconds


def run_field(run: Any, key: str) -> Any:
    if isinstance(run, dict):
        return run.get(key)
    attribute = {"defaultDatasetId": "default_dataset_id"}.get(key, key)
    return getattr(run, attribute, None)


def redact_token(message: str, token: str) -> str:
    return message.replace(token, "[REDACTED]") if token else message


def wait_timeout_message(run_id: str, max_wait: int, status: str, detail: str = "") -> str:
    message = (
        f"Wait limit reached after {max_wait} seconds; Run {run_id} may still be running "
        f"(status: {status}). Continue with: python3 examples/python/async_run.py "
        f"wait --run-id {run_id} --max-wait {max_wait}"
    )
    return f"{message}. Read-only status recheck: {detail}" if detail else message


def wait_for_existing_run(client: Any, run_id: str, max_wait: int) -> Any:
    """Wait for and, on timeout, inspect only the specified existing Run."""
    if not isinstance(max_wait, int) or isinstance(max_wait, bool) or not 1 <= max_wait <= MAX_MAX_WAIT:
        raise ValueError(f"--max-wait must be between 1 and {MAX_MAX_WAIT} seconds")
    run_client = client.run(run_id)
    try:
        run = run_client.wait_for_finish(wait_duration=timedelta(seconds=max_wait))
    except TimeoutError:
        run = None
    except NotFoundError as exc:
        detail = redact_token(str(exc), os.getenv("APIFY_TOKEN", ""))
        raise SystemExit(f"Run {run_id} was not found: {detail}") from None
    except ApifyApiError as exc:
        detail = redact_token(str(exc), os.getenv("APIFY_TOKEN", ""))
        if getattr(exc, "status_code", None) == 404:
            raise SystemExit(f"Run {run_id} was not found: {detail}") from None
        raise SystemExit(f"Run status/API error for {run_id}: {detail}") from None
    except TypeError as exc:
        detail = redact_token(str(exc), os.getenv("APIFY_TOKEN", ""))
        raise SystemExit(f"Local SDK wait-call error for Run {run_id}: {detail}") from None
    except Exception as exc:
        token = os.getenv("APIFY_TOKEN", "")
        detail = redact_token(str(exc), token)
        raise SystemExit(f"Unexpected error while waiting for existing Run {run_id}: {detail}") from None

    observed_nonterminal = False
    if run is not None:
        initial_status = run_field(run, "status")
        if not isinstance(initial_status, str) or not initial_status.strip():
            raise SystemExit(f"Run lookup error: Apify returned no valid status for Run {run_id}.")
        observed_nonterminal = initial_status not in TERMINAL_STATUSES

    if run is None or observed_nonterminal:
        try:
            current = run_client.get()
        except NotFoundError as exc:
            token = os.getenv("APIFY_TOKEN", "")
            detail = redact_token(str(exc), token)
            if observed_nonterminal:
                raise SystemExit(wait_timeout_message(run_id, max_wait, initial_status, detail)) from None
            raise SystemExit(f"Run {run_id} was not found after the wait limit: {detail}") from None
        except ApifyApiError as exc:
            token = os.getenv("APIFY_TOKEN", "")
            detail = redact_token(str(exc), token)
            if getattr(exc, "status_code", None) == 404:
                raise SystemExit(f"Run {run_id} was not found after the wait limit: {detail}") from None
            if observed_nonterminal:
                raise SystemExit(wait_timeout_message(run_id, max_wait, initial_status, detail)) from None
            raise SystemExit(f"Could not read Run {run_id} after the wait limit: {detail}") from None
        except TypeError as exc:
            token = os.getenv("APIFY_TOKEN", "")
            detail = redact_token(str(exc), token)
            if observed_nonterminal:
                raise SystemExit(wait_timeout_message(run_id, max_wait, initial_status, detail)) from None
            raise SystemExit(f"Local SDK Run-read error for {run_id}: {detail}") from None
        except Exception as exc:
            token = os.getenv("APIFY_TOKEN", "")
            detail = redact_token(str(exc), token)
            if observed_nonterminal:
                raise SystemExit(wait_timeout_message(run_id, max_wait, initial_status, detail)) from None
            raise SystemExit(f"Unexpected error while reading existing Run {run_id}: {detail}") from None
        if current is None:
            if observed_nonterminal:
                status = initial_status
            else:
                raise SystemExit(f"Run {run_id} could not be found after the wait limit; no new Run was created.")
        else:
            status = run_field(current, "status")
            if not isinstance(status, str) or not status.strip():
                raise SystemExit(f"Run lookup error: Apify returned no valid status for Run {run_id}.")
            if status in TERMINAL_STATUSES:
                run = current
        if status not in TERMINAL_STATUSES:
            raise SystemExit(wait_timeout_message(run_id, max_wait, status))
    return run


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch a transcript from the fixed TikTok Transcript Actor.")
    parser.add_argument("video_url", nargs="?", help="TikTok video URL (defaults to the verified sample URL).")
    parser.add_argument("--video-url", dest="video_url_option", help="TikTok video URL (alternative to the positional URL).")
    parser.add_argument(
        "--max-wait",
        type=parse_max_wait,
        default=DEFAULT_MAX_WAIT,
        help=f"Maximum wait duration in seconds (1-{MAX_MAX_WAIT}; default: {DEFAULT_MAX_WAIT}).",
    )
    args = parser.parse_args()
    if args.video_url is not None and args.video_url_option is not None:
        parser.error("provide the video URL either positionally or with --video-url, not both")
    if args.video_url_option is not None:
        video_url = args.video_url_option
    elif args.video_url is not None:
        video_url = args.video_url
    else:
        video_url = DEFAULT_VIDEO_URL
    validation_error = validate_tiktok_video_url(video_url)
    if validation_error:
        raise SystemExit(f"Input error: {validation_error}")

    preflight_output_directory(OUTPUT_DIR)

    load_dotenv(REPO_ROOT / ".env")

    token = require_env("APIFY_TOKEN")
    client = ApifyClient(token=token)
    print(f"Actor: {TIKTOK_ACTOR_SLUG}", flush=True)
    print("Starting one Actor Run and waiting for its terminal state...", flush=True)

    try:
        # Run creation uses one standard-library HTTP POST attempt. The SDK then
        # handles only safe reads while waiting for this known Run ID.
        started = start_actor_run_once(token, video_url)
    except RunStartError as exc:
        detail = str(exc).replace(token, "[REDACTED]")
        raise SystemExit(
            "Run creation result is unknown; check Apify Console to see whether it was created. "
            f"Do not retry or start another Run until checked. Details: {detail}"
        ) from None
    except Exception as exc:
        detail = str(exc).replace(token, "[REDACTED]")
        raise SystemExit(
            "Run creation result is unknown; check Apify Console before taking further action. "
            f"Do not retry directly. Details: {detail}"
        ) from None

    run_id = str(started["id"])
    print(f"Run ID: {run_id}", flush=True)
    try:
        run = wait_for_existing_run(client, run_id, args.max_wait)
    except Exception as exc:
        if isinstance(exc, SystemExit):
            raise
        detail = str(exc).replace(token, "[REDACTED]") if token else str(exc)
        raise SystemExit(f"Run lookup/wait error for {run_id}: {detail}") from None

    if run is None:
        raise SystemExit(f"Run {run_id} could not be retrieved; its state is unknown.")

    status = run_field(run, "status")
    if not isinstance(status, str) or not status.strip():
        raise SystemExit(f"Run lookup error: Apify returned no valid status for Run {run_id}.")
    if status not in TERMINAL_STATUSES:
        raise SystemExit(f"Run has not completed (current status: {status}).")
    if status != "SUCCEEDED":
        raise SystemExit(f"Actor Run finished with failure status {status}.")

    dataset_id = run_field(run, "defaultDatasetId")
    if not dataset_id:
        raise SystemExit("Dataset error: completed Run has no default Dataset ID.")

    try:
        items = list(client.dataset(dataset_id).iterate_items())
    except Exception as exc:
        detail = str(exc).replace(token, "[REDACTED]")
        raise SystemExit(f"Dataset read error for {dataset_id}: {detail}") from exc
    if not items:
        raise SystemExit("Dataset is empty: the Run completed but returned no items.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    text = first_value(items, "text") or ""
    print(f"Output path: {OUTPUT_FILE}")
    print(f"Items: {len(items)}")
    print(f"Run status: {status}")
    print(f"Title: {first_value(items, 'title') or ''}")
    print(f"Creator: {first_value(items, 'nickname') or ''}")
    print(f"Play count: {first_value(items, 'playCount') or ''}")
    print("text:")
    print(text if isinstance(text, str) else "")
    print("segments:")
    print(json.dumps(first_value(items, "segments") or [], indent=2, ensure_ascii=False))
    err_msg = first_value(items, "errMsg")
    print(f"errMsg: {err_msg or ''}")
    transcript_problems: list[str] = []
    if not isinstance(text, str) or not text.strip():
        transcript_problems.append("transcript text is empty or missing")
    if err_msg:
        transcript_problems.append(f"Actor errMsg is non-empty: {err_msg}")
    if transcript_problems:
        raise SystemExit("Transcript failure: " + "; ".join(transcript_problems))


if __name__ == "__main__":
    main()
