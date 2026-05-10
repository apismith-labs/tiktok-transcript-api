# Use TikTok Transcript API with Gemini CLI

Gemini CLI and similar command-line AI workflows can use TikTok transcript
results as structured input for analysis, summarization, or code generation.

This repository does not provide a custom Gemini CLI extension. Use the examples
or Apify MCP as building blocks for your own terminal workflow.

## Developer flow

```text
TikTok URL -> Apify Actor -> dataset JSON -> Gemini CLI prompt -> structured output
```

You can run one of this repository's examples first, save the dataset JSON under
`sample-output/generated/`, then pass the transcript text or selected fields to
your command-line AI workflow.

## Actor input

```json
{
  "videoUrl": "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
}
```

## Example prompt

```text
Analyze this TikTok transcript JSON.

Return:
- Summary
- Main topic
- Hook
- Content structure
- Product or brand mentions
- Suggested categories
- Any missing or uncertain fields
```

## Useful tasks

- Inspect raw Actor output.
- Generate TypeScript interfaces or database schemas for transcript records.
- Draft batch-processing scripts around `videoUrl` inputs.
- Create content analysis reports from saved dataset JSON.
- Compare output fields across multiple test runs.

## Notes

For live Actor calls from an AI tool, exact setup depends on the MCP or command
line environment you use. Keep `APIFY_TOKEN` private and avoid pasting secrets
into shared prompts.
