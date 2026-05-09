# Use TikTok Transcript API with Rust

This example calls the Apify Actor `apple_yang/tiktok-transcripts-scraper`
with `tokio`, `reqwest`, `serde`, and `dotenvy`.

## Requirements

- Rust 1.75 or newer
- Rust 2021 edition

## Setup

From this directory:

```bash
cargo build
```

From the repository root:

```bash
cp .env.example .env
```

Set `APIFY_TOKEN` in `.env` or your shell environment.

## Run

```bash
cargo run --manifest-path examples/rust/Cargo.toml --bin single_url
```

You can also pass a URL directly:

```bash
cargo run --manifest-path examples/rust/Cargo.toml --bin single_url -- "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
```

The full response is saved to:

```text
sample-output/generated/rust-single-url-response.json
```
