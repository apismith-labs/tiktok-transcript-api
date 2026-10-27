# Go example

Requires Go 1.22+. The example uses the Go standard library and reads
`APIFY_TOKEN` from the process environment; it does not load `.env`. The Actor
ID is fixed in code.

From the repository root, export `APIFY_TOKEN`, then use:

```bash
cd examples/go
go run .
go run . --video-url 'https://www.tiktok.com/@user/video/1234567890'
go run . start
go run . wait --run-id RUN_ID --max-wait 900
go run . batch --csv ../../sample-data/tiktok-video-urls.csv --journal ../../sample-output/generated/go-csv-batch-results.jsonl --concurrency 2 --max-wait 900
go run . batch --csv ../../sample-data/tiktok-video-urls.csv --journal ../../sample-output/generated/go-csv-batch-results.jsonl --reconcile
```

The default video URL is
`https://www.tiktok.com/@carter.braydon/video/7647694374876319007`. Run
creation sends one client-side POST attempt, not an exactly-once guarantee. If
the result is unknown, check Apify Console before retrying; after a wait timeout
continue with the same Run ID.

Offline checks are listed in [QuickStart](../../docs/quick-start.md).
