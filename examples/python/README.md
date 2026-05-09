# Use TikTok Transcript API with Python

This example calls the Apify Actor `apple_yang/tiktok-transcripts-scraper`
with the official Apify Python API client.

## Setup

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r examples/python/requirements.txt
cp .env.example .env
```

Set `APIFY_TOKEN` in `.env` or your shell environment.

## Run

```bash
python examples/python/single_url.py
```

You can also pass a URL directly:

```bash
python examples/python/single_url.py "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
```

The full response is saved to:

```text
sample-output/generated/python-single-url-response.json
```
