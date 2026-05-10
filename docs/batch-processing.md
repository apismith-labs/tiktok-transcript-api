# Batch Processing TikTok Video URLs

This guide describes how to build batch processing around the single-video
examples in this repository.

The repository currently includes single-video examples only. Use this guide as
an implementation pattern before adding batch code to your own project.

## CSV input

Start with [sample-data/tiktok-video-urls.csv](../sample-data/tiktok-video-urls.csv).

Recommended CSV format:

```csv
videoUrl
https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392
```

Each row should contain one TikTok video URL in the `videoUrl` column.

## Suggested workflow

1. Read the CSV file.
2. Validate that each row has a non-empty `videoUrl`.
3. Run the Apify Actor `apple_yang/tiktok-transcripts-scraper` once for each URL.
4. Wait for each Actor run to finish.
5. Fetch dataset results for each run.
6. Save successful records to JSON or JSONL.
7. Save failed records to a separate CSV or JSON file.
8. Preserve the source URL with every result.

## Suggested result shape

For batch workflows, keep one normalized record per input URL:

```json
{
  "sourceUrl": "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392",
  "status": "success",
  "text": "",
  "segments": [],
  "errMsg": "",
  "rawItems": []
}
```

The `rawItems` field is useful during validation because Actor output may vary
by video.

## Production considerations

- Retries: retry temporary network failures, rate limits, and timeouts with
  backoff. Avoid retrying clearly invalid input forever.
- Rate limits: keep concurrency modest until you understand Apify usage,
  latency, and any platform-specific limits.
- Failed URLs: write failures to a durable file or database table with the
  source URL, error message, attempt count, and timestamp.
- Empty transcripts: treat empty `text` as a valid failure mode to inspect, not
  as proof that the integration is broken.
- Logging: log run IDs, dataset IDs, source URLs, and statuses. Never log
  `APIFY_TOKEN`.
- Output storage: store generated files outside version control. This
  repository ignores `sample-output/generated/`.
- Resumability: for larger CSV files, checkpoint progress so a failed job can
  continue without starting from the beginning.
