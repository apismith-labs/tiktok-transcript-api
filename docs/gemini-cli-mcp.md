# Gemini CLI and Apify MCP

This guide connects Gemini CLI to Apify's hosted MCP service for the fixed
Actor [`apple_yang/tiktok-transcripts-scraper`](https://apify.com/apple_yang/tiktok-transcripts-scraper).
The hosted endpoint is Streamable HTTP, not SSE; do not append `/sse`.
See the [MCP compatibility matrix](mcp-compatibility.md) for verification
scope across clients.

## Hosted Streamable HTTP setup

As checked on 2026-10-27, Gemini CLI's official configuration reference
distinguishes `httpUrl` for Streamable HTTP, `url` for SSE, and `command` for
stdio. The user configuration file is `~/.gemini/settings.json` (or the
settings file for your chosen Gemini CLI profile). Add this to its top-level
`mcpServers` object:

```json
{
  "mcpServers": {
    "apify": {
      "httpUrl": "https://mcp.apify.com?tools=actors,runs,storage,apple_yang/tiktok-transcripts-scraper"
    }
  }
}
```

Apify supports OAuth for the hosted endpoint. Complete the authentication
flow if Gemini CLI prompts you; follow the current [Gemini MCP OAuth guide](https://geminicli.com/docs/tools/mcp-server/#oauth-support-for-remote-mcp-servers)
if your installation needs additional OAuth settings. If using a fixed
Bearer token instead, configure it only using a supported secure credential
mechanism for your Gemini CLI version; do not paste it into a shared
`settings.json`.

The Apify `tools` selector includes actor, run, and storage categories plus
the TikTok Actor tool. Categories expose multiple operations, and the exact
tool list can change. The URL only enables tools; it does not prove they are
connected. See [Apify MCP result retrieval](apify-mcp.md#calling-the-actor-and-reading-its-output).

## Other transports

Gemini CLI's documented `mcpServers` fields are transport-specific:

| Transport | Field | Example endpoint/process |
| --- | --- | --- |
| Streamable HTTP | `httpUrl` | `https://mcp.apify.com?...` |
| SSE | `url` | An actual SSE endpoint, if a server provides one |
| stdio | `command`, optional `args` / `env` | A local process |

Do not configure Apify's current hosted endpoint under `url`: Gemini CLI would
interpret that field as SSE. Local stdio is optional; Apify's docs disagree
about the minimum Node.js version, so use Node.js 22+ conservatively and check
the [dated Apify MCP runtime note](apify-mcp.md#local-stdio-option). This local
runtime requirement does not apply to hosted HTTP.

## Run and inspect the Dataset

Use only the Actor's public input:

```json
{"videoUrl":"https://www.tiktok.com/@carter.braydon/video/7647694374876319007"}
```

Prompt Gemini CLI to run the Actor, retain the Run ID, check status, and fetch
Dataset Items with the Dataset ID. Apify's `call-actor` returns Run status and
storage identifiers rather than Dataset items; use available Run and storage
reader tools. If those tools are not listed, adjust the selected categories
and reconnect or use this repository's code examples.

```text
Run apple_yang/tiktok-transcripts-scraper with only the videoUrl above.
Check the Run, then retrieve its Dataset Items. Return raw fields actually
present, including text, segments, and errMsg where present. A SUCCEEDED Run
does not guarantee a usable transcript; do not fabricate absent fields.
```

The field names come from the Actor's [current public Output schema](https://apify.com/apple_yang/tiktok-transcripts-scraper/output-schema).
If the result is truncated, request the same Dataset ID again. If the Run is
still active, check the same Run ID; if creation is uncertain, inspect Apify
Console before retrying or starting another Run.

Review [current Actor pricing](https://apify.com/apple_yang/tiktok-transcripts-scraper/pricing)
before calling it; no free-use or fixed-cost promise is made here.

## Validation status (checked 2026-10-27)

- **Official docs:** Gemini CLI HTTP/SSE/stdio field names and settings schema
  reviewed in the [MCP server reference](https://geminicli.com/docs/tools/mcp-server/)
  and [configuration reference](https://geminicli.com/docs/reference/configuration/).
- **Static configuration:** `httpUrl` and Actor input were compared with the
  current references; Gemini CLI was not launched.
- **Repository offline tests:** cover language API clients, not Gemini MCP
  configuration or OAuth.
- **Real MCP connection / Actor Run:** not verified.
