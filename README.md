# TikTok Transcript API examples

This repository contains runnable integration examples for the fixed Apify
Actor [`apple_yang/tiktok-transcripts-scraper`](https://apify.com/apple_yang/tiktok-transcripts-scraper).
The Actor accepts one `videoUrl` string per Run. The examples show a single
video call, separate `start` / `wait` flows, and client-side CSV fan-out where
implemented.

**Try the Actor:** [Open the Apify Actor](https://apify.com/apple_yang/tiktok-transcripts-scraper)
to run it from Apify Console. This GitHub repository is for copying the same
integration into your own code.

## Quick start

From the repository root, provide your token in the shell and run the cURL
example (Bash, curl, and Python 3 are required):

```bash
export APIFY_TOKEN='your_apify_token_here'
bash examples/curl/single-url-sync.sh
```

The script uses this default TikTok video URL:

```text
https://www.tiktok.com/@carter.braydon/video/7647694374876319007
```

To use another video, pass `--video-url`:

```bash
bash examples/curl/single-url-sync.sh --video-url 'https://www.tiktok.com/@user/video/1234567890'
```

The cURL script reads `APIFY_TOKEN` from the process environment and does not
load `.env`. Python, Node.js, and Java also load a repository-root `.env`; Go
and Rust read the process environment only. See [QuickStart](docs/quick-start.md)
for per-language setup and the exact commands.

## What the examples do

- Call the fixed Actor API ID `apple_yang~tiktok-transcripts-scraper` at
  `api.apify.com`. There is no Actor ID setting to change.
- Send only `{ "videoUrl": "..." }` as Actor input. A CSV client starts one
  independent Run per valid row; the Actor itself does not accept URL arrays.
- Read the Run status and Dataset separately. `SUCCEEDED` alone does not mean
  transcript text is available; inspect Dataset items, `text`, and `errMsg`.
- Save outputs under `sample-output/generated/`, which Git ignores. The
  repository does not include a committed raw transcript sample; learn how to
  inspect a generated Dataset in the [API reference](docs/api-reference.md).

Run creation uses one client-side POST attempt, which is not a server-side
exactly-once guarantee. If creation has an uncertain result, check Apify Console
before retrying. After a wait timeout, continue with the same Run ID.

## Language examples

Commands below start from the repository root unless noted. Set `APIFY_TOKEN`
as described in each language guide.

| Example | Runtime | Single-video command | Guide |
| --- | --- | --- | --- |
| cURL | Bash, curl, Python 3 | `bash examples/curl/single-url-sync.sh` | [cURL](examples/curl/README.md) |
| Python | Python 3.11+ | `python3 examples/python/single_url.py` | [Python](examples/python/README.md) |
| Node.js | Node.js 20.12+ | `node examples/nodejs/single-url.mjs` | [Node.js](examples/nodejs/README.md) |
| Java | JDK 17, Maven | `mvn -f examples/java/pom.xml -Dexec.mainClass=com.apismith.tiktok.SingleUrl compile exec:java` | [Java](examples/java/README.md) |
| Go | Go 1.22+ | `cd examples/go && go run .` | [Go](examples/go/README.md) |
| Rust | Rust 2021, Cargo lockfile v4 | `cargo run --manifest-path examples/rust/Cargo.toml --bin single_url` | [Rust](examples/rust/README.md) |

The per-language guides include URL overrides, async Run retrieval, CSV batch
commands, output files, and offline tests.

## Documentation

- [QuickStart](docs/quick-start.md)
- [API reference](docs/api-reference.md)
- [Batch processing](docs/batch-processing.md)
- [Troubleshooting](docs/troubleshooting.md)
- [AI workflows](docs/ai-workflows.md) and [agent use cases](docs/ai-agent-use-cases.md)
- [Prompt recipes](docs/prompt-recipes.md)
- [Apify MCP](docs/apify-mcp.md), [ChatGPT](docs/chatgpt-mcp.md),
  [Claude](docs/claude-mcp.md), [Cursor / VS Code](docs/cursor-vscode-mcp.md),
  and [Gemini CLI](docs/gemini-cli-mcp.md)

## Token safety

Provide only `APIFY_TOKEN` as a credential. Do not place it in source code,
URLs, logs, committed files, or shared output. The Actor ID is fixed in the
examples; do not configure `APIFY_ACTOR_ID`.
