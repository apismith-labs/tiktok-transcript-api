from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from apify_client import ApifyClient
from dotenv import load_dotenv


DEFAULT_ACTOR_ID = "apple_yang/tiktok-transcripts-scraper"
DEFAULT_VIDEO_URL = "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "sample-output" / "generated"
OUTPUT_FILE = OUTPUT_DIR / "python-single-url-response.json"


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Error: {name} is required. Set it in .env or your environment.")
    return value


def first_value(items: list[dict[str, Any]], key: str) -> Any:
    for item in items:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")

    token = require_env("APIFY_TOKEN")
    actor_id = os.getenv("APIFY_ACTOR_ID", DEFAULT_ACTOR_ID)
    video_url = sys.argv[1] if len(sys.argv) > 1 else os.getenv("TIKTOK_VIDEO_URL", DEFAULT_VIDEO_URL)

    client = ApifyClient(token)
    print(f"Actor ID: {actor_id}")
    print("Running request...")

    run = client.actor(actor_id).call(run_input={"videoUrl": video_url})
    status = (run or {}).get("status")
    if status and status != "SUCCEEDED":
        raise SystemExit(f"Error: Actor run finished with status {status}.")

    dataset_id = (run or {}).get("defaultDatasetId")
    if not dataset_id:
        raise SystemExit("Error: Actor run completed without a defaultDatasetId.")

    items = client.dataset(dataset_id).list_items().items
    if not items:
        raise SystemExit("Error: Actor returned an empty dataset.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    text = first_value(items, "text") or ""
    print(f"Output path: {OUTPUT_FILE}")
    print(f"Items: {len(items)}")
    print(f"Title: {first_value(items, 'title') or ''}")
    print(f"Creator: {first_value(items, 'nickname') or ''}")
    print(f"Play count: {first_value(items, 'playCount') or ''}")
    print(f"Transcript characters: {len(text) if isinstance(text, str) else 0}")
    if isinstance(text, str) and text:
        print("Transcript preview:")
        print(text[:500])
    err_msg = first_value(items, "errMsg")
    if err_msg:
        print(f"errMsg: {err_msg}")


if __name__ == "__main__":
    main()
