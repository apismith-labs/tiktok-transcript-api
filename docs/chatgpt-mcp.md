# ChatGPT and Apify MCP

This guide connects ChatGPT to Apify's hosted MCP server for the fixed Actor
[`apple_yang/tiktok-transcripts-scraper`](https://apify.com/apple_yang/tiktok-transcripts-scraper).
This repository does not include a ChatGPT app, Custom GPT Action, hosted
backend, or MCP server. If your ChatGPT workspace cannot add custom MCP
servers, use one of the [repository code examples](quick-start.md).
See the [MCP compatibility matrix](mcp-compatibility.md) for verification
scope across clients.

## Availability and setup

As checked on 2026-10-27, OpenAI's current help page says custom MCP server
connections with full MCP support are available on ChatGPT Business and
Enterprise/Edu on the web. ChatGPT Pro can connect to custom MCP servers only
with read/fetch permissions; this is enough to connect and retrieve permitted
data, but not to call an Actor or perform write/modify actions. This example
requires the Apify `call-actor` tool to create a Run, so Pro's read/fetch-only
access does not provide the full workflow described here. Business creation
and publishing are limited to admins/owners. Enterprise/Edu admins and owners
can create and test connections; admins can grant selected members permission
to create them, while only admins/owners can publish. These plan and role
rules are dynamic; consult [OpenAI's current help page](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt)
for changes.

1. In ChatGPT web, open **Plugins**, select **+**, then **Add custom MCP
   server**.
2. Give the connection a name such as `Apify TikTok transcripts`.
3. Enter this public HTTPS endpoint:

   ```text
   https://mcp.apify.com?tools=actors,runs,storage,apple_yang/tiktok-transcripts-scraper
   ```

4. Select the authentication method offered for the Apify server. Prefer its
   OAuth flow. Review the risk notice and create the connection.
5. Review the discovered tools, then enable the connector in the conversation.

The endpoint uses Apify's hosted Streamable HTTP service. It does not require
local Node.js. The `tools` selector enables categories as well as the specified
Actor tool; it does not promise a single exposed operation. For tool behavior
and the separate Run/Dataset retrieval steps, see [Apify MCP setup](apify-mcp.md).

## Test prompt

```text
Use the Apify MCP tools to run apple_yang/tiktok-transcripts-scraper with only:
{"videoUrl":"https://www.tiktok.com/@carter.braydon/video/7647694374876319007"}
Wait for that Run, then read its Dataset Items using the returned Dataset ID.
Report the available raw fields among text, segments, and errMsg. Do not invent
missing fields, and distinguish Run status from transcript availability.
```

The URL above is an illustrative documentation example; it does not identify
the input used in the recorded MCP verification.

The prompt asks for output fields listed in the Actor's
[public Output schema](https://apify.com/apple_yang/tiktok-transcripts-scraper/output-schema).
Any summary, hook analysis, classification, or JSON synthesis is ChatGPT's
analysis of the retrieved Dataset, not an Actor output field. Check the actual
Dataset item: a `SUCCEEDED` Run does not guarantee non-empty transcript text.

## Troubleshooting

- **No custom MCP option:** verify workspace plan and permissions with an
  administrator; otherwise use the repository's cURL or language examples.
- **No Apify tools found:** reconnect and inspect the tool scan. If the Actor
  tool or Dataset reader is absent, use the Apify MCP configurator and check
  the tool selection.
- **Authorization fails:** complete OAuth again and confirm the intended Apify
  account has access to the Actor.
- **Run is not finished:** continue checking the same Run ID. Do not start a
  second Run because waiting stopped.
- **Create response is unclear:** inspect Apify Console before retrying. One
  client send attempt does not guarantee server-side exactly-once creation.
- **Empty transcript / `errMsg`:** return the raw Dataset status and error
  rather than calling the extraction successful.
- **Truncated result:** ask ChatGPT to retrieve Dataset Items for the same
  Dataset ID before summarizing.

Check the Actor's [current pricing](https://apify.com/apple_yang/tiktok-transcripts-scraper/pricing)
before running it; this guide makes no free-use or fixed-cost promise.

## Validation status (checked 2026-10-27)

ChatGPT Web custom MCP and Codex's native Apify MCP plugin are separate clients;
evidence for one does not verify the other.

- **ChatGPT Web custom MCP — BLOCKED:** the user was a member of a ChatGPT
  Business workspace rather than an administrator or owner, and could not
  create or test a custom MCP app. The ChatGPT Web
  connector was not configured; its connection, tool discovery, reads, and
  Actor execution remain unverified.
- **Codex native Apify MCP — verified for one run:**
  `fetch-actor-details` returned the fixed Actor details (Actor ID
  `509El6cODefVZLx2W`); the only required input field was `videoUrl`. One
  `call-actor` call succeeded, followed by a successful Run query
  (`SUCCEEDED`) and Dataset read (one item, non-empty `text`, empty `errMsg`).
  The `call-actor` invocation was not retried, and no second Run was created.
  This verifies one Codex native MCP
  execution path, not ChatGPT Web custom MCP.
- **Cost and prior transport errors:** the call supplied
  `callOptions.maxItems: 1` (an item-limit setting) and
  `maxTotalChargeUsd: 0.002` (a separate charge-control request setting). The
  MCP result did not report the final charge; the charge setting is not a
  confirmed final bill or independently verified absolute cap. Earlier
  transport errors were followed by
  successful read-only calls and this successful execution; their cause is
  unknown.
- **Repository offline tests:** exercise language API examples, not either
  client's connector discovery, authentication, or live reads.

For a read-only Codex MCP check, call `get-actor-run` for an existing Run and
pass the Dataset ID returned by that Run to `get-dataset-items`. Do not create
a new Run just to verify the documentation.
