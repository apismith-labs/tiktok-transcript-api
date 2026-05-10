# Claude Desktop MCP Setup for TikTok Transcript API

This guide shows how to configure Claude Desktop to use the TikTok transcripts
Actor through Apify MCP.

This repository does not include a ready-made Claude integration. Use these
steps to configure Claude Desktop or another Claude-compatible MCP client
manually.

Exact Claude Desktop UI and remote MCP support can vary by version, account,
and rollout status.

For the central MCP reference, see [Apify MCP setup](apify-mcp.md).

## Recommended remote connector setup

Use this path when Claude Desktop supports remote MCP connectors.

1. Open Claude Desktop.
2. Add a custom connector or MCP server.
3. Use this remote MCP server URL:

   ```text
   https://mcp.apify.com?tools=apple_yang/tiktok-transcripts-scraper
   ```

4. Sign in to Apify through OAuth if prompted.
5. Save the connector.
6. Restart Claude Desktop if the tools do not appear immediately.
7. Open a new chat and confirm Apify tools are available.

Exact labels may vary by Claude Desktop version and MCP support.

## Alternative local stdio setup

Use this path when Claude Desktop expects a local MCP server configuration.

If your Claude Desktop environment uses a local MCP configuration file, add a
server like this:

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

This requires Node.js 18 or newer and `npx` on your machine. Do not commit
configuration files that contain a real token.

Check local requirements:

```bash
node -v
npx -v
```

## Verify the connection

1. Restart Claude Desktop if needed.
2. Open a new chat.
3. Confirm Apify tools are available.
4. Ask Claude to run the Actor with the sample TikTok URL.
5. Ask Claude to retrieve the full dataset output if the first response is only
   a preview.

## Actor input

```json
{
  "videoUrl": "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
}
```

## Ready-to-copy Claude prompt

```text
Use Apify MCP to run `apple_yang/tiktok-transcripts-scraper` with this input:

{
  "videoUrl": "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
}

After the dataset output is available, analyze the TikTok transcript and return:
- transcript text
- title
- creator nickname
- opening hook
- content structure
- recurring themes
- audience pain points or interests
- duration
- play count
- any `errMsg`
```

## Troubleshooting

### Tools do not load

- Confirm the MCP config is valid JSON.
- Restart Claude Desktop.
- Confirm the `tools` value is exactly `apple_yang/tiktok-transcripts-scraper`.

### OAuth or authentication fails

- Reconnect the Apify account.
- Confirm you have access to the Actor.
- For local stdio, confirm `APIFY_TOKEN` is set in the MCP config.

### Local stdio cannot find Node.js

- Install Node.js.
- Confirm `npx` works in your terminal.
- Use hosted Apify MCP if your Claude environment supports remote servers.

### Actor run takes too long

- Ask Claude to check the Actor run status again.
- Try another public TikTok URL.
- Inspect the run in Apify Console if a run ID is available.

### Dataset output is truncated

Use a follow-up prompt:

```text
Retrieve the full dataset output for the Actor run. Show the raw fields before analysis.
```
