# TikTok Transcript API Quick Start

This repository provides working examples for calling the Apify Actor
`apple_yang/tiktok-transcripts-scraper` and saving TikTok transcript results for
developer workflows.

Use it when you want to validate the Actor locally, inspect raw output, or copy
a simple integration pattern into your own app, backend job, data pipeline, or
AI workflow.

## Prerequisites

- An Apify account
- Your own Apify API token
- A public TikTok video URL to test
- One of the supported runtimes for the examples you want to run

The Actor page is available at
[https://apify.com/apple_yang/tiktok-transcripts-scraper](https://apify.com/apple_yang/tiktok-transcripts-scraper).

## Create an Apify token

1. Sign in to your Apify account.
2. Open your account settings in Apify Console.
3. Find the API token section.
4. Create or copy an API token for local development.
5. Keep the token private and do not commit it to Git.

You need your own Apify account and token to run these examples.

## Configure environment variables

From the repository root:

```bash
cp .env.example .env
```

Edit `.env`:

```bash
APIFY_TOKEN=your_apify_token_here
APIFY_ACTOR_ID=apple_yang/tiktok-transcripts-scraper
TIKTOK_VIDEO_URL=https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392
MAX_CONCURRENCY=3
```

`APIFY_TOKEN` is required. `APIFY_ACTOR_ID` and `TIKTOK_VIDEO_URL` have defaults
in the examples, but keeping them in `.env` makes local testing clearer.

## Run cURL first

The cURL example is the fastest validation path because it has no project
dependencies.

```bash
bash examples/curl/single-url-sync.sh
```

The full JSON response is saved to:

```text
sample-output/generated/curl-single-url-response.json
```

You can also pass a TikTok URL directly:

```bash
bash examples/curl/single-url-sync.sh "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
```

## Run Python

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r examples/python/requirements.txt
python examples/python/single_url.py
```

The full JSON response is saved to:

```text
sample-output/generated/python-single-url-response.json
```

## Run Node.js

```bash
cd examples/nodejs
npm install
cd ../..
node examples/nodejs/single-url.mjs
```

The full JSON response is saved to:

```text
sample-output/generated/nodejs-single-url-response.json
```

## Next steps

- Review [API reference](api-reference.md) for input and output fields.
- Review [troubleshooting](troubleshooting.md) if a run fails.
- Review [batch processing](batch-processing.md) before processing many URLs.
- Review [AI workflows](ai-workflows.md) for LLM and automation ideas.
