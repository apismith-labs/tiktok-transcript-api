# Troubleshooting

## `APIFY_TOKEN` is missing

Python, Node.js, and Java load `.env` from the repository root. Create it from
the template and set only the token:

```bash
cp .env.example .env
```

cURL, Go, and Rust do not load `.env`; export the token in the process that
launches the example:

```bash
export APIFY_TOKEN='your_apify_token_here'
```

Do not print the token for diagnosis or put it in a URL, source file, output,
or log. The Actor ID is fixed in the examples; `APIFY_ACTOR_ID` is not a
supported setting.

## Invalid token or authorization failure

Check that the shell variable or root `.env` contains the intended token and
that it has not been revoked. Python's `load_dotenv` does not override an
already-set shell variable; Node.js preserves existing process environment
values when loading the root `.env`; Java checks the process environment
before falling back to `.env`.

The cURL example reports a complete JSON 4xx create response as rejected. If a
create request ends in a transport error, malformed response, or 5xx response,
its outcome remains unknown.

## Run creation result is unknown

A client sends a Run creation POST once, but one client send is not a
server-side exactly-once guarantee. If the response is incomplete or cannot
confirm a Run ID:

1. Check Apify Console for a Run matching the time and video URL.
2. Do not directly retry the create command or start another Run before that
   check.
3. If the Run exists, keep its Run ID and use the language's `wait` command.

CSV journals record `start_attempted` and unresolved creation states so a
rerun does not silently submit a second POST.

## Waiting timed out

A wait timeout does not mean the Run failed or was not created. Continue with
the same Run ID using the matching command, for example:

```bash
python3 examples/python/async_run.py wait --run-id RUN_ID --max-wait 900
node examples/nodejs/async-run.mjs wait --run-id RUN_ID --max-wait 900
```

For Java, from the repository root, run:

```bash
mvn -f examples/java/pom.xml -Dexec.mainClass=com.apismith.tiktok.AsyncRun -Dexec.args="wait --run-id RUN_ID --max-wait 900" compile exec:java
```

For Go, run `go run . wait --run-id RUN_ID --max-wait 900` from
`examples/go`. For Rust, from the repository root, run:

```bash
cargo run --manifest-path examples/rust/Cargo.toml --bin async_run -- wait --run-id RUN_ID --max-wait 900
```

cURL uses:

```bash
bash examples/curl/single-url-sync.sh wait --run-id RUN_ID --max-wait 900
```

Do not create another Run just because waiting reached its local limit.

## Run failed or cannot be read

The examples distinguish a failed Run status from a Run lookup/network error.
For an existing Run ID, inspect the Run and Actor log in Apify Console. Statuses
`FAILED`, `TIMED-OUT`, and `ABORTED` are terminal failures; an unknown or
nonterminal status is not evidence that the Run failed.

## Run succeeded but transcript is missing

The example must also read the Run's default Dataset and its Items. A
`SUCCEEDED` status does not imply a non-empty Dataset or a usable transcript.
Inspect the reported Dataset error, empty Dataset, `text`, and `errMsg`. Keep
the complete Dataset Items JSON for diagnosis when the example provides an
output file. Transcript availability depends on the specific video.

## CSV batch reports `needs_reconciliation`

The batch program is refusing to guess whether an earlier POST created a Run.
Use the read-only reconcile command and compare the recorded input URL, current
URL, status, error, and any Run ID with Apify Console. Do not edit or discard
the journal before that review. If you decide after review to submit a changed
input as a new job, keep the old journal as an audit trail and start with a new
journal path as supported by that language.

Python and Node.js reconcile their default JSONL journal without a CSV path:

```bash
python3 examples/python/csv_batch.py --reconcile
cd examples/nodejs && npm run batch -- --reconcile
```

Java, Go, and Rust reconciliation uses the current CSV plus its journal. The
exact commands and default journal locations are in
[Batch processing](batch-processing.md).

## CSV validation or empty batch

Check that the header contains `videoUrl`, each non-empty input is a supported
TikTok video URL, and any optional `id` column has unique non-empty values.
Without `id`, stable keys use the URL and its duplicate occurrence order; keep
URLs and duplicate-row ordering stable across resumptions. An empty CSV does
not count as a successful batch.

Concurrency limits vary: Python, Node.js, Go, and Rust allow 1–16; Java allows
1–8. The CSV client starts separate Runs rather than passing an array to the
Actor.

## Output file is missing

Only outputs from completed Dataset reads are written. Check the exact path
printed by the example and confirm the process can create files there. Runtime
files are under `sample-output/generated/`, which Git ignores, except Java CSV
uses the journal path supplied with `--journal` (otherwise it defaults beside
the input CSV).

The repository does not contain a committed live output fixture. To inspect a
generated Dataset, see the command in [API reference](api-reference.md).

## Runtime or dependencies

- Python requires Python 3.11+ and the versions in
  `examples/python/requirements.txt`.
- Node.js requires 20.12+; the example package has no third-party runtime
  dependencies.
- Java requires JDK 17 and Maven.
- Go requires Go 1.22+.
- Rust uses the 2021 edition and Cargo lockfile v4. The first build may need to
  fetch crates; use `--offline` only after they are cached.

Use the language-specific README for setup and validation commands. Offline
tests use fake transports; they do not validate a live Apify Run.
