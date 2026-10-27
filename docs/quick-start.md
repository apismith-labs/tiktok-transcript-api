# QuickStart

This repository contains integration examples for the fixed Apify Actor
[`apple_yang/tiktok-transcripts-scraper`](https://apify.com/apple_yang/tiktok-transcripts-scraper).
You can also open the [Actor in Apify Console](https://apify.com/apple_yang/tiktok-transcripts-scraper)
to try it without this repository.

Each Actor Run accepts one `videoUrl` string. The examples use this tested
default video unless a CLI URL override is provided:

```text
https://www.tiktok.com/@carter.braydon/video/7647694374876319007
```

## 1. Configure the token

The only credential needed by the examples is `APIFY_TOKEN`. To prepare the
root `.env` file used by Python, Node.js, and Java:

```bash
cp .env.example .env
```

Edit `.env` and replace the placeholder with your token. Keep the file local;
`.gitignore` excludes it. Alternatively, set the variable in your shell:

```bash
export APIFY_TOKEN='your_apify_token_here'
```

Token loading differs by language: Python, Node.js, and Java load the
repository-root `.env`; cURL, Go, and Rust read the process environment only.
The cURL/Go/Rust commands below therefore require the `export` form or an
already-exported variable. No example reads `APIFY_ACTOR_ID` or
`TIKTOK_VIDEO_URL`.

## 2. Run one video

Commands are shown from the repository root unless a `cd` is included.

### cURL

Requirements: Bash, curl, and Python 3 standard library. The script does not
read `.env`.

```bash
export APIFY_TOKEN='your_apify_token_here'
bash examples/curl/single-url-sync.sh run
```

Replace the URL with `--video-url URL`. The script prints the Run ID before
waiting and saves complete Dataset Items to
`sample-output/generated/curl-transcript-<run-id>.json`.

### Python

Requirements: Python 3.11 or newer. Install the locked Apify client in a
virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r examples/python/requirements.txt
cp .env.example .env
```

After setting `APIFY_TOKEN` in the root `.env`:

```bash
python3 examples/python/single_url.py
python3 examples/python/single_url.py --video-url 'https://www.tiktok.com/@user/video/1234567890'
python3 examples/python/single_url.py --max-wait 900
```

The single-video output is `sample-output/generated/python-single-url-response.json`.
Python single-video waiting defaults to 900 seconds; `--max-wait` accepts
1–86400 seconds. On timeout, continue with the same Run ID using the async
`wait` command below.

### Node.js

Requirements: Node.js 20.12 or newer. The examples use Node built-ins and have
no package dependencies, so `npm install` is not required. From the repository
root, set `APIFY_TOKEN` in `.env`, then run:

```bash
node examples/nodejs/single-url.mjs
node examples/nodejs/single-url.mjs --video-url 'https://www.tiktok.com/@user/video/1234567890'
node examples/nodejs/single-url.mjs --max-wait 1200
```

Output: `sample-output/generated/nodejs-single-url-response.json`.
Node.js single-video waiting defaults to 900 seconds. `--max-wait SECONDS`
accepts values from 1 to 86400; use the same option on the single-video
command or `async-run.mjs wait` to set the limit.

### Java

Requirements: JDK 17 and Maven. Java loads the root `.env` (the process
environment takes precedence). From the repository root:

```bash
cp .env.example .env
mvn -f examples/java/pom.xml -Dexec.mainClass=com.apismith.tiktok.SingleUrl compile exec:java
```

Maven resolves dependencies and plugins on the first build. That first
invocation needs access to the configured Maven repositories unless the
required artifacts are already cached. The first use of `exec-maven-plugin`
for the run command may also download that plugin.

To run the Java offline tests on an initial setup, use normal dependency
resolution:

```bash
mvn -f examples/java/pom.xml test
```

To override the URL:

```bash
mvn -f examples/java/pom.xml -Dexec.mainClass=com.apismith.tiktok.SingleUrl -Dexec.args="--video-url https://www.tiktok.com/@user/video/1234567890" compile exec:java
```

Output: `sample-output/generated/java-single-url-response.json`.

### Go

Requirements: Go 1.22 or newer. Go reads `APIFY_TOKEN` from the process
environment, not `.env`. From the repository root:

```bash
export APIFY_TOKEN='your_apify_token_here'
cd examples/go
go run .
```

Override the URL with `go run . --video-url 'https://www.tiktok.com/@user/video/1234567890'`.
The full Dataset Items are saved as `sample-output/generated/go-single-url-response.json`.

### Rust

Requirements: Rust 2021 and Cargo with lockfile-v4 support (Cargo 1.78 or newer).
`Cargo.toml` does not declare a separate `rust-version`; use a current stable
toolchain. Rust reads `APIFY_TOKEN` from the process environment, not `.env`.
The first build needs access to download the locked crates if they are not
already cached:

```bash
export APIFY_TOKEN='your_apify_token_here'
cargo build --manifest-path examples/rust/Cargo.toml
cargo run --manifest-path examples/rust/Cargo.toml --bin single_url
```

After dependencies are cached, `cargo run --offline --manifest-path examples/rust/Cargo.toml --bin single_url` avoids registry access. Add
`-- --video-url 'https://www.tiktok.com/@user/video/1234567890'` to override
the URL. Output: `sample-output/generated/rust-single-url-response.json`.

## 3. Start now and wait later

Starting a Run and waiting for it are separate operations. Copy the printed Run
ID into the corresponding `wait` command. If waiting times out, retry only the
read using that same ID; do not create another Run because a wait timed out.

| Language | Start | Wait for the same Run |
| --- | --- | --- |
| cURL | `bash examples/curl/single-url-sync.sh start` | `bash examples/curl/single-url-sync.sh wait --run-id RUN_ID` |
| Python | `python3 examples/python/async_run.py start` | `python3 examples/python/async_run.py wait --run-id RUN_ID --max-wait 900` |
| Node.js | `node examples/nodejs/async-run.mjs start` | `node examples/nodejs/async-run.mjs wait --run-id RUN_ID --max-wait 900` |
| Java | `mvn -f examples/java/pom.xml -Dexec.mainClass=com.apismith.tiktok.AsyncRun -Dexec.args="start" compile exec:java` | `mvn -f examples/java/pom.xml -Dexec.mainClass=com.apismith.tiktok.AsyncRun -Dexec.args="wait --run-id RUN_ID --max-wait 900" compile exec:java` |
| Go | From `examples/go`: `go run . start` | From `examples/go`: `go run . wait --run-id RUN_ID --max-wait 900` |
| Rust | `cargo run --manifest-path examples/rust/Cargo.toml --bin async_run -- start` | `cargo run --manifest-path examples/rust/Cargo.toml --bin async_run -- wait --run-id RUN_ID --max-wait 900` |

The default wait limit is 900 seconds, including Node.js. cURL, Node.js, Java,
Go, and Rust validate `--max-wait` from 1 to 86400 seconds. Python
single-video uses the same range; Python async and CSV commands require a
finite positive value.

Run creation makes one client-side POST attempt; this does not guarantee
server-side exactly-once creation. If the create response is incomplete or its
outcome is uncertain, check Apify Console before retrying or starting another
Run.

## 4. Process CSV rows

The CSV uses a `videoUrl` column, one URL per row, and may include a unique `id`
column. Each client starts a separate Actor Run for each valid row; no Actor
accepts a URL array. Batch concurrency defaults to 2. Python, Node.js, Go, and
Rust allow 1–16 workers; Java allows 1–8.

```bash
# From the repository root
python3 examples/python/csv_batch.py sample-data/tiktok-video-urls.csv --concurrency 2
(cd examples/nodejs && npm run batch -- ../../sample-data/tiktok-video-urls.csv --concurrency 2)
(cd examples/go && go run . batch --csv ../../sample-data/tiktok-video-urls.csv --concurrency 2)
cargo run --manifest-path examples/rust/Cargo.toml --bin csv_batch -- --csv sample-data/tiktok-video-urls.csv --concurrency 2
```

Java uses `--csv` and supports an explicit journal path:

```bash
mvn -f examples/java/pom.xml -Dexec.mainClass=com.apismith.tiktok.CsvBatch -Dexec.args="--csv sample-data/tiktok-video-urls.csv --journal sample-output/generated/java-csv-batch-results.jsonl --concurrency 2" compile exec:java
```

Python and Node.js have a journal-only read-only reconcile command:

```bash
python3 examples/python/csv_batch.py --reconcile
cd examples/nodejs && npm run batch -- --reconcile
```

Java, Go, and Rust reconcile against the current CSV plus its journal. See
[Batch processing](batch-processing.md) for the matching commands and journal
paths. `needs_reconciliation` means the program will stop rather than guess
whether an earlier Run exists. Check the recorded Run ID and URLs in Apify
Console, then choose a deliberate manual resolution; the reconcile command is
read-only.

## Outputs and result interpretation

Successful runs must pass through a Run terminal status, a default Dataset ID,
and Dataset item reads. A `SUCCEEDED` Run can still have an empty Dataset, no
usable `text`, or a non-empty `errMsg`. The examples report these separately
and return a failure status when there is no usable transcript.

There is no committed live Dataset fixture in `sample-output/`. Generated files
are ignored by Git. To inspect a generated array without assuming a fixed text
value, for example:

```bash
python3 - <<'PY'
import json
from pathlib import Path

path = Path("sample-output/generated/python-single-url-response.json")
items = json.loads(path.read_text(encoding="utf-8"))
print(json.dumps(items[0] if items else [], ensure_ascii=False, indent=2))
PY
```

## Offline validation

These commands use mocks/fake transports and do not require `APIFY_TOKEN` or
start an Actor Run:

```bash
python3 scripts/validate_python_examples.py
npm --prefix examples/nodejs test
mvn -o -f examples/java/pom.xml test
(cd examples/go && go test -count=1 ./... && go test -race -count=1 ./... && go vet ./... && gofmt -l .)
cargo test --offline --locked --manifest-path examples/rust/Cargo.toml
cargo fmt --manifest-path examples/rust/Cargo.toml --check
cargo clippy --offline --locked --manifest-path examples/rust/Cargo.toml --all-targets -- -D warnings
cargo build --offline --locked --manifest-path examples/rust/Cargo.toml --bins
bash -n examples/curl/single-url-sync.sh
bash -n examples/curl/tests/test_offline.sh
bash examples/curl/tests/test_offline.sh
```

The Maven command in this offline validation list is optional and works only
after Maven dependencies and plugins are cached. For the first Rust build, use
the `cargo build` command above if you want Cargo to fetch dependencies; later
you can use `--offline --locked`.
