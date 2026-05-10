# Use TikTok Transcript API with Claude via Apify MCP

This guide describes how the TikTok transcripts Actor can fit into a Claude
workflow through Apify MCP.

This repository does not include a ready-made Claude integration. It provides
the Actor details, examples, and prompt patterns needed to build or configure
your own workflow.

## Flow

1. Provide a public TikTok video URL.
2. Run the Apify Actor `apple_yang/tiktok-transcripts-scraper` through Apify
   MCP.
3. Retrieve the Actor dataset output.
4. Use the transcript result as Claude input.
5. Ask Claude to extract creator insights, hooks, structure, themes, and
   reusable content ideas.

## Actor input

```json
{
  "videoUrl": "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
}
```

## Example Claude prompt

```text
Use Apify MCP to run apple_yang/tiktok-transcripts-scraper with this TikTok URL.

When the dataset output is available, analyze the transcript and return:
- Creator positioning notes
- Opening hook
- Content structure
- Recurring themes
- Audience pain points or interests
- Suggestions for a similar short-form video concept
- Any errMsg
```

## Practical uses

- Creator research
- Campaign planning
- Content style analysis
- Trend notes
- Message extraction
- Brand safety review based on transcript text

## Notes

MCP client configuration varies by Claude environment. Follow your client's MCP
setup instructions and keep Apify credentials out of shared files.
