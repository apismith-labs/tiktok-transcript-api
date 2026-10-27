#!/usr/bin/env bash
set -euo pipefail

# This script makes one client-side POST attempt. That does not guarantee
# exactly-once processing on the server. If the response is uncertain, check
# the Apify Console before starting another Run.

readonly ACTOR_SLUG="apple_yang/tiktok-transcripts-scraper"
readonly ACTOR_API_ID="apple_yang~tiktok-transcripts-scraper"
readonly API_HOST="https://api.apify.com"
readonly DEFAULT_VIDEO_URL="https://www.tiktok.com/@carter.braydon/video/7647694374876319007"
readonly DEFAULT_MAX_WAIT=900

COMMAND="run"
COMMAND_OPTION_SET=0
VIDEO_URL="${DEFAULT_VIDEO_URL}"
RUN_ID=""
MAX_WAIT="${DEFAULT_MAX_WAIT}"
MAX_WAIT_OPTION_SET=0
OUTPUT_FILE=""
OUTPUT_OPTION_SET=0
POSITIONAL_URL=""
VIDEO_URL_OPTION_SET=0

usage() {
  cat <<'USAGE'
Usage:
  single-url-sync.sh [run] [--video-url URL] [--max-wait SECONDS] [--output FILE]
  single-url-sync.sh start [--video-url URL]
  single-url-sync.sh wait --run-id RUN_ID [--max-wait SECONDS] [--output FILE]

Commands:
  run    Create one Run, print its ID, wait, and read its Dataset (default).
  start  Create one Run and print its ID without waiting.
  wait   Wait for and read an existing Run. This command never creates a Run.

Options:
  --video-url URL  TikTok video URL; defaults to the bundled test video.
  --run-id ID      Existing Run ID (required by wait).
  --max-wait N     Wait limit in seconds, 1 through 86400 (default: 900).
  --output FILE    Dataset JSON destination; defaults to the ignored generated directory.
  -h, --help       Show this help.

APIFY_TOKEN must be set in the environment. This script does not read .env.
USAGE
}

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit "${2:-1}"
}

