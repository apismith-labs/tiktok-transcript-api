# MCP compatibility and verification status

**Checked: 2026-10-27.** This matrix separates documentation and static
configuration review from client-specific connection and Actor evidence. A
documentation check does not mean that a client connected or an Actor ran.

## Status definitions

- **Official docs checked:** the named vendor's current public documentation
  was reviewed on the date shown.
- **Config statically checked:** this repository's documented endpoint,
  command, or JSON shape was compared with that documentation; it was not
  loaded into the client.
- **Repository offline tests:** the six language examples' fake-transport
  tests exercise API request and result handling. They do not test MCP client
  configuration or discovery.
- **Real MCP connection:** mark `PASS` only after the named client successfully
  connects to the service. A visible tool catalog entry is not a successful
  tool call or completed discovery validation. Documentation review, static
  configuration checks, and repository offline tests do not count.
- **Real Actor call:** mark `PASS` only after an Actor Run has actually been
  created or run through that client and its corresponding result checked. A
  successful MCP connection alone does not count.
- **Blocked:** the attempt could not proceed because of a confirmed permission
  boundary or a failed connection attempt. This is not a `PASS` or an Actor
  failure.
- **Not attempted / not verified:** no corresponding operation was performed;
  for example, no Actor Run was created.

## Matrix

| Client path | MCP server form | Official docs checked (2026-10-27) | Config statically checked | Repository offline tests | Real MCP connection | Real Actor call |
| --- | --- | --- | --- | --- | --- | --- |
| ChatGPT Web custom MCP | Apify hosted MCP / Streamable HTTP | Yes — [OpenAI help](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt) (checked 2026-10-27; plan and role rules are dynamic) | Yes — hosted endpoint and setup flow documented in [ChatGPT MCP guide](chatgpt-mcp.md) | API examples only; MCP N/A | **BLOCKED** — the user was a member of a ChatGPT Business workspace, not an admin/owner, and could not create/test the custom MCP app. No connection or tool discovery was completed. | Not attempted — no ChatGPT Actor call |
| Codex native Apify MCP plugin | Native plugin; actual transport form not recorded | N/A — native plugin path | N/A — no repository-side connector config | API examples only; MCP N/A | **PASS — Codex native MCP verified.** Actor details and input schema were read; the only required field was `videoUrl`. Earlier transport errors were followed by successful reads and execution; cause unknown. This does not verify the hosted or stdio configuration documented in this file. | **PASS — one call.** One `call-actor` succeeded; Run was `SUCCEEDED`; Dataset read returned 1 item with non-empty `text` and empty `errMsg`. The `call-actor` invocation was not retried, and no second Run was created. `maxItems: 1` and `maxTotalChargeUsd: 0.002` were distinct request settings; final charge was not reported, and the charge setting is not an independently verified absolute cap. |
| Claude Web/Desktop | Remote MCP | Yes — [Anthropic remote connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp) | Yes — remote endpoint and UI steps described | API examples only; MCP N/A | Not verified | Not verified |
| Claude Code | HTTP MCP | Yes — [Claude Code MCP](https://code.claude.com/docs/en/mcp) | Yes — CLI command, HTTP transport, and scope notes | API examples only; MCP N/A | Not verified | Not verified |
| Cursor | Client configuration format; server transport not verified | Yes — [Cursor MCP docs](https://prod.cursor.com/docs/mcp) | Yes — documented `mcpServers` format and config locations | API examples only; MCP N/A | Not verified | Not verified |
| VS Code / Copilot | Client configuration format; server transport not verified | Yes — [VS Code MCP docs](https://code.visualstudio.com/docs/agent-customization/mcp-servers) | Yes — native `servers` and portable `mcpServers` distinction | API examples only; MCP N/A | Not verified | Not verified |
| Gemini CLI | Streamable HTTP, SSE, or stdio | Yes — [MCP server docs](https://geminicli.com/docs/tools/mcp-server/) | Yes — `httpUrl` for Streamable HTTP, `url` for SSE, `command` for stdio | API examples only; MCP N/A | Not verified | Not verified |

## Repository Apify configuration paths

- **Hosted configuration:** this repository documents the Apify hosted MCP
  endpoint, but it was not separately loaded into ChatGPT Web or another
  corresponding client for this verification. Its connection remains not
  verified.
- **Local stdio configuration:** this repository documents the Apify local
  stdio option, but it was not separately launched and verified through a
  corresponding client. Its connection remains not verified.
- The Codex native Apify plugin's actual transport form was not recorded.
  Therefore, its successful verification in the matrix does not establish
  that either repository configuration above was loaded or verified.

## What repository tests establish

The offline test suites use fake HTTP transports and do not call Apify. They
validate the language examples' fixed Actor API target, request and response
handling, and selected error paths. They do **not** establish that any MCP
client accepts these settings, completes authentication, discovers the
current server tools, runs an Actor, or retrieves a Dataset.

Apify MCP tool names and auto-injected Run/storage readers can change. After
connecting, inspect the client's discovered tools. A `call-actor` response
can contain Run status and storage IDs without the Dataset items; retrieve
items separately with the available Dataset reader. For the current tool
reference, see [Apify MCP](https://docs.apify.com/mcp).

## Codex native Apify MCP verification (2026-10-27)

- `fetch-actor-details` identified
  `apple_yang/tiktok-transcripts-scraper` (Actor ID `509El6cODefVZLx2W`); the
  only required input field was `videoUrl`.
- A single `call-actor` invocation used one video URL, with
  `callOptions.maxItems: 1` and `maxTotalChargeUsd: 0.002` as separate request
  settings. It returned a successful Run; `get-actor-run` reported `SUCCEEDED`, and
  `get-dataset-items` returned one item with non-empty `text` and empty
  `errMsg`. The `call-actor` invocation was not retried, and no second Run was
  created.
- The MCP response did not include a final charge or billing record. The
  `maxItems` setting concerns the requested item limit; `maxTotalChargeUsd` is
  a separate charge-control request setting, not a confirmed final amount or an
  independently verified absolute cap.
- Earlier MCP transport errors were followed by successful read-only calls
  and this successful execution. The transport-error cause is unknown; no
  Apify, Codex, or network root cause is inferred.
- This is Codex's native Apify MCP result, whose actual transport form was not
  recorded. It does not validate the repository's hosted or stdio configuration.
  **ChatGPT Web custom MCP remains BLOCKED** because the user lacks
  administrator/owner permissions in a ChatGPT Business workspace to create
  and test a custom MCP app.
