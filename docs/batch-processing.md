# CSV batch processing

The Actor accepts one `videoUrl` string per Run. The examples implement batch
processing on the client: each valid CSV row starts a separate Run. They do not
send URL arrays to the Actor.

## Input file

The sample file is [sample-data/tiktok-video-urls.csv](../sample-data/tiktok-video-urls.csv):

```csv
videoUrl
https://www.tiktok.com/@carter.braydon/video/7647694374876319007
```

A CSV may include an optional `id` column with unique, non-empty identifiers.
Without `id`, the examples derive row keys from each URL and its occurrence
number. Keep the URL text and order of duplicate URLs stable when resuming.
Empty URLs, duplicate identifiers, and malformed rows are reported instead of
being submitted.

## Run a batch

All examples default to concurrency 2. Python, Node.js, Go, and Rust support
1–16 workers; Java supports 1–8. From the repository root:

```bash
python3 examples/python/csv_batch.py sample-data/tiktok-video-urls.csv --concurrency 2 --max-wait 900
(cd examples/nodejs && npm run batch -- ../../sample-data/tiktok-video-urls.csv --concurrency 2 --max-wait 900)
(cd examples/go && go run . batch --csv ../../sample-data/tiktok-video-urls.csv --journal ../../sample-output/generated/go-csv-batch-results.jsonl --concurrency 2 --max-wait 900)
cargo run --manifest-path examples/rust/Cargo.toml --bin csv_batch -- --csv sample-data/tiktok-video-urls.csv --journal sample-output/generated/rust-csv-batch.jsonl --concurrency 2 --max-wait 900
mvn -f examples/java/pom.xml -Dexec.mainClass=com.apismith.tiktok.CsvBatch -Dexec.args="--csv sample-data/tiktok-video-urls.csv --journal sample-output/generated/java-csv-batch-results.jsonl --concurrency 2 --max-wait 900" compile exec:java
```

The examples append JSONL progress records so that known Run IDs can be
resumed. Before a Run creation POST, they persist a `start_attempted` record.
An unresolved creation result is not automatically posted again. One client
POST attempt is not a server-side exactly-once guarantee; check Apify Console
when the result is unknown.

## Resume and reconcile

A row with a known Run ID and unchanged URL can resume status and Dataset reads
for that same Run. If a pending row's URL changes, it needs manual
reconciliation; the old Dataset is not attached to the new URL. Completed rows
whose URL changes are handled as new input by the language implementations.

Python and Node.js can list journal entries needing review without a CSV:

```bash
python3 examples/python/csv_batch.py --reconcile
(cd examples/nodejs && npm run batch -- --reconcile)
```

Java, Go, and Rust reconcile against the current CSV and journal:

```bash
mvn -f examples/java/pom.xml -Dexec.mainClass=com.apismith.tiktok.CsvBatch -Dexec.args="--csv sample-data/tiktok-video-urls.csv --journal sample-output/generated/java-csv-batch-results.jsonl --reconcile" compile exec:java
(cd examples/go && go run . batch --csv ../../sample-data/tiktok-video-urls.csv --journal ../../sample-output/generated/go-csv-batch-results.jsonl --reconcile)
cargo run --manifest-path examples/rust/Cargo.toml --bin csv_batch -- --csv sample-data/tiktok-video-urls.csv --journal sample-output/generated/rust-csv-batch.jsonl --reconcile
```

Reconcile is read-only. Inspect the recorded status, original/current URL, and
Run ID in Apify Console before deciding how to proceed. Keep the journal as an
audit trail; use a new journal path for a deliberately separate batch.

## Interpret each row

A Run is not a successful transcript merely because its status is `SUCCEEDED`.
The client must also read the default Dataset and find usable `text` without a
non-empty `errMsg`. Empty Dataset, missing/blank transcript, Actor failure,
Dataset read failure, and unknown Run creation are distinct outcomes. Batch
commands return non-zero when a row fails or needs manual action.

Runtime JSON/JSONL files are written under `sample-output/generated/` and
ignored by Git. Java's default journal is adjacent to the CSV unless `--journal`
is supplied. Never include `APIFY_TOKEN` in a journal or application log.
