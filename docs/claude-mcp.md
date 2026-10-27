# Claude and Apify MCP

Connect Claude to Apify's hosted MCP server to run the fixed Actor
[`apple_yang/tiktok-transcripts-scraper`](https://apify.com/apple_yang/tiktok-transcripts-scraper).
Claude Web/Desktop remote connectors and Claude Code are separate setup paths;
do not use a CLI command as a Desktop configuration file.
See the [MCP compatibility matrix](mcp-compatibility.md) for verification
scope across clients.

## Claude Web or Desktop: remote connector

As checked on 2026-10-27, Anthropic's help page lists remote custom connectors
for Claude Free, Pro, Max, Team, and Enterprise; Free is limited to one custom
connector. For Team/Enterprise, an Owner or Primary Owner must add the
organization connector; users then connect and enable it. Remote connections
are made from Anthropic's cloud infrastructure, so the endpoint must be
publicly reachable. See the current [Anthropic connector guide](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
for current plan and role rules.

1. In Claude Web, Claude Desktop, or Cowork, open **Customize > Connectors**.
   Team/Enterprise owners first add it under **Organization settings >
   Connectors**.
2. Add a custom connector and enter:

   ```text
   https://mcp.apify.com?tools=actors,runs,storage,apple_yang/tiktok-transcripts-scraper
   ```

3. Choose OAuth/authentication as offered, finish sign-in, then enable the
   connector in the conversation.

The endpoint is Apify hosted Streamable HTTP; this path needs no local Node.js.
For a configured local MCP server in Claude Desktop, use the separate Desktop
configuration mechanism described below and in Anthropic's [Desktop guide](https://support.anthropic.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop).

## Claude Code: terminal setup

Claude Code uses its own CLI and MCP scopes. Run this in a terminal where
Claude Code is available:

```bash
claude mcp add --transport http apify 'https://mcp.apify.com?tools=actors,runs,storage,apple_yang/tiktok-transcripts-scraper'
```

This adds a remote HTTP server at the CLI's default local scope. Add
`--scope user` or `--scope project` only if you intend that scope; project
servers use a repository `.mcp.json` and require workspace approval. Verify
the configured server with `claude mcp get apify`, and inspect connection
status with `claude mcp list` or `/mcp`. Claude Code can handle the server's
OAuth flow. Bearer credentials, if used, should be entered through a secure
header mechanism, not committed in `.mcp.json`.

## Claude Desktop: local stdio alternative

Use local stdio only if you specifically need a locally launched server. The
Desktop configuration uses an `mcpServers` JSON object. As checked on
2026-10-27, Apify's troubleshooting docs say Node.js 18+, while its public
package manifest declares `engines.node >=22.0.0`; the npm listing and public
manifest do not currently identify the same package revision. Use Node.js 22+
for local stdio based on the manifest; hosted remote MCP does not need local
Node.js. See the [source comparison](apify-mcp.md#local-stdio-option).

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

`<APIFY_TOKEN>` is a placeholder; do not assume Claude Desktop expands
`${APIFY_TOKEN}`. Replace it or inject the secret only through a secure method
documented for your Claude Desktop version and operating system. Prefer the
hosted OAuth option above when available. Do not put a real token in a shared
or committed config file. See Anthropic's [Desktop guide](https://support.anthropic.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop)
for current configuration details.

## Run and read output

The only Actor input is one `videoUrl`:

```json
{"videoUrl":"https://www.tiktok.com/@carter.braydon/video/7647694374876319007"}
```

Ask Claude to invoke the Actor, retain the returned Run ID, check that Run's
status, and read Dataset Items using the returned Dataset ID. Apify's
`call-actor` may return status and storage IDs rather than Dataset contents;
use the available Run and Dataset reader tools. See [Apify MCP tool details](apify-mcp.md#calling-the-actor-and-reading-its-output).

```text
Run apple_yang/tiktok-transcripts-scraper with only the videoUrl shown above.
Read the completed Run's Dataset Items and report the fields actually present,
especially text, segments, and errMsg. Separate any summary or opening-hook
analysis as your own analysis, and do not invent absent Actor fields.
```

The fields are based on the Actor's [public Output schema](https://apify.com/apple_yang/tiktok-transcripts-scraper/output-schema).
Run `SUCCEEDED` does not prove the Dataset or transcript is non-empty. Check
the actual items and `errMsg`.

## Troubleshooting and cost

- **Connector/tool missing:** check its client-specific scope, workspace
  approval, selected Apify tools, then reconnect.
- **Authentication/network failure:** complete OAuth again and ensure the
  hosted endpoint is reachable from the public internet. A local-only URL is
  not reachable from Anthropic's cloud connector.
- **Run still active:** check the same Run ID again; do not launch another Run
  because a wait ended.
- **Creation result unknown:** inspect Apify Console before retrying. One
  client request is not a server-side exactly-once guarantee.
- **Truncated/empty output:** retrieve the same Dataset Items again and report
  Run, Dataset, `text`, and `errMsg` states separately.

Review the Actor's [current pricing](https://apify.com/apple_yang/tiktok-transcripts-scraper/pricing)
before a call. The current price can change; this guide does not promise free
use or a fixed charge.

## Validation status (checked 2026-10-27)

- **Official docs:** remote connectors, plan/organization roles, network path,
  and Claude Code commands/scopes reviewed in the Anthropic links above.
- **Static configuration:** the remote URL, CLI command, and stdio JSON shape
  were checked against current docs; no Claude client was launched.
- **Repository offline tests:** cover the language API clients, not Claude
  connector discovery, OAuth, or Claude Code MCP startup.
- **Real MCP connection / Actor Run:** not verified.
