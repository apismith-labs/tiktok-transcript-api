#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

EXPORTED_APIFY_TOKEN="${APIFY_TOKEN-}"
EXPORTED_APIFY_ACTOR_ID="${APIFY_ACTOR_ID-}"
EXPORTED_TIKTOK_VIDEO_URL="${TIKTOK_VIDEO_URL-}"

if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  source "${REPO_ROOT}/.env"
  set +a
fi

if [[ -n "${EXPORTED_APIFY_TOKEN}" ]]; then
  APIFY_TOKEN="${EXPORTED_APIFY_TOKEN}"
fi

if [[ -n "${EXPORTED_APIFY_ACTOR_ID}" ]]; then
  APIFY_ACTOR_ID="${EXPORTED_APIFY_ACTOR_ID}"
fi

if [[ -n "${EXPORTED_TIKTOK_VIDEO_URL}" ]]; then
  TIKTOK_VIDEO_URL="${EXPORTED_TIKTOK_VIDEO_URL}"
fi

ACTOR_ID="${APIFY_ACTOR_ID:-apple_yang/tiktok-transcripts-scraper}"
VIDEO_URL="${1:-${TIKTOK_VIDEO_URL:-https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392}}"
OUTPUT_DIR="${REPO_ROOT}/sample-output/generated"
OUTPUT_FILE="${OUTPUT_DIR}/curl-single-url-response.json"

if [[ -z "${APIFY_TOKEN:-}" ]]; then
  echo "Error: APIFY_TOKEN is required. Set it in your environment or local .env file." >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"

ACTOR_ID_FOR_URL="${ACTOR_ID//\//~}"
API_URL="https://api.apify.com/v2/acts/${ACTOR_ID_FOR_URL}/run-sync-get-dataset-items"

json_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '%s' "${value}"
}

VIDEO_URL_JSON="$(json_escape "${VIDEO_URL}")"

echo "Using Actor ID: ${ACTOR_ID}"
echo "Running request..."

curl \
  --fail-with-body \
  --silent \
  --show-error \
  --request POST "${API_URL}" \
  --header "Authorization: Bearer ${APIFY_TOKEN}" \
  --header "Content-Type: application/json" \
  --data "$(printf '{"videoUrl":"%s"}' "${VIDEO_URL_JSON}")" \
  --output "${OUTPUT_FILE}"

echo "Saved full JSON response to: ${OUTPUT_FILE}"

python3 - "${OUTPUT_FILE}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as file:
    items = json.load(file)

if not items:
    raise SystemExit("Error: Actor returned an empty dataset.")

item = items[0]
text = item.get("text") or ""
print(f"Items: {len(items)}")
print(f"Title: {item.get('title') or ''}")
print(f"Creator: {item.get('nickname') or ''}")
print(f"Play count: {item.get('playCount') or ''}")
print(f"Transcript characters: {len(text)}")
print("Transcript preview:")
print(text[:500])
if item.get("errMsg"):
    print(f"errMsg: {item.get('errMsg')}")
PY
