# Use TikTok Transcript API with Apify MCP

Apify MCP lets MCP-compatible AI tools discover and call Apify Actors. In this
repository's context, it can be used to run the TikTok transcripts Actor and
pass transcript text into an AI workflow.

Use this when you want an AI tool to call the Apify Actor
`apple_yang/tiktok-transcripts-scraper`, retrieve the Actor dataset output, and
then summarize, classify, transform, or analyze the transcript.

## Prerequisites

- Apify account
- Apify API token or supported Apify connection
- Access to the Apify Actor `apple_yang/tiktok-transcripts-scraper`
- MCP-compatible client
- Public TikTok video URL

Actor page:
[https://apify.com/apple_yang/tiktok-transcripts-scraper](https://apify.com/apple_yang/tiktok-transcripts-scraper)

## Minimal Actor input

```json
{
  "videoUrl": "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
}
```

Do not add extra Actor input fields unless they are verified by the Actor page
or a real Actor run.

## How this fits

The high-level flow is:

```text
MCP client -> Apify MCP -> TikTok transcripts Actor -> dataset output -> AI analysis
```

The Actor can provide transcript text, segments when available, source URL, and
metadata such as title, creator nickname, and engagement counts. AI tools can
then use that data to generate summaries, tags, content briefs, research notes,
or structured records.

## Setup note

Exact MCP setup steps depend on your MCP client. Some clients support remote MCP
servers, while others use local configuration files or command-line MCP
servers. Follow your client's documentation and Apify's MCP documentation for
the exact connection format.

## Suggested AI prompt

```text
Use Apify MCP to run the Actor apple_yang/tiktok-transcripts-scraper.

Input:
{
  "videoUrl": "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
}

After the run completes, retrieve the dataset output and summarize:
- Main topic
- Opening hook
- Key points
- Call to action
- Product or brand mentions
- Any errMsg
```

## Safety notes

- Keep Apify tokens out of committed files and public prompts.
- Review tool calls before running them in an AI client.
- Treat transcript availability as video-dependent.
- Preserve raw Actor output during early integration.
