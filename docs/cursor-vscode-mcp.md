# Cursor and VS Code MCP Setup for TikTok Transcript API

This guide shows practical MCP setup patterns for using the TikTok transcripts
Actor inside Cursor, VS Code, or another AI coding environment.

This repository does not include a ready-made editor extension. Use these
configuration examples manually in an MCP-capable editor or AI coding client.

For the central MCP reference, see [Apify MCP setup](apify-mcp.md).

## Cursor setup

1. Open the project in Cursor.
2. Create `.cursor/mcp.json` if it does not exist.
3. Paste one of the config options below.
4. Restart Cursor or reconnect MCP tools.
5. Confirm the Apify tool appears.
6. Run the test prompt.

The Apify MCP UI configurator at [https://mcp.apify.com](https://mcp.apify.com)
may provide one-click Cursor setup when available.

### Hosted OAuth config

```json
{
  "mcpServers": {
    "apify": {
      "url": "https://mcp.apify.com?tools=apple_yang/tiktok-transcripts-scraper"
    }
  }
}
```

After saving the file, restart Cursor or reconnect MCP tools. Sign in to Apify
through OAuth if prompted.

### Hosted Bearer token config

Use this only in secure local configuration:

```json
{
  "mcpServers": {
    "apify": {
      "url": "https://mcp.apify.com?tools=apple_yang/tiktok-transcripts-scraper",
      "headers": {
        "Authorization": "Bearer <APIFY_TOKEN>"
      }
    }
  }
}
```

Do not commit a token-bearing `.cursor/mcp.json`.

### Local stdio fallback

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

Restart Cursor after changing MCP configuration.

## Cursor test prompt

```text
Use Apify MCP to run the Actor `apple_yang/tiktok-transcripts-scraper` with this input:

{
  "videoUrl": "https://www.tiktok.com/@carter.braydon/video/7647694374876319007"
}

Retrieve the dataset output and generate a TypeScript interface for the fields returned.
```

## VS Code setup

MCP support in VS Code depends on the installed AI extension or client. For
GitHub Copilot agent mode or another MCP-capable extension, use this generic
path:

1. Install or enable an MCP-capable AI extension.
2. Open Command Palette.
3. Search for an MCP user configuration command, such as
   `MCP: Open User Configuration`, if available.
4. Add the same hosted OAuth, hosted Bearer token, or local stdio config from
   the Cursor section.
5. Save the config.
6. Restart or reload VS Code.
7. Open a new agent chat.
8. Test with the prompt below.

Do not assume every VS Code installation supports MCP by default. The exact
configuration path depends on the extension or AI client.

## VS Code test prompt

```text
Use Apify MCP to run `apple_yang/tiktok-transcripts-scraper` with this TikTok URL:

https://www.tiktok.com/@carter.braydon/video/7647694374876319007

Return the transcript text, title, creator nickname, duration, play count, and any `errMsg`.
```

## What developers can build after MCP works

- Content analysis tool
- Transcript database
- API wrapper
- Internal research workflow
- AI coding assistant-generated scripts
- Tests based on saved Actor output
- Schema generation for transcript and metadata records

## Troubleshooting

- If tools do not appear, restart the editor and confirm the MCP config path.
- If hosted auth fails, reconnect OAuth or switch to local stdio.
- If local stdio fails, confirm Node.js and `npx` are available.
- If output is incomplete, ask the agent to retrieve the full dataset output.
