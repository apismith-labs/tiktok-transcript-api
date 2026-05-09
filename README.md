# TikTok Transcript API

Production-ready examples for extracting TikTok video transcripts with Apify.

This repository provides developer-focused examples and integration patterns for
the Apify Actor
[apple_yang/tiktok-transcripts-scraper](https://apify.com/apple_yang/tiktok-transcripts-scraper).

Use it to validate TikTok transcript extraction, plan batch workflows, and build
transcript data into apps, internal tools, databases, analytics pipelines, and
AI-assisted content workflows.

## Apify Actor

- Actor page: [Stable Tiktok Transcripts Scraper](https://apify.com/apple_yang/tiktok-transcripts-scraper)
- Actor ID: `apple_yang/tiktok-transcripts-scraper`

## Quick start

1. Create a local environment file:

   ```bash
   cp .env.example .env
   ```

2. Add your Apify token:

   ```bash
   APIFY_TOKEN=your_apify_token_here
   APIFY_ACTOR_ID=apple_yang/tiktok-transcripts-scraper
   TIKTOK_VIDEO_URL=https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392
   MAX_CONCURRENCY=3
   ```

3. Run a planned language example after the example implementations are added.

   The initial scaffold includes repository configuration, sample input data,
   and the documented Actor input model. Runnable language examples will be
   added in follow-up steps.

## Authentication

You must provide your own Apify API token.

Do not hard-code tokens in source code, scripts, docs, commits, logs,
screenshots, or shared output files.

Configuration belongs in `.env`:

- `APIFY_TOKEN`
- `APIFY_ACTOR_ID`
- `TIKTOK_VIDEO_URL`
- `MAX_CONCURRENCY`

TikTok video URLs should be treated as runtime input in production examples.
The `TIKTOK_VIDEO_URL` value in `.env.example` is only a convenient local
validation default.

## Actor input

The verified Actor input field is `videoUrl`:

```json
{
  "videoUrl": "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
}
```

Do not add undocumented Actor input fields without verifying them against a real
Actor run or the Actor page.

## Important output fields

The Actor page shows these output fields:

- `url`
- `title`
- `audioUrl`
- `createTime`
- `playCount`
- `commentCount`
- `diggCount`
- `shareCount`
- `collectCount`
- `duration`
- `text`
- `segments`
- `nickname`
- `avatarUri`
- `signature`
- `secUid`
- `followerCount`
- `followingCount`
- `heartCount`
- `errMsg`
- `timestamp`

Treat metadata fields as optional in production code. The exact `segments`
object shape and field types should be verified with a real Actor run before
building strict schemas.

## Planned examples

This repository will include examples for:

- cURL
- Python
- Node.js
- Java
- Go
- Rust

The planned examples will cover single-video validation and batch processing
from CSV where appropriate.

## Use cases

- TikTok transcript extraction
- TikTok caption and subtitle workflows
- Creator research
- Social media monitoring
- AI content analysis
- Batch transcript processing

## Repository layout

```text
.
├── docs/
│   └── .gitkeep
├── examples/
│   ├── curl/
│   ├── go/
│   ├── java/
│   ├── nodejs/
│   ├── python/
│   └── rust/
├── sample-data/
│   └── tiktok-video-urls.csv
├── sample-output/
│   └── .gitkeep
├── .env.example
├── .gitignore
├── LICENSE
└── README.md
```

## License

This project is licensed under the MIT License.
