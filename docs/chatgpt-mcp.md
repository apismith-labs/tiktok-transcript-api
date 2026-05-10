# Use TikTok Transcript API with ChatGPT via Apify MCP

This guide explains the conceptual flow for using the TikTok transcripts Actor
with ChatGPT through Apify MCP.

This repository does not directly configure ChatGPT, provide a custom ChatGPT
connector, or include a hosted proxy. It provides examples and documentation you
can use when designing that workflow.

## Flow

1. Send a TikTok video URL to ChatGPT.
2. Use Apify MCP to run the Apify Actor `apple_yang/tiktok-transcripts-scraper`.
3. Retrieve the Actor dataset output.
4. Pass `text`, `segments`, and useful metadata to ChatGPT.
5. Ask ChatGPT to summarize, classify, extract hooks, analyze content, or return
   structured insights.

## Actor input

```json
{
  "videoUrl": "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
}
```

## Example ChatGPT prompt

```text
Use Apify MCP to run the TikTok transcripts Actor for this TikTok URL.

After the Actor finishes, retrieve the dataset output and return:
- Transcript summary
- Opening hook
- Main claims or talking points
- Content structure
- Product or brand mentions
- Suggested tags
- Any errMsg
```

## Useful analysis tasks

- Summarize TikTok transcript text.
- Classify a video by topic, format, audience, or funnel stage.
- Extract hooks and calls to action.
- Generate structured content insights.
- Turn transcript text into a content brief.
- Compare multiple transcript outputs outside this repository's current
  single-video examples.

## Notes

Exact setup depends on ChatGPT's available connector and MCP features in your
environment. Keep credentials private, review tool calls, and verify raw Actor
output before relying on structured analysis.
