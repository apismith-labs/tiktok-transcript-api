# Apify MCP for the TikTok Transcript Actor

Use the Apify MCP server to call the fixed Actor
[`apple_yang/tiktok-transcripts-scraper`](https://apify.com/apple_yang/tiktok-transcripts-scraper).
Each Actor call accepts one `videoUrl` string. This repository does not host
an MCP server or provide a ChatGPT/Claude plugin.

For a side-by-side view of configuration paths and verification evidence, see
the [MCP compatibility matrix](mcp-compatibility.md).

## Hosted server (recommended)

The hosted endpoint is `https://mcp.apify.com` and uses Streamable HTTP. It
supports OAuth; clients that cannot use OAuth can send an Apify token as a
Bearer authorization header. A hosted connection does not require Node.js on
your computer.

Apify's `tools` selector accepts tool categories, tool names, and Actor tools.
This example enables actor execution, Run and storage readers, and the TikTok
Actor tool. Categories enable multiple operations; they do not mean “one tool
only.” The exact discovered tools can change as the server evolves.

```text
https://mcp.apify.com?tools=actors,runs,storage,apple_yang/tiktok-transcripts-scraper
```

Prefer the Apify MCP configurator at [mcp.apify.com](https://mcp.apify.com/) to
copy the hosted URL into your client. Use OAuth when offered. If configuring a
Bearer header manually, keep it in the client's secret store or a private local
configuration; never commit it:

```text
Authorization: Bearer <APIFY_TOKEN>
```

## Local stdio option

Use stdio only when the client requires a local process. It uses the npm
package `@apify/actors-mcp-server`; `npx` may download that package on first
use. Checked 2026-10-27, Apify's [MCP troubleshooting docs](https://docs.apify.com/mcp#troubleshooting)
say local stdio needs Node.js 18 or higher. The [current npm package listing](https://www.npmjs.com/package/@apify/actors-mcp-server)
and the upstream [`package.json`](https://github.com/apify/apify-mcp-server/blob/master/package.json)
do not identify the same package revision: the listing reports a newer release,
while the public manifest's `version` field is behind. That manifest declares
`engines.node` as `>=22.0.0`. The latest published tarball's own manifest could
not be independently confirmed from the available package page, so use
Node.js 22+ as the local stdio runtime floor based on the public manifest and
recheck release metadata when upgrading. This local stdio requirement does not
apply to hosted MCP. These sources were checked on 2026-10-27.

```json
{
  "mcpServers": {
    "apify": {
      "command": "npx",
      "args": [
        "-y",
        "@apify/actors-mcp-server@latest",
        "--tools",
        "actors,runs,storage,apple_yang/tiktok-transcripts-scraper"
      ],
      "env": {
        "APIFY_TOKEN": "<APIFY_TOKEN>"
      }
    }
  }
}
```

`<APIFY_TOKEN>` is a placeholder, not a promise that a client expands
`${APIFY_TOKEN}`. Replace it or inject the secret using the selected client's
documented secure mechanism. Client environment-variable support and expansion
rules differ. Prefer hosted OAuth when available, and never commit a config
file containing a real token.

## Calling the Actor and reading its output

The Actor input is exactly one URL:

```json
{
  "videoUrl": "https://www.tiktok.com/@carter.braydon/video/7647694374876319007"
}
```

The TikTok URL shown in these examples is illustrative documentation input; it
does not represent the input used in the recorded Codex native MCP verification.

Apify documents `call-actor` as starting an Actor and returning Run status and
storage IDs, not Dataset results. Use the returned Run ID with `get-actor-run`
if you need to inspect status, then use the returned Dataset ID with
`get-dataset-items` to read items. The current Apify MCP tool reference says
the Run/Dataset reader tools are automatically added when `call-actor` or an
Actor tool is selected; still inspect the tools exposed by your connected
server because available tools and response details can change. See Apify's
[tool reference](https://docs.apify.com/mcp#available-tools) and
[tool selection guide](https://docs.apify.com/mcp#tool-selection).

Use a prompt such as:

```text
Run apple_yang/tiktok-transcripts-scraper with only this Actor input:
{"videoUrl":"https://www.tiktok.com/@carter.braydon/video/7647694374876319007"}
After the Run finishes, read the Dataset Items using the Run's Dataset ID.
Return the raw available fields, especially text, segments, and errMsg. Do not
invent missing fields or infer transcript success from SUCCEEDED alone.
```

The current [public Output schema](https://apify.com/apple_yang/tiktok-transcripts-scraper/output-schema)
lists fields such as `text`, `segments`, and `errMsg`; inspect the actual item
before using any value. A successful Run may still have an empty Dataset,
blank text, or a non-empty `errMsg`. `videoUrl` is an input and is not promised
as an output field; `audioUrl` is not in the public schema.

## If something goes wrong

- **Actor tool is missing:** inspect the client's discovered tool list and
  confirm the selected Actor tool/category; reconnect after changing config.
- **Authorization fails:** complete Apify OAuth again, or check the token in
  the client secret store. Do not paste a token into chat or a shared file.
- **Run is still running:** keep the same Run ID and check it again; do not
  create a second Run just because a client stopped waiting.
- **Create result is unclear:** inspect Apify Console before retrying. A
  client's one send attempt is not a server-side exactly-once guarantee.
- **Output is truncated:** request `get-dataset-items` for the same Dataset ID
  and inspect the returned items before asking for a summary.
- **Transcript is empty or has `errMsg`:** report that state rather than
  treating Run success as transcript success.

Review the Actor's [current pricing](https://apify.com/apple_yang/tiktok-transcripts-scraper/pricing)
before starting a Run. This repository does not promise a free run or a fixed
charge.

## Validation status (checked 2026-10-27)

- **Official docs:** Apify hosted transport, tool selection, Run/storage tools,
  and local package prerequisites reviewed; links above.
- **Static configuration:** endpoint, selector syntax, and this JSON example
  were checked against the published client formats; no client was launched.
- **Repository offline tests:** cover the language API clients, not MCP client
  configuration or MCP discovery.
- **Repository configuration load:** the hosted and local stdio configurations
  documented here were not separately loaded into a client during this update.
- **Codex native Apify MCP:** a separate Codex-native verification completed
  successfully, including one Actor call and a Dataset read. Its actual
  transport form was not recorded, so it does not establish that the hosted or
  stdio configuration in this guide was loaded or verified. See the
  [MCP compatibility matrix](mcp-compatibility.md#codex-native-apify-mcp-verification-2026-10-27)
  for the recorded scope and ChatGPT Web status.
- **ChatGPT Web custom MCP:** remains blocked by workspace permissions; see
  [ChatGPT MCP validation status](chatgpt-mcp.md#validation-status-checked-2026-10-27).
