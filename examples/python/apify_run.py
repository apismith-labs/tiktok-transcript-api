from __future__ import annotations

import http.client
import json
import sys
from typing import Any
from urllib.parse import quote


TIKTOK_ACTOR_SLUG = "apple_yang/tiktok-transcripts-scraper"
TIKTOK_ACTOR_API_ID = "apple_yang~tiktok-transcripts-scraper"
DEFAULT_VIDEO_URL = "https://www.tiktok.com/@carter.braydon/video/7647694374876319007"


class RunStartError(RuntimeError):
    def __init__(self, message: str, *, outcome_unknown: bool) -> None:
        super().__init__(message)
        self.outcome_unknown = outcome_unknown


def require_supported_python() -> None:
    if sys.version_info < (3, 11):
        raise SystemExit(
            "Python 3.11 or newer is required by apify-client==3.3.0. "
            f"Current version: {sys.version_info.major}.{sys.version_info.minor}. "
            "Run this example with Python 3.11+ (for example, `python3.11 script.py`)."
        )


def validate_tiktok_video_url(video_url: str) -> str | None:
    if not video_url or video_url != video_url.strip():
        return "videoUrl is empty or contains surrounding whitespace."
    from urllib.parse import urlparse

    try:
        parsed = urlparse(video_url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return "videoUrl is not a valid TikTok video URL."
    if parsed.scheme != "https" or not (host == "tiktok.com" or host.endswith(".tiktok.com")):
        return "videoUrl must be an HTTPS TikTok URL."
    if "/video/" not in parsed.path:
        return "videoUrl must point to a TikTok video path containing /video/."
    return None


def start_actor_run_once(token: str, video_url: str) -> dict[str, Any]:
    """Send one HTTP POST attempt to Apify's Actor Run endpoint.

    Apify documents the Run endpoint and Bearer authentication, but no applicable
    idempotency key for Actor Run creation was confirmed. This standard-library
    HTTP connection performs no retry or redirect replay; transport/API outcomes
    that cannot be confirmed are reported as unknown and must not be auto-retried.
    This is one client-side send attempt, not a server-side exactly-once guarantee.
    """
    validation_error = validate_tiktok_video_url(video_url)
    if validation_error:
        raise ValueError(f"Input error: {validation_error}")
    path = f"/v2/actors/{quote(TIKTOK_ACTOR_API_ID, safe='~')}/runs"
    body = json.dumps({"videoUrl": video_url}, ensure_ascii=False).encode("utf-8")
    connection = http.client.HTTPSConnection("api.apify.com", timeout=30)
    try:
        connection.request(
            "POST",
            path,
            body=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        response = connection.getresponse()
        response_body = response.read()
    except Exception as exc:
        raise RunStartError(
            "Run creation request did not return a complete response; the Run may have started. "
            "Check Apify Console before taking any further action.",
            outcome_unknown=True,
        ) from exc
    finally:
        connection.close()

    if not 200 <= response.status < 300:
        raise RunStartError(
            f"Apify rejected or did not confirm Run creation (HTTP {response.status}); "
            "treat the outcome as unknown and reconcile before retrying.",
            outcome_unknown=True,
        )
    try:
        payload = json.loads(response_body)
        if not isinstance(payload, dict):
            raise ValueError("successful response JSON must be an object")
        if "data" in payload:
            run = payload["data"]
            if not isinstance(run, dict):
                raise ValueError("successful response 'data' field must be an object")
        else:
            run = payload
        run_id = run.get("id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("successful response must contain a non-empty string Run ID")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RunStartError(
            "Apify returned a successful response with an invalid Run structure or without a readable Run ID; "
            "the Run may have started. Reconcile before taking any further action.",
            outcome_unknown=True,
        ) from exc
    return run
