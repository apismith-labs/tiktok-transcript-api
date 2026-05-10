# Use TikTok Transcript API with cURL

This example uses Apify's synchronous dataset-items endpoint to validate one
TikTok video URL quickly.

## Setup

Requirements:

- `curl`
- `bash`
- `python3` for the response summary printed after the request

From the repository root:

```bash
cp .env.example .env
```

Edit `.env` and set your Apify token:

```bash
APIFY_TOKEN=your_apify_token_here
APIFY_ACTOR_ID=apple_yang/tiktok-transcripts-scraper
TIKTOK_VIDEO_URL=https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392
```

## Run

```bash
bash examples/curl/single-url-sync.sh
```

You can also pass a URL directly:

```bash
bash examples/curl/single-url-sync.sh "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
```

The full response is saved to:

```text
sample-output/generated/curl-single-url-response.json
```