validate_max_wait() {
  local value="$1"
  [[ "$value" =~ ^[0-9]+$ ]] || fail "--max-wait must be an integer from 1 through 86400 seconds."
  # Strip leading zeroes before arithmetic so bash cannot interpret octal values.
  while [[ "$value" == 0* && "$value" != 0 ]]; do value="${value#0}"; done
  ((${#value} <= 5)) || fail "--max-wait must be from 1 through 86400 seconds."
  (( value >= 1 && value <= 86400 )) || fail "--max-wait must be from 1 through 86400 seconds."
  MAX_WAIT="$value"
}

validate_video_url() {
  python3 - "$1" <<'PY'
import re
import sys
from urllib.parse import urlsplit

try:
    value = sys.argv[1]
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    valid_host = host == "tiktok.com" or host.endswith(".tiktok.com")
    valid_path = re.fullmatch(r"/@[^/]+/video/[0-9]+/?", parsed.path or "") is not None
    valid = parsed.scheme == "https" and valid_host and parsed.username is None and parsed.password is None and valid_path
except (IndexError, ValueError):
    valid = False

if not valid:
    print("Error: video URL must be an HTTPS TikTok video URL containing /video/<numeric-id>.", file=sys.stderr)
    raise SystemExit(1)
PY
}

while (($#)); do
  case "$1" in
    run|start|wait)
      [[ "$COMMAND_OPTION_SET" == 0 ]] || fail "provide exactly one command (run, start, or wait)."
      COMMAND="$1"
      COMMAND_OPTION_SET=1
      shift
      ;;
    --video-url)
      (($# >= 2)) || fail "--video-url requires a URL."
      [[ "$VIDEO_URL_OPTION_SET" == 0 ]] || fail "provide the video URL only once."
      VIDEO_URL="$2"
      VIDEO_URL_OPTION_SET=1
      shift 2
      ;;
    --run-id)
      (($# >= 2)) || fail "--run-id requires an ID."
      [[ -z "$RUN_ID" ]] || fail "provide --run-id only once."
      RUN_ID="$2"
      shift 2
      ;;
    --max-wait)
      (($# >= 2)) || fail "--max-wait requires a number of seconds."
      validate_max_wait "$2"
      MAX_WAIT_OPTION_SET=1
      shift 2
      ;;
    --output)
      (($# >= 2)) || fail "--output requires a file path."
      [[ "$OUTPUT_OPTION_SET" == 0 ]] || fail "provide --output only once."
      OUTPUT_FILE="$2"
      OUTPUT_OPTION_SET=1
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      fail "unknown option: $1"
      ;;
    *)
      [[ -z "$POSITIONAL_URL" ]] || fail "provide at most one positional video URL."
      [[ "$VIDEO_URL_OPTION_SET" == 0 ]] || fail "do not combine a positional URL with --video-url."
      POSITIONAL_URL="$1"
      VIDEO_URL="$1"
      shift
      ;;
  esac
done

if [[ "$COMMAND" == "wait" ]]; then
  [[ "$VIDEO_URL_OPTION_SET" == 0 && -z "$POSITIONAL_URL" ]] || fail "wait accepts a Run ID, not a video URL."
  [[ "$RUN_ID" =~ ^[A-Za-z0-9_-]+$ ]] || fail "wait requires a valid --run-id."
else
  [[ -z "$RUN_ID" ]] || fail "--run-id is only valid with wait."
  validate_video_url "$VIDEO_URL" || exit 2
fi
if [[ "$COMMAND" == "start" ]]; then
  [[ "$MAX_WAIT_OPTION_SET" == 0 ]] || fail "--max-wait is not valid with start; pass it later to wait."
  [[ "$OUTPUT_OPTION_SET" == 0 ]] || fail "--output is not valid with start; pass it later to wait."
fi

if [[ -z "${APIFY_TOKEN:-}" ]]; then
  fail "APIFY_TOKEN is required in the environment."
fi
if [[ "$APIFY_TOKEN" == *$'\n'* || "$APIFY_TOKEN" == *$'\r'* ]]; then
  fail "APIFY_TOKEN contains unsupported control characters."
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SCRIPT_PATH="${SCRIPT_DIR}/$(basename "${BASH_SOURCE[0]}")"

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/tiktok-curl.XXXXXX")" || fail "could not create a temporary directory."
OUTPUT_PROBE_FILE=""
cleanup() {
  [[ -z "$OUTPUT_PROBE_FILE" ]] || rm -f "$OUTPUT_PROBE_FILE"
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

print_wait_command() {
  local run_id="$1"
  local wait_seconds="$2"
  printf 'Wait command (same Run ID):\n'
  printf 'bash %q wait --run-id %q --max-wait %q\n' "$SCRIPT_PATH" "$run_id" "$wait_seconds"
}

response_is_json_object() {
  python3 - "$1" <<'PY'
import json
import sys
try:
    with open(sys.argv[1], encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict) or not value.get("error"):
        raise ValueError
except (OSError, ValueError, TypeError, json.JSONDecodeError):
    raise SystemExit(1)
PY
}

preflight_output_directory() {
  local output_directory
  if [[ -z "$OUTPUT_FILE" ]]; then
    output_directory="${REPO_ROOT}/sample-output/generated"
  else
    if [[ "$OUTPUT_FILE" != /* ]]; then OUTPUT_FILE="${PWD}/${OUTPUT_FILE}"; fi
    output_directory="$(dirname "$OUTPUT_FILE")"
  fi
  if ! mkdir -p "$output_directory"; then
    fail "Output directory preflight failed: could not create ${output_directory}."
  fi
  OUTPUT_PROBE_FILE="$(mktemp "${output_directory}/.tiktok-transcript-output-probe.XXXXXX")" || \
    fail "Output directory preflight failed: could not create a probe file in ${output_directory}."
  if ! rm -f "$OUTPUT_PROBE_FILE"; then
    fail "Output directory preflight failed: could not remove its probe file from ${output_directory}."
  fi
  OUTPUT_PROBE_FILE=""
}

request_once() {
  local method="$1"
  local url="$2"
  local response_file="$3"
  local payload="${4:-}"
  local max_time="${5:-60}"
  local status=""
  local curl_exit=0
  local auth_config="${TMP_DIR}/curl-auth.conf"
  LAST_CURL_EXIT=0
  LAST_HTTP_STATUS=""

  # curl reads the credential from a mode-0600 config file, never from argv or
  # its environment. Its request body remains a separate --data-binary input.
  if ! (umask 077; printf '%s' "$APIFY_TOKEN" | python3 -c 'import json,sys; token=sys.stdin.read(); print("header = " + json.dumps("Authorization: Bearer " + token))' >"$auth_config"); then
    return 1
  fi
  chmod 600 "$auth_config" || { rm -f "$auth_config"; return 1; }

  if [[ "$method" == "POST" ]]; then
    # Deliberately no --retry and no --location: the Run creation POST is sent
    # once by this client. An uncertain response must never trigger a re-POST.
    status="$(env -u APIFY_TOKEN curl --config "$auth_config" --silent --output "$response_file" --write-out '%{http_code}' \
      --request POST "${API_HOST}/v2/actors/${ACTOR_API_ID}/runs" \
      --header 'Content-Type: application/json' \
      --data-binary "$payload" --max-time "$max_time" 2>/dev/null)" || curl_exit=$?
  else
    status="$(env -u APIFY_TOKEN curl --config "$auth_config" --silent --output "$response_file" --write-out '%{http_code}' \
      --request GET "$url" \
      --max-time "$max_time" 2>/dev/null)" || curl_exit=$?
  fi
  rm -f "$auth_config"
  LAST_CURL_EXIT="$curl_exit"
  LAST_HTTP_STATUS="$status"
  ((curl_exit == 0)) || return 1
  [[ "$status" =~ ^2[0-9][0-9]$ ]] || return 1
}

start_run() {
  local response_file="${TMP_DIR}/create.json"
  local payload run_id

  payload="$(python3 -c 'import json,sys; print(json.dumps({"videoUrl":sys.argv[1]}, separators=(",", ":")))' "$VIDEO_URL")" \
    || fail "could not encode the video URL."
  printf 'Actor: %s\n' "$ACTOR_SLUG"
  printf 'Creating one Run. A client-side single send is not a server-side exactly-once guarantee.\n'

  if ! request_once POST "${API_HOST}/v2/actors/${ACTOR_API_ID}/runs" "$response_file" "$payload" 60; then
    if ((LAST_CURL_EXIT == 0)) && [[ "$LAST_HTTP_STATUS" =~ ^4[0-9][0-9]$ ]] && response_is_json_object "$response_file"; then
      printf 'Run creation was rejected by Apify with HTTP %s; the Run was not created. Check APIFY_TOKEN, permissions, and input, then correct the request before starting again.\n' "$LAST_HTTP_STATUS" >&2
      return 2
    fi
    printf 'Run creation outcome is unknown. Check the Apify Console first; do not retry or create another Run before checking.\n' >&2
    return 3
  fi

  if ! run_id="$(python3 - "$response_file" <<'PY'
import json
import re
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as source:
        payload = json.load(source)
    data = payload.get("data") if isinstance(payload, dict) else None
    run_id = data.get("id") if isinstance(data, dict) else None
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError
    print(run_id)
except (OSError, ValueError, TypeError, json.JSONDecodeError):
    raise SystemExit(1)
PY
  )"; then
    printf 'Run creation outcome is unknown: the response did not contain a valid Run ID. Check the Apify Console first; do not retry or create another Run before checking.\n' >&2
    return 3
  fi

  RUN_ID="$run_id"
  # Use Python's explicit flush so piped or redirected output exposes this ID
  # before the first polling request begins.
  python3 -c 'import sys; print("Run ID: " + sys.argv[1], flush=True)' "$RUN_ID"
  if [[ "$COMMAND" == "start" ]]; then
    print_wait_command "$RUN_ID" "$DEFAULT_MAX_WAIT"
  fi
}

wait_for_run() {
  local run_id="$1"
  local deadline=$((SECONDS + MAX_WAIT))
  local run_response="${TMP_DIR}/run.json"
  local metadata_file="${TMP_DIR}/run-meta"
  local dataset_file="${TMP_DIR}/dataset.json"
  local result_stdout="${TMP_DIR}/dataset-result.stdout"
  local result_stderr="${TMP_DIR}/dataset-result.stderr"
  local remaining status dataset_id result_exit=0

  if [[ -z "$OUTPUT_FILE" ]]; then
    OUTPUT_FILE="${REPO_ROOT}/sample-output/generated/curl-transcript-${run_id}.json"
  fi

  printf 'Waiting for Run %s (maximum %s seconds). Reuse this same Run ID if you need to wait again.\n' "$run_id" "$MAX_WAIT"
  while true; do
    remaining=$((deadline - SECONDS))
    if ((remaining < 1)); then
      printf 'Wait limit reached. Run %s may still be running; use this same Run ID to wait again.\n' "$run_id" >&2
      print_wait_command "$run_id" "$MAX_WAIT" >&2
      return 4
    fi

    if ! request_once GET "${API_HOST}/v2/actor-runs/${run_id}" "$run_response" "" "$remaining"; then
      if ((SECONDS >= deadline)); then
        printf 'Wait limit reached. Run %s may still be running; use this same Run ID to wait again.\n' "$run_id" >&2
        print_wait_command "$run_id" "$MAX_WAIT" >&2
        return 4
      fi
      printf 'Could not read Run %s. No new Run was created; retry the read later with this same Run ID.\n' "$run_id" >&2
      return 5
    fi

    if ! python3 - "$run_response" "$run_id" >"$metadata_file" <<'PY'
import json
import re
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as source:
        payload = json.load(source)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or data.get("id") != sys.argv[2]:
        raise ValueError
    status = data.get("status")
    if not isinstance(status, str) or not status.strip():
        raise ValueError
    dataset_id = data.get("defaultDatasetId")
    if not isinstance(dataset_id, str):
        dataset_id = ""
    elif dataset_id and not re.fullmatch(r"[A-Za-z0-9_-]+", dataset_id):
        raise ValueError
    print(status.strip())
    print(dataset_id)
except (OSError, ValueError, TypeError, json.JSONDecodeError):
    raise SystemExit(1)
PY
    then
      printf 'Invalid Apify Run response while reading Run %s. No new Run was created.\n' "$run_id" >&2
      return 5
    fi
    {
      IFS= read -r status || true
      IFS= read -r dataset_id || true
    } <"$metadata_file"
    status="${status:-}"
    dataset_id="${dataset_id:-}"

    case "$status" in
      SUCCEEDED) break ;;
      FAILED|TIMED-OUT|ABORTED)
        printf 'Run %s finished with status %s.\n' "$run_id" "$status" >&2
        return 6
        ;;
    esac

    remaining=$((deadline - SECONDS))
    if ((remaining < 1)); then
      printf 'Wait limit reached. Run %s may still be running; use this same Run ID to wait again.\n' "$run_id" >&2
      print_wait_command "$run_id" "$MAX_WAIT" >&2
      return 4
    fi
    sleep 1
  done

  if [[ -z "$dataset_id" ]]; then
    printf 'Run %s succeeded but has no default Dataset ID.\n' "$run_id" >&2
    return 7
  fi
  if ! request_once GET "${API_HOST}/v2/datasets/${dataset_id}/items" "$dataset_file" "" 60; then
    printf 'Run %s succeeded, but Dataset %s could not be read.\n' "$run_id" "$dataset_id" >&2
    return 8
  fi

  if [[ -z "$OUTPUT_FILE" ]]; then
    OUTPUT_FILE="${REPO_ROOT}/sample-output/generated/curl-transcript-${run_id}.json"
  elif [[ "$OUTPUT_FILE" != /* ]]; then
    OUTPUT_FILE="${PWD}/${OUTPUT_FILE}"
  fi
  mkdir -p "$(dirname "$OUTPUT_FILE")"
  APIFY_OUTPUT_FILE="$OUTPUT_FILE" python3 - "$dataset_file" >"$result_stdout" 2>"$result_stderr" <<'PY' || result_exit=$?
import json
import os
import sys

def redact(value, token):
    if not token:
        return value
    if isinstance(value, str):
        return value.replace(token, "[REDACTED]")
    if isinstance(value, list):
        return [redact(item, token) for item in value]
    if isinstance(value, dict):
        return {redact(key, token): redact(item, token) for key, item in value.items()}
    return value

try:
    with open(sys.argv[1], encoding="utf-8") as source:
        items = json.load(source)
    if not isinstance(items, list):
        raise ValueError
except (OSError, ValueError, TypeError, json.JSONDecodeError):
    print("Error: Dataset response was not a JSON array.", file=sys.stderr)
    raise SystemExit(9)

token = os.environ.get("APIFY_TOKEN", "")
safe_items = redact(items, token)
output_path = os.environ["APIFY_OUTPUT_FILE"]
try:
    with open(output_path, "w", encoding="utf-8") as destination:
        json.dump(safe_items, destination, ensure_ascii=False, indent=2)
        destination.write("\n")
except OSError:
    print("Error: could not save Dataset Items JSON.", file=sys.stderr)
    raise SystemExit(10)

if not items:
    print("Error: Run succeeded, but the Dataset is empty.", file=sys.stderr)
    raise SystemExit(11)

errors = []
texts = []
for item in items:
    if not isinstance(item, dict):
        continue
    err = item.get("errMsg")
    if err is not None and str(err).strip():
        errors.append(str(err).strip())
    text = item.get("text")
    if isinstance(text, str) and text.strip():
        texts.append(text)

if errors:
    safe_errors = [redact(error, token) for error in errors]
    print("Error: Actor returned errMsg: " + "; ".join(safe_errors), file=sys.stderr)
    raise SystemExit(12)
if not texts:
    print("Error: Run completed, but transcript text is empty or missing.", file=sys.stderr)
    raise SystemExit(13)

print("Transcript:")
print("\n".join(redact(text, token) for text in texts))
PY
  if [[ -s "$result_stdout" ]]; then cat "$result_stdout"; fi
  case "$result_exit" in
    0) printf 'Complete Dataset Items JSON saved: %s\n' "$OUTPUT_FILE" ;;
    11|12|13) printf 'Dataset Items saved for diagnosis: %s\n' "$OUTPUT_FILE" ;;
  esac
  if [[ -s "$result_stderr" ]]; then cat "$result_stderr" >&2; fi
  return "$result_exit"
}

if [[ "$COMMAND" == "run" || "$COMMAND" == "wait" ]]; then
  preflight_output_directory
fi

case "$COMMAND" in
  start)
    start_run || exit $?
    ;;
  wait)
    wait_for_run "$RUN_ID"
    ;;
  run)
    start_run || exit $?
    wait_for_run "$RUN_ID"
    ;;
esac
