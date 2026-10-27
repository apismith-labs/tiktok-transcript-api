# TikTok Transcript API examples

This repository shows how to call the fixed Apify Actor
[`apple_yang/tiktok-transcripts-scraper`](https://apify.com/apple_yang/tiktok-transcripts-scraper)
from cURL, Python, Node.js, Java, Go, and Rust. Each Actor Run accepts one
TikTok video URL as the `videoUrl` string; CSV examples start separate Runs
from the client, one URL at a time.

Choose a starting point:

1. **Try without writing code:** an Apify account is required. Open the
   [Actor in Apify Console](https://apify.com/apple_yang/tiktok-transcripts-scraper),
   enter a video URL in its public input, start a Run, then inspect its Dataset.
2. **Integrate with code:** follow [QuickStart](docs/quick-start.md) or pick a
   [language example](#language-examples).
3. **Use an AI client:** configure Apify MCP using the [MCP compatibility
   matrix](docs/mcp-compatibility.md) and the relevant [client guides](#mcp-guides).

Before running the Actor, review its [current pricing](https://apify.com/apple_yang/tiktok-transcripts-scraper/pricing).
The examples make no free-use or fixed-cost promise.

## First code call

You need an Apify account. Create an API token in Apify Console under
**Settings → API & Integrations**, then set it as `APIFY_TOKEN` (see Apify's
[API getting-started guide](https://docs.apify.com/api/v2/getting-started)); never publish, share, or commit the real token, or paste it into chats or AI assistant tools.

The default example video URL is:

```text
https://www.tiktok.com/@carter.braydon/video/7647694374876319007
```

For a quick cURL run, set `APIFY_TOKEN` in your shell and run from the
repository root (Bash, curl, and Python 3 are required):

```bash
export APIFY_TOKEN='your_apify_token_here'
bash examples/curl/single-url-sync.sh
```

On success, the script prints the Run ID before waiting, then displays the
transcript text and saves the complete Dataset Items to
`sample-output/generated/curl-transcript-<run-id>.json`.

To provide another video URL:

```bash
bash examples/curl/single-url-sync.sh --video-url 'https://www.tiktok.com/@user/video/1234567890'
```

The cURL script reads the process environment and does not load `.env`.
Python, Node.js, and Java can load a repository-root `.env`; Go and Rust read
the process environment. See [QuickStart](docs/quick-start.md) for setup and
runtime requirements.

## What this project does

- Calls the fixed API ID `apple_yang~tiktok-transcripts-scraper` at
  `api.apify.com`; Actor, host, and path are not user-configurable.
- Sends the minimal input `{ "videoUrl": "..." }`. The Actor does not accept
  a URL array.
- Separates Run status, Dataset reads, and transcript checks. `SUCCEEDED` does
  not guarantee a Dataset item or non-empty `text`; inspect `errMsg` too.
- Writes generated examples under `sample-output/generated/`, which Git
  ignores. No real transcript output is committed as a fixture.

Run creation uses one client-side POST attempt; that is not a server-side
exactly-once guarantee. If the result is uncertain, check Apify Console before
retrying. After a wait timeout, use the same Run ID to continue checking.

The Actor extracts transcript and metadata fields listed in its
[public Output schema](https://apify.com/apple_yang/tiktok-transcripts-scraper/output-schema).
Summaries, topic labels, hooks, and other analysis are produced by your
application or AI client from the returned data; they are not additional Actor
output fields.

## Language examples

Commands start at the repository root unless noted. Supply `APIFY_TOKEN` as
described in each language guide.

| Example | Runtime | Single-video command | Guide |
| --- | --- | --- | --- |
| cURL | Bash, curl, Python 3 | `bash examples/curl/single-url-sync.sh` | [cURL](examples/curl/README.md) |
| Python | Python 3.11+ | `python3 examples/python/single_url.py` | [Python](examples/python/README.md) |
| Node.js | Node.js 20.12+ | `node examples/nodejs/single-url.mjs` | [Node.js](examples/nodejs/README.md) |
| Java | JDK 17, Maven | `mvn -f examples/java/pom.xml -Dexec.mainClass=com.apismith.tiktok.SingleUrl compile exec:java` | [Java](examples/java/README.md) |
| Go | Go 1.22+ | `cd examples/go && go run .` | [Go](examples/go/README.md) |
| Rust | Rust 2021, Cargo lockfile v4 | `cargo run --manifest-path examples/rust/Cargo.toml --bin single_url` | [Rust](examples/rust/README.md) |

Per-language guides document URL overrides, asynchronous Run retrieval, CSV
processing, outputs, and offline checks.

## MCP guides

- [Apify MCP](docs/apify-mcp.md)
- [ChatGPT](docs/chatgpt-mcp.md)
- [Claude Web/Desktop and Claude Code](docs/claude-mcp.md)
- [Cursor and VS Code](docs/cursor-vscode-mcp.md)
- [Gemini CLI](docs/gemini-cli-mcp.md)
- [Compatibility and verification status](docs/mcp-compatibility.md)

## Documentation

- [QuickStart](docs/quick-start.md)
- [API reference](docs/api-reference.md)
- [Batch processing](docs/batch-processing.md)
- [Troubleshooting](docs/troubleshooting.md)
- [AI workflows](docs/ai-workflows.md) and [agent use cases](docs/ai-agent-use-cases.md)
- [Prompt recipes](docs/prompt-recipes.md)

## FAQ

**Do I need to write code to try it?** No. Open the Actor in Apify Console,
provide one `videoUrl`, start a Run, and inspect the Dataset. Check current
pricing before starting.

**Does a `SUCCEEDED` Run guarantee a transcript?** No. Check Run status,
Dataset availability and contents, `text`, and `errMsg` separately.

**What if Run creation has an unclear result?** Check Apify Console first; do
not immediately send another create request.

**What if waiting times out?** Continue with the same Run ID using the language
guide's `wait` command. A timeout does not mean the Run failed.

## Token safety

The only credential used by the examples is `APIFY_TOKEN`. Do not place it in
source code, URLs, logs, committed files, or shared output. The Actor ID is
fixed in code; no example reads `APIFY_ACTOR_ID`.

**Next:** [try the Actor](https://apify.com/apple_yang/tiktok-transcripts-scraper),
[start with code](docs/quick-start.md), or choose an [MCP client](docs/mcp-compatibility.md).
