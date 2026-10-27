# Apify MCP Setup for TikTok Transcript API

This guide helps you connect an MCP-compatible AI client to Apify MCP, restrict
the available tools to the TikTok transcripts Actor, run the Actor with a TikTok
video URL, and retrieve transcript dataset output for analysis.

Actor:
[`apple_yang/tiktok-transcripts-scraper`](https://apify.com/apple_yang/tiktok-transcripts-scraper)

MCP server URL:

```text
https://mcp.apify.com
```

Exact screens and file locations vary by MCP client, but the connection values
below are the important pieces.

## Prerequisites

- Apify account
- Apify API token, or OAuth-based Apify MCP connection
- MCP-compatible client
- Access to the Actor `apple_yang/tiktok-transcripts-scraper`
- Public TikTok video URL

## Minimal Actor input

```json
{
  "videoUrl": "https://www.tiktok.com/@carter.braydon/video/7647694374876319007"
}
```

Do not add extra Actor input fields unless the Actor page or a real Actor run
confirms them.

## Recommended setup: hosted Apify MCP

Use hosted Apify MCP when your client supports remote MCP server URLs.
Hosted Apify MCP uses Streamable HTTP and OAuth when supported by the client.
This is the recommended path because it avoids storing an Apify token in local
configuration files.

You can also open the Apify MCP UI configurator at
[https://mcp.apify.com](https://mcp.apify.com), select the Actor tool
`apple_yang/tiktok-transcripts-scraper`, and copy configuration for supported
clients.

## Which option should I choose?

- Use hosted OAuth first if your client supports remote MCP servers.
- Use hosted Bearer token only in secure local or server-side configs.
- Use local stdio if your client does not support remote MCP URLs.

### Option A: hosted MCP with OAuth

Use this when your MCP client supports OAuth sign-in for remote MCP servers:

```json
{
  "mcpServers": {
    "apify": {
      "url": "https://mcp.apify.com?tools=apple_yang/tiktok-transcripts-scraper"
    }
  }
}
```

After saving the config, connect the MCP server in your client and sign in to
Apify in the browser when prompted.

### Option B: hosted MCP with Bearer token

Use this only in a secure local or server-side configuration:

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

Do not commit configuration files that contain a real token.

### Option C: local stdio MCP server with `npx`

Use this when your client supports stdio MCP servers or does not support remote
MCP URLs:

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

This requires Node.js 18 or newer and network access for `npx` to install or
run the MCP server package.

## Check local requirements

Run these commands before using the local stdio option:

```bash
node -v
npx -v
```

If either command is missing, install Node.js 18 or newer or use hosted Apify
MCP instead.

## Restrict tools to this Actor

The `tools=apple_yang/tiktok-transcripts-scraper` query parameter, or the
`--tools apple_yang/tiktok-transcripts-scraper` local stdio argument, limits the
MCP server to this Actor. This keeps the AI client focused and reduces the
chance of calling unrelated Apify tools.

## Test the connection

1. Save the MCP configuration in your client.
2. Restart or reconnect the client if required.
3. Confirm that an Apify tool or Actor tool is visible.
4. Ask the client to run the test prompt below.
5. If the client only shows an output preview, ask it to retrieve the full
   dataset output.

## Ready-to-copy test prompt

```text
Use Apify MCP to run the Actor `apple_yang/tiktok-transcripts-scraper` with this input:

{
  "videoUrl": "https://www.tiktok.com/@carter.braydon/video/7647694374876319007"
}

After the Actor run finishes, retrieve the dataset output and return:

- transcript text
- title
- creator nickname
- duration
- play count
- any `errMsg`
```

## Retrieve full dataset output

Some MCP clients show only a preview after an Actor run. If that happens, ask
the AI client to fetch the full Actor output or full dataset items for the run.

Useful follow-up prompt:

```text
Retrieve the full dataset output for the Actor run. Do not summarize yet.
Return the raw dataset item fields that are available.
```

## Common MCP troubleshooting

### Actor tool does not appear

- Confirm the MCP server config was saved in the right client location.
- Restart or reconnect the MCP client.
- Confirm the `tools` value is exactly `apple_yang/tiktok-transcripts-scraper`.
- Try the hosted OAuth config first if your client supports it.

### Authorization failed

- Reconnect OAuth if using hosted MCP with OAuth.
- Confirm the Bearer token is a real Apify token.
- Replace `<APIFY_TOKEN>` with the real token while keeping the JSON syntax
  valid.

### Local stdio server does not start

- Confirm Node.js and `npx` are available.
- Confirm the client allows stdio MCP servers.
- Check whether your environment blocks package downloads.
- Try hosted Apify MCP instead.

### Actor run takes too long

- Wait for the run to finish or ask the client to check the run status again.
- Try another public TikTok URL.
- Inspect the run in Apify Console if you have the run ID.

### Dataset output is truncated

- Ask the client to retrieve full dataset items.
- Ask for raw JSON first, then run analysis in a second step.
- Preserve the run ID and dataset ID when available.
