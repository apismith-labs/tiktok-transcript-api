# Release Notes

## v1.0.0

Initial release draft for `tiktok-transcript-api`, a developer example
repository for the TikTok Transcript API powered by Apify.

## Project summary

This repository provides production-friendly examples for extracting TikTok
video transcripts with the Apify Actor
[`apple_yang/tiktok-transcripts-scraper`](https://apify.com/apple_yang/tiktok-transcripts-scraper).

The examples use the minimal Actor input:

```json
{
  "videoUrl": "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
}
```

Users must provide their own Apify account and `APIFY_TOKEN`.

## Included language examples

- cURL
- Python
- Node.js
- Java
- Go
- Rust

Each example reads configuration from environment variables, calls the Apify
Actor, retrieves dataset results, prints transcript and metadata fields, and
saves the full response under `sample-output/generated/`.

## Included documentation

- Quick start
- API reference
- Batch processing guide
- AI workflows
- AI agent use cases
- Prompt recipes
- Apify MCP overview
- ChatGPT, Claude, Gemini CLI, Cursor, and VS Code workflow notes
- Troubleshooting guide

## Links

- Apify Actor:
  [https://apify.com/apple_yang/tiktok-transcripts-scraper](https://apify.com/apple_yang/tiktok-transcripts-scraper)
- Transcript365 web demo:
  [https://www.transcript365.com/free/tiktok-transcript](https://www.transcript365.com/free/tiktok-transcript)

## Notes

- Transcript availability may vary by TikTok video.
- Output fields and `segments` shape should be verified with real Actor output
  before building strict schemas.
- Generated output files are ignored by Git under `sample-output/generated/`.
