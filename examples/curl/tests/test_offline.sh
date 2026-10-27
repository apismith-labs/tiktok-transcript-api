#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="${SCRIPT_DIR}/single-url-sync.sh"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/tiktok-curl-test.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT
mkdir -p "${TMP_DIR}/bin"

cat >"${TMP_DIR}/bin/curl" <<'FAKE_CURL'
#!/usr/bin/env bash
set -euo pipefail
method="GET"
url=""
output=""
write_out=""
auth=""
body=""
config_file=""
args="$(printf '%q ' "$@")"
while (($#)); do
  case "$1" in
    --config) config_file="$2"; shift 2 ;;
    --request) method="$2"; shift 2 ;;
    --output) output="$2"; shift 2 ;;
    --write-out) write_out="$2"; shift 2 ;;
    --header)
      case "$2" in Authorization:*) auth="$2" ;; esac
      shift 2
      ;;
    --data-binary) body="$2"; shift 2 ;;
    --max-time) shift 2 ;;
    --silent) shift ;;
    --*) printf 'unexpected fake curl option\n' >&2; exit 90 ;;
    -*) printf 'unexpected fake curl short option\n' >&2; exit 90 ;;
    https://*) url="$1"; shift ;;
    *) printf 'unexpected fake curl argument\n' >&2; exit 90 ;;
  esac
done

if [[ -n "$config_file" ]]; then
  auth="$(python3 - "$config_file" <<'PY'
import json,sys
line=open(sys.argv[1],encoding="utf-8").read().strip()
assert line.startswith("header = ")
value=json.loads(line[len("header = "):])
assert value.startswith("Authorization: Bearer ")
print(value)
PY
)"
  config_mode="$(python3 - "$config_file" <<'PY'
import os,stat,sys
print(oct(stat.S_IMODE(os.stat(sys.argv[1]).st_mode)))
PY
)"
fi

python3 - "$CURL_LOG" "$method" "$url" "$auth" "$body" "${config_mode:-}" "$args" "$config_file" <<'PY'
import json
import sys
record = dict(method=sys.argv[2], url=sys.argv[3], authorization=sys.argv[4], body=sys.argv[5], config_mode=sys.argv[6], args=sys.argv[7], config_file=sys.argv[8])
with open(sys.argv[1], "a", encoding="utf-8") as target:
    target.write(json.dumps(record) + "\n")
PY

if [[ "$method" == POST ]]; then
  case "${FAKE_SCENARIO:-happy}" in
    create_null) response='null'; code=200 ;;
    create_array) response='[]'; code=200 ;;
    create_data_null) response='{"data":null}'; code=200 ;;
    create_missing_id) response='{"data":{"status":"READY"}}'; code=200 ;;
    create_unauthorized) response='{"error":{"message":"unauthorized"}}'; code=401 ;;
    create_http_5xx) response='{"error":"response unavailable"}'; code=503 ;;
    create_transport_error) exit 56 ;;
    *) response="{\"data\":{\"id\":\"${FAKE_RUN_ID}\",\"status\":\"READY\"}}"; code=201 ;;
  esac
