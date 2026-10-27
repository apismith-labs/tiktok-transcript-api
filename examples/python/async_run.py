from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from pathlib import Path

from apify_run import (
    DEFAULT_VIDEO_URL,
    TIKTOK_ACTOR_SLUG,
    RunStartError,
    require_supported_python,
    start_actor_run_once,
    validate_tiktok_video_url,
)

require_supported_python()

from apify_client import ApifyClientAsync
from apify_client.errors import ApifyApiError, NotFoundError
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "sample-output" / "generated"
TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Error: {name} is required. Set it in .env or your environment.")
    return value


async def start_run(token: str, video_url: str) -> None:
    print(f"Actor: {TIKTOK_ACTOR_SLUG}")
    try:
        # This helper makes one HTTP POST attempt; it does not rely on SDK retry settings.
        run = start_actor_run_once(token, video_url)
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
    print(json.dumps({"run_id": run["id"], "status": run.get("status")}, ensure_ascii=False))


async def fetch_run_result(client: ApifyClientAsync, run_id: str, max_wait: float, token: str) -> None:
    run_client = client.run(run_id)
    try:
        run = await run_client.get()
    except NotFoundError as exc:
        raise SystemExit(f"Run not found: {run_id}. No new Run was created.") from exc
    except ApifyApiError as exc:
        detail = str(exc).replace(token, "[REDACTED]")
        raise SystemExit(f"Run read error for {run_id}; no new Run was created: {detail}") from exc
    except Exception as exc:
        detail = str(exc).replace(token, "[REDACTED]")
        raise SystemExit(f"Run read/network error for {run_id}; no new Run was created: {detail}") from exc

    if run is None:
        raise SystemExit(f"Run not found: {run_id}. No new Run was created.")

    if str(run.status) not in TERMINAL_STATUSES:
        try:
            run = await asyncio.wait_for(run_client.wait_for_finish(), timeout=max_wait)
        except asyncio.TimeoutError as exc:
            raise SystemExit(
                f"Wait limit reached after {max_wait:g} seconds. Run {run_id} may still be running; "
                f"wait again with the same run_id: --run-id {run_id}.",
            ) from exc
        except ApifyApiError as exc:
            detail = str(exc).replace(token, "[REDACTED]")
            raise SystemExit(f"Run wait/read error for {run_id}; it may still be running: {detail}") from exc
        except Exception as exc:
            detail = str(exc).replace(token, "[REDACTED]")
            raise SystemExit(f"Run wait/network error for {run_id}; it may still be running: {detail}") from exc

    status = str(run.status)
    print(f"Run ID: {run.id}")
    print(f"Run status: {status}")
    if status not in TERMINAL_STATUSES:
        raise SystemExit(f"Run {run_id} has not completed (current status: {status}).")
    if status != "SUCCEEDED":
        raise SystemExit(f"Actor Run finished with status {status}; no transcript success is implied.")

    dataset_id = run.default_dataset_id
    if not dataset_id:
        raise SystemExit("Dataset error: completed Run has no default Dataset ID.")

    try:
        items = [item async for item in client.dataset(dataset_id).iterate_items()]
    except Exception as exc:
        detail = str(exc).replace(token, "[REDACTED]")
        raise SystemExit(f"Dataset read error for {dataset_id}: {detail}") from exc
    if not items:
        raise SystemExit("Dataset is empty: Run completed but returned no items.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"python-async-run-{run_id}.json"
    output_path.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    text = next((item.get("text") for item in items if item.get("text") is not None), None)
    segments = next((item.get("segments") for item in items if item.get("segments") is not None), None)
    err_msg = next((item.get("errMsg") for item in items if item.get("errMsg") is not None), None)
    print(f"Dataset ID: {dataset_id}")
    print(f"Items: {len(items)}")
    print(f"Output path: {output_path}")
    print(f"text: {text if isinstance(text, str) else ''}")
    print(f"segments: {json.dumps(segments or [], indent=2, ensure_ascii=False)}")
    print(f"errMsg: {err_msg or ''}")
    transcript_problems: list[str] = []
    if not isinstance(text, str) or not text.strip():
        transcript_problems.append("transcript text is empty or missing")
    if err_msg:
        transcript_problems.append(f"Actor errMsg is non-empty: {err_msg}")
    if transcript_problems:
        raise SystemExit("Transcript failure: " + "; ".join(transcript_problems))


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start a Run now, or wait for an existing Run ID and fetch its Dataset."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    start_parser = subparsers.add_parser("start", help="Start one Run and print its run_id immediately.")
    start_parser.add_argument("--video-url", default=DEFAULT_VIDEO_URL, help="One TikTok video URL (defaults to the verified sample URL).")
    wait_parser = subparsers.add_parser("wait", help="Wait for an existing Run and save its Dataset items.")
    wait_parser.add_argument("--run-id", required=True, help="An existing Apify Run ID.")
    wait_parser.add_argument("--max-wait", type=float, default=900, help="Maximum wait duration in seconds (default: 900).")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    token = require_env("APIFY_TOKEN")
    client = ApifyClientAsync(token=token)

    if args.command == "start":
        validation_error = validate_tiktok_video_url(args.video_url)
        if validation_error:
            raise SystemExit(f"Input error: {validation_error}")
        await start_run(token, args.video_url)
    else:
        if not args.run_id.strip():
            raise SystemExit("Input error: --run-id cannot be empty.")
        if not math.isfinite(args.max_wait) or args.max_wait <= 0:
            raise SystemExit("Input error: --max-wait must be a finite number greater than zero.")
        await fetch_run_result(client, args.run_id.strip(), args.max_wait, token)


if __name__ == "__main__":
    asyncio.run(main())
