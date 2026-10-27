# AI Workflows with TikTok Transcripts

TikTok transcript data can be routed into AI systems for analysis,
summarization, search, and structured content operations.

This repository provides API examples, not ready-made automation integrations.
You can use the same Actor calls inside n8n, Make, Zapier, custom backend jobs,
or AI agents that can call HTTP APIs.

## Example workflow

```text
TikTok URL -> Apify Actor -> transcript text -> LLM analysis -> structured output
```

The structured output might be a summary, topic list, hook analysis, content
brief, sentiment note, subtitle draft, or database record.

## Choose your implementation path

- Direct API/examples: use the cURL, Python, Node.js, Java, Go, or Rust examples
  in [examples](../examples/).
- Apify MCP: use [Apify MCP setup](apify-mcp.md).
- ChatGPT: use [ChatGPT MCP setup](chatgpt-mcp.md).
- Claude: use [Claude Desktop MCP setup](claude-mcp.md).
- Cursor and VS Code: use [Cursor and VS Code MCP setup](cursor-vscode-mcp.md).
- Gemini CLI or terminal workflows: use
  [Gemini CLI and terminal AI workflows](gemini-cli-mcp.md).
- Check client-specific setup and what has actually been verified in the
  [MCP compatibility matrix](mcp-compatibility.md).

## Use cases

### Creator research

Collect transcripts from selected creator videos and ask an LLM to identify
recurring topics, positioning, audience language, product mentions, and brand
fit signals.

### Short-form video analysis

Use transcript text and metadata to compare hooks, pacing, calls to action,
message clarity, and repeated creative patterns across videos.

### Social media monitoring

Process public TikTok video URLs collected by a monitoring workflow and route
transcripts into dashboards, alerts, spreadsheets, or search indexes.

### Content repurposing

Turn transcript text into blog outlines, social posts, email drafts, short-form
scripts, content briefs, or internal research notes.

### Trend analysis

Group videos by topic, creator, campaign, or time period, then use transcript
text to extract recurring language, claims, formats, and emerging themes.

### Subtitle workflows

Use transcript text and `segments` when available to draft subtitle-friendly
lines, translations, or accessibility review notes. Verify segment timing with
real Actor output before building strict subtitle exports.

### LLM-based summarization

Send the `text` field to an LLM with metadata such as `title`, `nickname`,
`playCount`, and `commentCount` to generate concise summaries or structured
analysis.

## Prompt example

```text
Analyze this TikTok transcript.

Creator: {{nickname}}
Title: {{title}}
Transcript:
{{text}}

Return:
- Main topic
- Opening hook
- Key points
- Call to action
- Product or brand mentions
- Reusable content ideas
```

## Integration notes

- Keep the raw Actor output for debugging.
- Redact secrets from logs and prompts.
- Treat transcript availability as video-dependent.
- Review LLM output before using it in production decisions.
