# Cursor and VS Code with Apify MCP

These are separate client configurations for the fixed TikTok Actor
[`apple_yang/tiktok-transcripts-scraper`](https://apify.com/apple_yang/tiktok-transcripts-scraper).
Do not copy Cursor's `mcpServers` block into VS Code's native `servers` file.
Apify's hosted endpoint is Streamable HTTP and uses OAuth when supported.
See the [MCP compatibility matrix](mcp-compatibility.md) for verification
scope across clients.

The URL below enables Apify's `actors`, `runs`, and `storage` tool categories
plus the specific Actor tool. Categories expose multiple operations; inspect
the tools discovered by your client. See [Apify MCP tool selection and result
retrieval](apify-mcp.md#calling-the-actor-and-reading-its-output).

## Cursor

As checked on 2026-10-27, Cursor documents MCP configuration in the project
file `.cursor/mcp.json` or the user-level `~/.cursor/mcp.json`. The JSON uses
the top-level `mcpServers` object. You can also add a server from Cursor's MCP
settings UI; labels may vary with the Cursor release. See the current
[Cursor MCP guide](https://prod.cursor.com/docs/mcp).

```json
{
  "mcpServers": {
    "apify": {
      "url": "https://mcp.apify.com?tools=actors,runs,storage,apple_yang/tiktok-transcripts-scraper"
    }
  }
}
```

Save the file, reconnect the server in Cursor, and complete OAuth if prompted.
For hosted MCP, no local Node.js is required. Do not add a token directly to a
project file.

## VS Code with GitHub Copilot

Current VS Code guidance is to run **MCP: Add Server** from the Command
Palette, choose **HTTP**, enter the Apify endpoint, and follow the
authentication prompt. The guided flow can write a global Copilot config or a
workspace config depending on your chosen destination and installed harness.

The native VS Code format uses `servers` and a `type`; for the current native
workspace file `.vscode/mcp.json`, the equivalent remote config is:

```json
{
  "servers": {
    "apify": {
      "type": "http",
      "url": "https://mcp.apify.com?tools=actors,runs,storage,apple_yang/tiktok-transcripts-scraper"
    }
  }
}
```

If you instead use a portable Copilot configuration, VS Code documents a
top-level `mcpServers` object (for example, `.mcp.json` for compatible
workspace use). Portable configuration does not support VS Code input
variables or environment files. Keep authentication in the client sign-in
flow or the supported secure configuration for the chosen harness; do not
paste a real token into a shared file. The current [VS Code guide](https://code.visualstudio.com/docs/agent-customization/mcp-servers)
explains destinations and format differences.

## Run, retrieve, then analyze

Ask the client to call the Actor with only one input field:

```text
{"videoUrl":"https://www.tiktok.com/@carter.braydon/video/7647694374876319007"}
```

The Actor's `call-actor` flow can return Run status and storage IDs rather than
Dataset items. Use the Run ID to check status, then the Dataset ID to retrieve
Dataset Items. Inspect the actual result: Run `SUCCEEDED`, non-empty
transcript text, and an empty `errMsg` are separate checks. Requests for a
summary or TypeScript interface are analysis of returned fields, not a promise
that the Actor emits a particular optional field. See the [public Output
schema](https://apify.com/apple_yang/tiktok-transcripts-scraper/output-schema).

If the tool is missing, inspect the client's MCP tool list, confirm the URL
and OAuth state, and reconnect. If output is truncated, retrieve the same
Dataset ID again. If a Run is still active, check the same Run ID; if Run
creation is ambiguous, check Apify Console before retrying.

Review the Actor's [current pricing](https://apify.com/apple_yang/tiktok-transcripts-scraper/pricing)
before running it. No free-use or fixed-cost promise is made here.

## Validation status (checked 2026-10-27)

- **Official docs:** Cursor's `mcpServers` locations and VS Code's MCP wizard,
  native `servers` schema, and portable-format distinction were reviewed in
  the linked client documentation.
- **Static configuration:** the JSON snippets were checked against those
  published formats; neither editor was launched.
- **Repository offline tests:** test the language API examples, not Cursor or
  VS Code MCP configuration or authentication.
- **Real MCP connection / Actor Run:** not verified.
