# Use TikTok Transcript API with Node.js

This example calls the Apify Actor `apple_yang/tiktok-transcripts-scraper`
with the official Apify JavaScript API client.

## Setup

From this directory:

```bash
npm install
```

From the repository root:

```bash
cp .env.example .env
```

Set `APIFY_TOKEN` in `.env` or your shell environment.

## Run

```bash
node examples/nodejs/single-url.mjs
```

You can also pass a URL directly:

```bash
node examples/nodejs/single-url.mjs "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
```

The full response is saved to:

```text
sample-output/generated/nodejs-single-url-response.json
```