elif [[ "$url" == */v2/actor-runs/* ]]; then
  if [[ -n "${OUTPUT_CAPTURE:-}" ]]; then
    grep -Fq "Run ID: ${FAKE_RUN_ID}" "$OUTPUT_CAPTURE" || { printf 'Run ID was not flushed before polling\n' >&2; exit 91; }
  fi
  case "${FAKE_SCENARIO:-happy}" in
    run_running) response="{\"data\":{\"id\":\"${FAKE_RUN_ID}\",\"status\":\"RUNNING\"}}" ;;
    run_unknown_then_success)
      run_reads="$(grep -c '/v2/actor-runs/' "$CURL_LOG" || true)"
      if [[ "$run_reads" == 1 ]]; then
        response="{\"data\":{\"id\":\"${FAKE_RUN_ID}\",\"status\":\"ABORTING\"}}"
      else
        response="{\"data\":{\"id\":\"${FAKE_RUN_ID}\",\"status\":\"SUCCEEDED\",\"defaultDatasetId\":\"DS_OFFLINE\"}}"
      fi
      ;;
    run_failed) response="{\"data\":{\"id\":\"${FAKE_RUN_ID}\",\"status\":\"FAILED\",\"defaultDatasetId\":\"DS_OFFLINE\"}}" ;;
    missing_dataset) response="{\"data\":{\"id\":\"${FAKE_RUN_ID}\",\"status\":\"SUCCEEDED\"}}" ;;
    run_malformed) response='{"status":"SUCCEEDED"}' ;;
    *) response="{\"data\":{\"id\":\"${FAKE_RUN_ID}\",\"status\":\"SUCCEEDED\",\"defaultDatasetId\":\"DS_OFFLINE\"}}" ;;
  esac
  code=200
elif [[ "$url" == */v2/datasets/*/items ]]; then
  code=200
  case "${FAKE_SCENARIO:-happy}" in
    dataset_http_error) response='{"error":"dataset unavailable"}'; code=503 ;;
    dataset_non_array) response='{"data":[]}'; code=200 ;;
    dataset_empty) response='[]' ;;
    dataset_text_missing) response='[{"segments":[]}]' ;;
    dataset_errmsg) response='[{"text":"","errMsg":"transcript unavailable"}]' ;;
    dataset_has_token) response="[{\"text\":\"transcript contains ${FAKE_ECHO_TOKEN}\",\"segments\":[{\"start\":0,\"end\":1,\"text\":\"sample\"}]}]" ;;
    *) response='[{"text":"offline transcript","segments":[{"start":0,"end":1,"text":"sample"}]}]' ;;
  esac
else
  printf 'unexpected fake URL: %s\n' "$url" >&2
  exit 92
fi

printf '%s' "$response" >"$output"
if [[ "$write_out" == '%{http_code}' ]]; then printf '%s' "$code"; fi
FAKE_CURL
chmod +x "${TMP_DIR}/bin/curl"

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
assert_count() {
  local expected="$1" log="$2" actual=0
  [[ -f "$log" ]] && actual="$(wc -l <"$log" | tr -d ' ')"
  [[ "$actual" == "$expected" ]] || fail "expected $expected fake requests, got $actual"
  if [[ -f "$log" ]]; then
    python3 - "$log" <<'PY'
import json,os,sys
for line in open(sys.argv[1],encoding="utf-8"):
    row=json.loads(line)
    assert row["config_file"] and not os.path.exists(row["config_file"]), "temporary curl auth config was not removed"
PY
  fi
}
assert_no_token() {
  local token="$1" file="$2"
  if grep -Fq "$token" "$file"; then fail "test token leaked to $file"; fi
}
assert_records() {
  local log="$1" mode="$2" video_url="${3:-}"
  python3 - "$log" "$mode" "$video_url" "$TOKEN" "$FAKE_RUN_ID" <<'PY'
import json
import sys

log, mode, video, token, run_id = sys.argv[1:]
with open(log, encoding="utf-8") as source:
    rows = [json.loads(line) for line in source]
api = "https://api.apify.com"
actor_path = "/v2/actors/apple_yang~tiktok-transcripts-scraper/runs"
assert all(row["authorization"] == "Authorization: Bearer " + token for row in rows)
assert all(token not in row["url"] for row in rows)
assert all(token not in row["args"] for row in rows), "token leaked into curl argv"
assert all(row["config_mode"] == "0o600" for row in rows), "curl auth config was not mode 0600"
assert all(not any(arg == "-L" or arg == "--location" or arg.startswith("--retry") for arg in row["args"].split()) for row in rows)
if mode == "run":
    assert [row["method"] for row in rows] == ["POST", "GET", "GET"]
    assert rows[0]["url"] == api + actor_path
    assert json.loads(rows[0]["body"]) == {"videoUrl": video}
    assert rows[1]["url"] == api + "/v2/actor-runs/" + run_id
    assert rows[2]["url"] == api + "/v2/datasets/DS_OFFLINE/items"
elif mode == "start":
    assert len(rows) == 1 and rows[0]["method"] == "POST"
    assert rows[0]["url"] == api + actor_path
    assert json.loads(rows[0]["body"]) == {"videoUrl": video}
elif mode == "wait":
    assert [row["method"] for row in rows] == ["GET", "GET"]
    assert rows[0]["url"] == api + "/v2/actor-runs/" + run_id
    assert rows[1]["url"] == api + "/v2/datasets/DS_OFFLINE/items"
PY
}

TOKEN="offline-token-0123456789"
FAKE_RUN_ID="RUN_OFFLINE_01"
VIDEO="https://www.tiktok.com/@user/video/1234567890"

# Full create, flush, poll, Dataset read: old environment overrides are ignored.
log="${TMP_DIR}/happy.jsonl"; out="${TMP_DIR}/happy.stdout"; err="${TMP_DIR}/happy.stderr"
output_path="${TMP_DIR}/curl-transcript-${FAKE_RUN_ID}.json"
if ! PATH="${TMP_DIR}/bin:$PATH" APIFY_TOKEN="$TOKEN" APIFY_ACTOR_ID='S9A11NvceWaGorwwh' \
  TIKTOK_VIDEO_URL='not-a-tiktok-url' CURL_LOG="$log" FAKE_RUN_ID="$FAKE_RUN_ID" OUTPUT_CAPTURE="$out" \
  bash "$SCRIPT" run --video-url "$VIDEO" --max-wait 5 --output "$output_path" >"$out" 2>"$err"; then
  cat "$out" "$err" >&2; fail "happy run failed"
fi
assert_count 3 "$log"
assert_records "$log" run "$VIDEO"
grep -Fq "Run ID: ${FAKE_RUN_ID}" "$out" || fail "Run ID missing from output"
grep -Fq 'Transcript:' "$out" || fail "transcript missing from output"
grep -Fq 'segments' "$output_path" || fail "complete Dataset JSON missing segments"
grep -Fq "Complete Dataset Items JSON saved: ${output_path}" "$out" || fail "stdout did not report the actual output path"
assert_no_token "$TOKEN" "$out"; assert_no_token "$TOKEN" "$err"; assert_no_token "$TOKEN" "$output_path"
[[ -z "$(find "$TMP_DIR" -name '.tiktok-transcript-output-probe.*' -print -quit)" ]] || fail "successful output preflight left a probe file"

# A non-directory output parent fails before curl is invoked; both probe and script temp files are cleaned.
blocker="${TMP_DIR}/output-parent-is-file"; printf 'preserve me' >"$blocker"
curl_tmpdir="${TMP_DIR}/curl-temp"; mkdir -p "$curl_tmpdir"
log="${TMP_DIR}/preflight-failure.jsonl"; out="${TMP_DIR}/preflight-failure.stdout"; err="${TMP_DIR}/preflight-failure.stderr"
if PATH="${TMP_DIR}/bin:$PATH" TMPDIR="$curl_tmpdir" APIFY_TOKEN="$TOKEN" CURL_LOG="$log" \
  bash "$SCRIPT" run --video-url "$VIDEO" --output "${blocker}/result.json" >"$out" 2>"$err"; then
  fail "output path conflict unexpectedly succeeded"
fi
[[ ! -f "$log" ]] || assert_count 0 "$log"
grep -Fq 'Output directory preflight failed' "$err" || fail "output preflight error was unclear"
[[ "$(cat "$blocker")" == 'preserve me' ]] || fail "preflight modified the blocking file"
[[ -z "$(find "$TMP_DIR" -name '.tiktok-transcript-output-probe.*' -print -quit)" ]] || fail "failed output preflight left a probe file"
[[ -z "$(find "$curl_tmpdir" -mindepth 1 -print -quit)" ]] || fail "failed output preflight left the curl temporary directory or config"
assert_no_token "$TOKEN" "$out"; assert_no_token "$TOKEN" "$err"

# start creates exactly one Run and does not poll.
log="${TMP_DIR}/start.jsonl"; out="${TMP_DIR}/start.stdout"
PATH="${TMP_DIR}/bin:$PATH" APIFY_TOKEN="$TOKEN" CURL_LOG="$log" FAKE_RUN_ID="$FAKE_RUN_ID" \
  bash "$SCRIPT" start --video-url "$VIDEO" >"$out"
assert_count 1 "$log"; assert_records "$log" start "$VIDEO"
grep -Fq "bash ${SCRIPT} wait --run-id ${FAKE_RUN_ID} --max-wait 900" "$out" || fail "start did not print a copyable wait command"

# No URL argument uses the fixed default; legacy environment values cannot override it.
log="${TMP_DIR}/default-url.jsonl"; out="${TMP_DIR}/default-url.stdout"
PATH="${TMP_DIR}/bin:$PATH" APIFY_TOKEN="$TOKEN" APIFY_ACTOR_ID='instagram-actor' \
  TIKTOK_VIDEO_URL='https://example.com/not-a-video' CURL_LOG="$log" FAKE_RUN_ID="$FAKE_RUN_ID" \
  bash "$SCRIPT" start >"$out"
assert_count 1 "$log"
assert_records "$log" start 'https://www.tiktok.com/@carter.braydon/video/7647694374876319007'

# Keep the existing positional URL form while also supporting --video-url.
log="${TMP_DIR}/positional-url.jsonl"; out="${TMP_DIR}/positional-url.stdout"
PATH="${TMP_DIR}/bin:$PATH" APIFY_TOKEN="$TOKEN" CURL_LOG="$log" FAKE_RUN_ID="$FAKE_RUN_ID" \
  bash "$SCRIPT" start "$VIDEO" >"$out"
assert_count 1 "$log"; assert_records "$log" start "$VIDEO"

# wait reads the supplied Run only and makes no creation request.
log="${TMP_DIR}/wait.jsonl"; out="${TMP_DIR}/wait.stdout"
PATH="${TMP_DIR}/bin:$PATH" APIFY_TOKEN="$TOKEN" CURL_LOG="$log" FAKE_RUN_ID="$FAKE_RUN_ID" \
  bash "$SCRIPT" wait --run-id "$FAKE_RUN_ID" --max-wait 1 --output "${TMP_DIR}/wait-items.json" >"$out"
assert_count 2 "$log"; assert_records "$log" wait

# Non-object create responses are unknown; 5xx and transport errors are also unknown.
for scenario in create_null create_array create_data_null create_missing_id create_http_5xx create_transport_error; do
  log="${TMP_DIR}/${scenario}.jsonl"; out="${TMP_DIR}/${scenario}.stdout"; err="${TMP_DIR}/${scenario}.stderr"
  if PATH="${TMP_DIR}/bin:$PATH" APIFY_TOKEN="$TOKEN" CURL_LOG="$log" FAKE_SCENARIO="$scenario" FAKE_RUN_ID="$FAKE_RUN_ID" \
    bash "$SCRIPT" start --video-url "$VIDEO" >"$out" 2>"$err"; then fail "$scenario unexpectedly succeeded"; fi
  assert_count 1 "$log"
  grep -Fq 'outcome is unknown' "$err" || fail "$scenario did not explain unknown outcome"
  grep -Fq 'Check the Apify Console' "$err" || fail "$scenario omitted Console guidance"
  grep -Fq 'do not' "$err" || fail "$scenario omitted no-retry guidance"
  assert_no_token "$TOKEN" "$out"; assert_no_token "$TOKEN" "$err"
done

# A complete JSON 401 response is a definite rejection, still with only one POST.
log="${TMP_DIR}/unauthorized.jsonl"; out="${TMP_DIR}/unauthorized.stdout"; err="${TMP_DIR}/unauthorized.stderr"
if PATH="${TMP_DIR}/bin:$PATH" APIFY_TOKEN="$TOKEN" CURL_LOG="$log" FAKE_SCENARIO=create_unauthorized FAKE_RUN_ID="$FAKE_RUN_ID" \
  bash "$SCRIPT" start --video-url "$VIDEO" >"$out" 2>"$err"; then fail "401 creation response unexpectedly succeeded"; fi
assert_count 1 "$log"
grep -Fq 'rejected by Apify with HTTP 401' "$err" || fail "401 was not classified as a request rejection"
grep -Fq 'Run was not created' "$err" || fail "401 rejection omitted its outcome"
if grep -Fq 'outcome is unknown' "$err"; then fail "401 was incorrectly classified as unknown"; fi
assert_no_token "$TOKEN" "$out"; assert_no_token "$TOKEN" "$err"
# Missing credentials fail before the fake transport is invoked.
log="${TMP_DIR}/missing-token.jsonl"; out="${TMP_DIR}/missing-token.stdout"; err="${TMP_DIR}/missing-token.stderr"
if (unset APIFY_TOKEN; PATH="${TMP_DIR}/bin:$PATH" CURL_LOG="$log" bash "$SCRIPT" start --video-url "$VIDEO" >"$out" 2>"$err"); then
  fail "missing APIFY_TOKEN unexpectedly succeeded"
fi
[[ ! -f "$log" ]] || assert_count 0 "$log"
grep -Fq 'APIFY_TOKEN is required' "$err" || fail "missing-token error was unclear"

# Duplicated commands and start-only unsupported options fail before any request.
for args in 'run run' 'start start' 'start --max-wait 10' 'start --output ignored.json'; do
  log="${TMP_DIR}/invalid-cli.jsonl"; err="${TMP_DIR}/invalid-cli.stderr"
  if PATH="${TMP_DIR}/bin:$PATH" APIFY_TOKEN="$TOKEN" CURL_LOG="$log" \
    bash "$SCRIPT" $args --video-url "$VIDEO" >/dev/null 2>"$err"; then fail "invalid CLI form was accepted: $args"; fi
  [[ ! -f "$log" ]] || assert_count 0 "$log"
  grep -Eq 'exactly one command|not valid with start' "$err" || fail "invalid CLI form lacked a clear error"
done

# Nonterminal states, including an unfamiliar nonempty state, keep polling the same Run.
log="${TMP_DIR}/unknown-status.jsonl"; out="${TMP_DIR}/unknown-status.stdout"
PATH="${TMP_DIR}/bin:$PATH" APIFY_TOKEN="$TOKEN" CURL_LOG="$log" FAKE_SCENARIO=run_unknown_then_success \
  FAKE_RUN_ID="$FAKE_RUN_ID" bash "$SCRIPT" run --video-url "$VIDEO" --max-wait 5 \
  --output "${TMP_DIR}/unknown-status.json" >"$out"
assert_count 4 "$log"
python3 - "$log" "$FAKE_RUN_ID" <<'PY'
import json,sys
rows=[json.loads(line) for line in open(sys.argv[1],encoding="utf-8")]
assert [row["method"] for row in rows] == ["POST","GET","GET","GET"]
assert all(row["url"].endswith("/v2/actor-runs/"+sys.argv[2]) for row in rows[1:3])
assert rows[3]["url"].endswith("/v2/datasets/DS_OFFLINE/items")
PY

# URL and wait-bound validation happen before any request.
for bad_url in '' 'http://www.tiktok.com/@user/video/1' 'https://example.com/@user/video/1' 'https://www.tiktok.com/@user/clip/1'; do
  log="${TMP_DIR}/invalid-url.jsonl"
  if PATH="${TMP_DIR}/bin:$PATH" APIFY_TOKEN="$TOKEN" CURL_LOG="$log" bash "$SCRIPT" start --video-url "$bad_url" >/dev/null 2>&1; then
    fail "invalid URL was accepted"
  fi
  [[ ! -f "$log" ]] || assert_count 0 "$log"
done
for bad_wait in 0 86401 1.5 999999999999999999999999999999; do
  log="${TMP_DIR}/invalid-wait.jsonl"
  if PATH="${TMP_DIR}/bin:$PATH" APIFY_TOKEN="$TOKEN" CURL_LOG="$log" \
    bash "$SCRIPT" wait --run-id "$FAKE_RUN_ID" --max-wait "$bad_wait" >/dev/null 2>&1; then
    fail "invalid max wait was accepted: $bad_wait"
  fi
  [[ ! -f "$log" ]] || assert_count 0 "$log"
done
# Both documented wait bounds are accepted without waiting when the fake Run is already terminal.
for good_wait in 1 86400; do
  log="${TMP_DIR}/valid-wait-${good_wait}.jsonl"
  PATH="${TMP_DIR}/bin:$PATH" APIFY_TOKEN="$TOKEN" CURL_LOG="$log" FAKE_RUN_ID="$FAKE_RUN_ID" \
    bash "$SCRIPT" wait --run-id "$FAKE_RUN_ID" --max-wait "$good_wait" --output "${TMP_DIR}/bounds-${good_wait}.json" >/dev/null
  assert_count 2 "$log"
done

# A timeout is attached to the same existing ID and never creates another Run.
log="${TMP_DIR}/timeout.jsonl"; out="${TMP_DIR}/timeout.stdout"; err="${TMP_DIR}/timeout.stderr"
if PATH="${TMP_DIR}/bin:$PATH" APIFY_TOKEN="$TOKEN" CURL_LOG="$log" FAKE_SCENARIO=run_running FAKE_RUN_ID="$FAKE_RUN_ID" \
  bash "$SCRIPT" wait --run-id "$FAKE_RUN_ID" --max-wait 1 >"$out" 2>"$err"; then fail "running Run did not time out"; fi
assert_count 1 "$log"
python3 - "$log" "$FAKE_RUN_ID" <<'PY'
import json,sys
row=json.loads(open(sys.argv[1],encoding="utf-8").readline())
assert row["method"] == "GET" and row["url"].endswith("/v2/actor-runs/"+sys.argv[2])
PY
grep -Fq 'may still be running' "$err" || fail "timeout did not explain that Run may continue"
grep -Fq "same Run ID" "$err" || fail "timeout omitted same-ID guidance"
grep -Fq "bash ${SCRIPT} wait --run-id ${FAKE_RUN_ID} --max-wait 1" "$err" || fail "timeout omitted the complete same-ID wait command"

# Run terminal failure and Dataset/transcript failures keep distinct diagnostics.
for scenario in run_failed run_malformed missing_dataset dataset_http_error dataset_non_array dataset_empty dataset_text_missing dataset_errmsg; do
  log="${TMP_DIR}/${scenario}.jsonl"; out="${TMP_DIR}/${scenario}.stdout"; err="${TMP_DIR}/${scenario}.stderr"
  output_path="${TMP_DIR}/curl-transcript-${FAKE_RUN_ID}-${scenario}.json"
  if PATH="${TMP_DIR}/bin:$PATH" APIFY_TOKEN="$TOKEN" CURL_LOG="$log" FAKE_SCENARIO="$scenario" FAKE_RUN_ID="$FAKE_RUN_ID" \
    bash "$SCRIPT" run --video-url "$VIDEO" --max-wait 3 --output "$output_path" >"$out" 2>"$err"; then
    fail "$scenario unexpectedly succeeded"
  fi
  case "$scenario" in
    run_failed) grep -Fq 'status FAILED' "$err" || fail "Run failure was not identified" ;;
    run_malformed) grep -Fq 'Invalid Apify Run response' "$err" || fail "malformed Run response was not identified" ;;
    missing_dataset) grep -Fq 'no default Dataset ID' "$err" || fail "missing Dataset ID was not identified" ;;
    dataset_http_error) grep -Fq 'Dataset DS_OFFLINE could not be read' "$err" || fail "Dataset HTTP error was not identified" ;;
    dataset_non_array) grep -Fq 'Dataset response was not a JSON array' "$err" || fail "non-array Dataset response was not identified" ;;
    dataset_empty) grep -Fq 'Dataset is empty' "$err" || fail "empty Dataset was not identified" ;;
    dataset_text_missing) grep -Fq 'transcript text is empty or missing' "$err" || fail "missing text was not identified" ;;
    dataset_errmsg) grep -Fq 'Actor returned errMsg' "$err" || fail "errMsg was not identified" ;;
  esac
  assert_no_token "$TOKEN" "$err"
  assert_no_token "$TOKEN" "$out"
  if [[ "$scenario" == dataset_empty || "$scenario" == dataset_text_missing || "$scenario" == dataset_errmsg ]]; then
    [[ -f "$output_path" ]] || fail "$scenario did not preserve its Dataset diagnostic JSON"
    grep -Fq "Dataset Items saved for diagnosis: ${output_path}" "$out" || fail "$scenario did not label the file as diagnostic output"
    if grep -Fq 'Complete Dataset Items JSON saved' "$out"; then fail "$scenario was incorrectly reported as a successful result"; fi
    assert_no_token "$TOKEN" "$output_path"
  else
    [[ ! -e "$output_path" ]] || fail "$scenario wrote a Dataset result without a valid successful Dataset read"
  fi
done

# Token echoed inside an API transcript is redacted in both stdout and result JSON.
log="${TMP_DIR}/redaction.jsonl"; out="${TMP_DIR}/redaction.stdout"; err="${TMP_DIR}/redaction.stderr"
PATH="${TMP_DIR}/bin:$PATH" APIFY_TOKEN="$TOKEN" FAKE_ECHO_TOKEN="$TOKEN" CURL_LOG="$log" FAKE_SCENARIO=dataset_has_token FAKE_RUN_ID="$FAKE_RUN_ID" \
  bash "$SCRIPT" run --video-url "$VIDEO" --output "${TMP_DIR}/redacted.json" >"$out" 2>"$err"
assert_no_token "$TOKEN" "$out"; assert_no_token "$TOKEN" "$err"; assert_no_token "$TOKEN" "${TMP_DIR}/redacted.json"
grep -Fq '[REDACTED]' "$out" || fail "response token was not redacted from transcript"

printf 'PASS: 39 offline CLI scenarios (fake-curl transport)\n'
