# Use TikTok Transcript API with Go

This example calls the Apify Actor `apple_yang/tiktok-transcripts-scraper`
with Go's standard HTTP and JSON packages.

## Requirements

- Go 1.22 or newer

## Setup

From the repository root:

```bash
cp .env.example .env
cd examples/go
go mod tidy
```

This may create or update `go.sum`.

Set `APIFY_TOKEN` in `.env` or your shell environment.

## Run

```bash
cd examples/go
go run single_url.go
```

You can also pass a URL directly:

```bash
cd examples/go
go run single_url.go "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
```

The full response is saved to:

```text
sample-output/generated/go-single-url-response.json
```
