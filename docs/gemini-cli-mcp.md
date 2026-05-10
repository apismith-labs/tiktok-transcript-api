# Gemini CLI and Terminal AI Workflows

This guide gives two practical paths for using TikTok transcript results in
Gemini CLI or a similar command-line AI workflow.

This repository does not provide a custom Gemini CLI extension. MCP support and
configuration vary by CLI and agent framework.

## Path A: reliable local workflow without MCP

Use this path when you want a dependable terminal workflow without relying on
MCP support.

1. Configure `.env` with your Apify token:

   ```bash
   cp .env.example .env
   ```

2. Run one of the examples:

   ```bash
   python examples/python/single_url.py
   ```

3. Open the generated output:

   ```text
   sample-output/generated/python-single-url-response.json
   ```

4. Preview the transcript text from the saved JSON:

   ```bash
   python - <<'PY'
   import json
   from pathlib import Path

   path = Path("sample-output/generated/python-single-url-response.json")
   items = json.loads(path.read_text(encoding="utf-8"))
   print((items[0].get("text") or "")[:2000])
   PY
   ```

5. Copy the full JSON, the first dataset item, or just the `text` field into
   Gemini CLI or another command-line AI tool.

### Copyable prompt

```text
Analyze this TikTok transcript JSON.

Return:
- transcript summary
- title
- creator nickname
- opening hook
- content structure
- product or brand mentions
- sentiment
- suggested categories
- any missing or uncertain fields

JSON:
{{paste_dataset_json_here}}
```

## Path B: MCP-capable Gemini or command-line AI environment

If your Gemini CLI setup or command-line AI framework supports MCP server
configuration, use the hosted or local Apify MCP setup from
[Apify MCP setup](apify-mcp.md).

Hosted MCP URL:

```text
https://mcp.apify.com?tools=apple_yang/tiktok-transcripts-scraper
```

Local stdio command pattern:

```json
{
  "mcpServers": {
    "apify": {
      "command": "npx",
      "args": [
        "-y",
        "@apify/actors-mcp-server@latest",
        "--tools",
        "apple_yang/tiktok-transcripts-scraper"
      ],
      "env": {
        "APIFY_TOKEN": "<APIFY_TOKEN>"
      }
    }
  }
}
```

Exact setup depends on the CLI or agent framework. If MCP tool output is only a
preview, ask the client to retrieve the full dataset output before analysis.

## Actor input

```json
{
  "videoUrl": "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
}
```
