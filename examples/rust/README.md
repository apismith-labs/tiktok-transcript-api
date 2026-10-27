# Rust example

Uses Rust 2021 and the dependencies pinned by `Cargo.lock` (lockfile format
4). Cargo 1.78 or newer is needed to read lockfile version 4. The example reads
`APIFY_TOKEN` from the process environment and does not load `.env`. The Actor
ID is fixed in code.

From the repository root, export `APIFY_TOKEN`, then use:

```bash
cargo run --manifest-path examples/rust/Cargo.toml --bin single_url
cargo run --manifest-path examples/rust/Cargo.toml --bin single_url -- --video-url 'https://www.tiktok.com/@user/video/1234567890'
cargo run --manifest-path examples/rust/Cargo.toml --bin async_run -- start
cargo run --manifest-path examples/rust/Cargo.toml --bin async_run -- wait --run-id RUN_ID --max-wait 900
cargo run --manifest-path examples/rust/Cargo.toml --bin csv_batch -- --csv sample-data/tiktok-video-urls.csv --journal sample-output/generated/rust-csv-batch.jsonl --concurrency 2 --max-wait 900
cargo run --manifest-path examples/rust/Cargo.toml --bin csv_batch -- --csv sample-data/tiktok-video-urls.csv --journal sample-output/generated/rust-csv-batch.jsonl --reconcile
```

The default video URL is
`https://www.tiktok.com/@carter.braydon/video/7647694374876319007`. The first
build may need to fetch crates; use `--offline --locked` after dependencies are
cached. Run creation is one client-side POST attempt, not an exactly-once
guarantee. Check Apify Console if its result is unknown, and reuse the same Run
ID after a wait timeout.
