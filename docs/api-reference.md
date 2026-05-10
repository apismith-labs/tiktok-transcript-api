# TikTok Transcript API Reference

This repository calls the TikTok transcripts Actor on Apify.

## Actor

- Actor ID: `apple_yang/tiktok-transcripts-scraper`
- Actor page: [https://apify.com/apple_yang/tiktok-transcripts-scraper](https://apify.com/apple_yang/tiktok-transcripts-scraper)

## Input

Use the minimal Actor input:

```json
{
  "videoUrl": "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
}
```

Do not add extra input fields unless they are confirmed by the Actor page or a
real Actor run.

## Output fields

Actual fields may vary depending on the TikTok video, transcript availability,
and Actor result. Treat all metadata fields as optional unless your own testing
proves otherwise.

| Field | Description |
| --- | --- |
| `url` | Source TikTok video URL or canonical URL returned by the Actor. |
| `title` | Video title, caption, or descriptive text when available. |
| `audioUrl` | Audio URL returned by the Actor when available. |
| `createTime` | Video creation time value returned by the Actor. |
| `playCount` | Number of plays or views when available. |
| `commentCount` | Number of comments when available. |
| `diggCount` | Number of likes when available. |
| `shareCount` | Number of shares when available. |
| `collectCount` | Number of saves or collections when available. |
| `duration` | Video duration when available. |
| `text` | Transcript text. This is usually the primary field application code consumes. |
| `segments` | Timestamped transcript segments when available. The exact segment object shape should be verified with a real Actor run. |
| `nickname` | Creator display name when available. |
| `avatarUri` | Creator avatar URL when available. |
| `signature` | Creator profile signature or bio text when available. |
| `secUid` | Creator identifier returned by the Actor when available. |
| `followerCount` | Creator follower count when available. |
| `followingCount` | Creator following count when available. |
| `heartCount` | Creator total like count when available. |
| `errMsg` | Error message returned by the Actor for failed or partial processing. |
| `timestamp` | Processing timestamp or transcript timestamp metadata returned by the Actor. |

## Parsing guidance

Production integrations should preserve the raw Actor output during early
validation. Normalize only the fields your application needs, and keep `errMsg`
for failed records so operators can investigate input-specific issues.
